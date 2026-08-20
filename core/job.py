"""Headless meeting job: audio → ASR → translate → summarize → four artifacts → Lark/email."""
import logging
import os
import threading

from . import output
from .asr import ASRManager
from .audio_source import (
    FileSource,
    LoopbackCapture,
    MicrophoneCapture,
    TeeSource,
    download_audio_from_link,
    ensure_16k_mono_wav,
    find_loopback_device,
)
from .emailer import EmailSender
from .lark import LarkPusher
from .pipeline import MeetingPipeline
from .summarizer import Summarizer
from .translator import Translator

logger = logging.getLogger(__name__)

MODEL_HINT = (
    "ASR failed. Place models under models/ or run: python app.py "
    "and click [检查环境/下载模型]."
)


class JobResult:
    def __init__(self, ok, folder, error=None, files=None, summary="",
                 transcript=None, lark_pushed=False, email_sent=False):
        self.ok = ok
        self.folder = folder
        self.error = error
        self.files = files or {}
        self.summary = summary
        self.transcript = transcript or []
        self.lark_pushed = lark_pushed
        self.email_sent = email_sent


class _Collector:
    def __init__(self, log=None):
        self.lines = []
        self.pairs = []
        self.done = threading.Event()
        self.error = None
        self._log = log

    def __call__(self, kind, payload):
        if kind == "line":
            self.lines.append((payload["ts"], payload["speaker"], payload["text"]))
            self._emit(f"[{payload['ts']}] {payload['text']}")
        elif kind == "trans":
            self.pairs.append(payload)
            dst = (payload or {}).get("dst") or ""
            if dst:
                self._emit(f"   -> {dst}")
        elif kind == "status":
            if payload:
                text = str(payload)
                if text.startswith("错误"):
                    self.error = text
                self._emit(text)
        elif kind == "done":
            self.done.set()

    def _emit(self, msg):
        if self._log:
            try:
                self._log(msg)
            except Exception:
                pass


def complete_translations(lines, pairs, translator, target_lang="zh"):
    """Ensure every transcript line has a translation pair for 翻译.txt."""
    by_src = {}
    for item in pairs or []:
        src = (item or {}).get("src")
        if src:
            by_src[src] = item
    out = []
    for _ts, _speaker, text in lines or []:
        if not text or not str(text).strip():
            continue
        if text in by_src and (by_src[text] or {}).get("dst"):
            out.append(by_src[text])
            continue
        src_lang = "zh" if output.looks_like_chinese(text) else "en"
        dst_lang = target_lang or "zh"
        if src_lang == dst_lang:
            dst_lang = "en" if src_lang == "zh" else "zh"
        trans = ""
        if translator is not None:
            try:
                trans = translator.translate(text, src_lang, dst_lang) or ""
            except Exception as e:
                logger.warning("translate line failed: %s", e)
        out.append({"src": text, "dst": trans or "（未翻译）"})
    return out


def chinese_summary(cfg, lines, title, summarizer=None, translator=None):
    engine = summarizer or Summarizer(cfg)
    try:
        text = engine.summarize(lines or [], title=title)
    except Exception as e:
        logger.warning("summarize failed: %s", e)
        text = f"（摘要失败: {e}）"
    text = text or "（无摘要）"
    if not output.looks_like_chinese(text) and translator is not None:
        try:
            zh = translator.translate(text, "en", "zh")
            if zh:
                text = zh
        except Exception as e:
            logger.warning("summary translate-to-zh failed: %s", e)
    return text


def run_meeting_job(
    cfg,
    *,
    title="会议记录",
    target_lang=None,
    file_path=None,
    url=None,
    live=None,
    device_index=None,
    push_lark=False,
    send_email=False,
    stop_event=None,
    asr=None,
    translator=None,
    summarizer=None,
    log=None,
):
    """Run the full pipeline once (file/url) or until stopped (live).

    Always writes four artifacts in the meeting folder:
      audio.wav, 转写记录.txt, 翻译.txt, 会议摘要.txt

    Headless delivery: if Lark/email are configured (or flags are set),
    send both. Fails gracefully when models / webhook / SMTP are missing.
    """
    emit = log or (lambda m: logger.info("%s", m))
    if target_lang:
        cfg.setdefault("translate", {})["target_lang"] = target_lang
    target_lang = (target_lang or cfg.get("translate", {}).get("target_lang") or "zh")

    folder = output.meeting_folder(title)
    wav_path = output.audio_path(folder)
    emit(f"输出目录: {folder}")

    asr = asr or ASRManager(cfg)
    translator = translator or Translator(cfg)
    collector = _Collector(log=emit)

    try:
        source = _build_source(
            cfg,
            folder=folder,
            wav_path=wav_path,
            file_path=file_path,
            url=url,
            live=live,
            device_index=device_index,
            emit=emit,
        )
    except Exception as e:
        logger.exception("prepare audio failed")
        files = _write_artifacts(
            folder, wav_path, [], [], f"（音频准备失败: {e}）",
            translator, target_lang, cfg, summarizer=None,
        )
        return JobResult(ok=False, folder=folder, error=str(e), files=files)

    pipeline = MeetingPipeline(
        cfg, asr=asr, translator=translator, source=source, callback=collector,
    )

    try:
        pipeline.start()
        if live:
            emit("正在接听 (Ctrl+C 结束)...")
            _wait_until_stop(pipeline, stop_event)
        else:
            while pipeline.running and pipeline.thread and pipeline.thread.is_alive():
                if stop_event is not None and stop_event.is_set():
                    break
                pipeline.thread.join(timeout=0.4)
    except KeyboardInterrupt:
        emit("收到中断,正在结束...")
    except Exception as e:
        logger.exception("pipeline failed")
        try:
            pipeline.stop()
        except Exception:
            pass
        files, summary = _finalize_artifacts(
            folder, wav_path, collector, translator, target_lang, cfg,
            title, summarizer, emit, extra_error=str(e),
        )
        emailed, larked = _deliver(
            cfg, title, summary, folder, emit,
            want_lark=push_lark, want_email=send_email,
        )
        return JobResult(
            ok=False, folder=folder, error=str(e), files=files,
            summary=summary, transcript=collector.lines,
            lark_pushed=larked, email_sent=emailed,
        )
    finally:
        try:
            pipeline.stop()
        except Exception:
            pass
        collector.done.wait(timeout=1)

    files, summary = _finalize_artifacts(
        folder, wav_path, collector, translator, target_lang, cfg,
        title, summarizer, emit,
    )
    emit(f"已保存四件套: {folder}")

    error = collector.error
    ok = True
    if not collector.lines and error:
        error = f"{error}\n{MODEL_HINT}"
        ok = False

    emailed, larked = _deliver(
        cfg, title, summary, folder, emit,
        want_lark=push_lark, want_email=send_email,
    )
    return JobResult(
        ok=ok, folder=folder, error=error if not ok else None, files=files,
        summary=summary, transcript=collector.lines,
        lark_pushed=larked, email_sent=emailed,
    )


def _finalize_artifacts(folder, wav_path, collector, translator, target_lang,
                        cfg, title, summarizer, emit, extra_error=None):
    pairs = complete_translations(
        collector.lines, collector.pairs, translator, target_lang=target_lang,
    )
    summary = chinese_summary(
        cfg, collector.lines, title, summarizer=summarizer, translator=translator,
    )
    if extra_error and not collector.lines:
        summary = f"（处理失败: {extra_error}）\n{summary}"
    files = output.save_four_artifacts(
        folder, collector.lines, pairs, summary, wav_path=wav_path,
        sample_rate=int(cfg.get("audio", {}).get("sample_rate", 16000)),
    )
    emit(f"  {output.ARTIFACT_WAV}")
    emit(f"  {output.ARTIFACT_TRANSCRIPT}")
    emit(f"  {output.ARTIFACT_TRANSLATION}")
    emit(f"  {output.ARTIFACT_SUMMARY}")
    return files, summary


def _write_artifacts(folder, wav_path, lines, pairs, summary, translator,
                     target_lang, cfg, summarizer=None):
    pairs = complete_translations(lines, pairs, translator, target_lang=target_lang)
    return output.save_four_artifacts(
        folder, lines, pairs, summary, wav_path=wav_path,
        sample_rate=int(cfg.get("audio", {}).get("sample_rate", 16000)),
    )


def _deliver(cfg, title, summary, folder, emit, want_lark=False, want_email=False):
    """Send email then Lark when configured (or when the CLI flags are set)."""
    sender = EmailSender(cfg)
    pusher = LarkPusher(cfg)
    do_email = bool(want_email) or sender.is_configured()
    do_lark = bool(want_lark) or pusher.should_push()

    emailed = False
    if do_email:
        emailed = _maybe_send_email(sender, title, summary, folder, emit)
    elif want_email:
        emit("邮件未配置,跳过 (设置 SMTP / GMAIL_APP_PASSWORD,或 MEETING_EMAIL_TO)")

    larked = False
    if do_lark:
        larked = _maybe_push_lark(pusher, title, summary, folder, emit, emailed=emailed)
    elif want_lark:
        emit("Lark webhook 未配置,跳过推送 (设置 LARK_WEBHOOK_URL 或 config.json lark.webhook_url)")
    return emailed, larked


def _build_source(cfg, folder, wav_path, file_path, url, live, device_index, emit):
    sr = int(cfg.get("audio", {}).get("sample_rate", 16000))
    if file_path:
        emit(f"准备音频文件: {file_path}")
        ensure_16k_mono_wav(file_path, wav_path)
        emit(f"已写入: {wav_path}")
        return FileSource(wav_path, sr=sr)
    if url:
        emit(f"下载链接音频: {url}")
        download_audio_from_link(url, wav_path)
        emit(f"已写入: {wav_path}")
        return FileSource(wav_path, sr=sr)
    if live == "mic":
        inner = MicrophoneCapture(cfg, device_index=device_index)
        return TeeSource(inner, wav_path, sample_rate=sr)
    if live == "loopback":
        idx = device_index
        if idx is None:
            idx = find_loopback_device()
        if idx is None:
            raise RuntimeError(
                "未找到系统声音捕获设备(Stereo Mix / loopback)。"
                "请在 Windows 声音设置中启用立体声混音,或安装 VB-Cable。"
            )
        inner = LoopbackCapture(cfg, device_index=idx)
        return TeeSource(inner, wav_path, sample_rate=sr)
    raise RuntimeError("no audio source (need --file / --url / --mic / --loopback)")


def _wait_until_stop(pipeline, stop_event):
    while pipeline.running and pipeline.thread and pipeline.thread.is_alive():
        if stop_event is not None and stop_event.is_set():
            break
        pipeline.thread.join(timeout=0.4)


def _maybe_send_email(sender, title, summary, folder, emit):
    if not sender.is_configured():
        emit("邮件未配置,跳过发送 (SMTP 或 GMAIL_USER / GMAIL_APP_PASSWORD)")
        return False
    try:
        info = sender.send_meeting_package(title, summary, folder)
        to = ", ".join(info.get("to") or [])
        emit(f"已邮件发送至 {to}: {', '.join(info.get('attachments') or [])}")
        for note in info.get("notes") or []:
            emit(note)
        return True
    except Exception as e:
        logger.warning("email send failed: %s", e)
        emit(f"邮件发送失败: {e}")
        return False


def _maybe_push_lark(pusher, title, summary, folder, emit, emailed=None):
    if not pusher.is_configured():
        emit("Lark webhook 未配置,跳过推送 (设置 LARK_WEBHOOK_URL 或 config.json lark.webhook_url)")
        return False
    extra = f"输出目录: {folder}" if folder else ""
    try:
        pusher.push_meeting(title, summary, extra=extra, emailed=emailed)
        emit("已推送中文摘要到飞书/Lark 会话")
        return True
    except Exception as e:
        logger.warning("Lark push failed: %s", e)
        emit(f"飞书/Lark 推送失败: {e}")
        return False
