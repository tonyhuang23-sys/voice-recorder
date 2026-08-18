"""Headless meeting job: audio → ASR → translate → summarize → save → optional Lark."""
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
                 transcript=None, lark_pushed=False):
        self.ok = ok
        self.folder = folder
        self.error = error
        self.files = files or {}
        self.summary = summary
        self.transcript = transcript or []
        self.lark_pushed = lark_pushed


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
                self._emit(f"   → {dst}")
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
    stop_event=None,
    asr=None,
    translator=None,
    summarizer=None,
    log=None,
):
    """Run the full pipeline once (file/url) or until stopped (live).

    Fails gracefully when models or the Lark webhook are missing.
    Live audio and extracted file audio are persisted as audio.wav in the
    meeting output folder.
    """
    emit = log or (lambda m: logger.info("%s", m))
    if target_lang:
        cfg.setdefault("translate", {})["target_lang"] = target_lang

    folder = output.meeting_folder(title)
    wav_path = output.audio_path(folder)
    emit(f"输出目录: {folder}")

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
        return JobResult(ok=False, folder=folder, error=str(e))

    collector = _Collector(log=emit)
    asr = asr or ASRManager(cfg)
    translator = translator or Translator(cfg)
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
        return JobResult(ok=False, folder=folder, error=str(e))
    finally:
        try:
            pipeline.stop()
        except Exception:
            pass
        collector.done.wait(timeout=1)

    files = {}
    files["audio"] = wav_path if os.path.isfile(wav_path) else None
    files["transcript"] = output.save_transcript(folder, collector.lines)
    if collector.pairs:
        files["translation"] = output.save_translation(folder, collector.pairs)

    summary = ""
    try:
        engine = summarizer or Summarizer(cfg)
        summary = engine.summarize(collector.lines, title=title)
        files["summary"] = output.save_summary(folder, summary)
    except Exception as e:
        logger.warning("summarize failed: %s", e)
        summary = f"（摘要失败: {e}）"
        try:
            files["summary"] = output.save_summary(folder, summary)
        except Exception:
            pass

    emit(f"已保存到: {folder}")

    error = collector.error
    if not collector.lines and error:
        error = f"{error}\n{MODEL_HINT}"
        return JobResult(
            ok=False, folder=folder, error=error, files=files,
            summary=summary, transcript=collector.lines,
        )

    lark_pushed = False
    if push_lark:
        lark_pushed = _maybe_push_lark(cfg, title, summary, folder, emit)

    return JobResult(
        ok=True, folder=folder, files=files, summary=summary,
        transcript=collector.lines, lark_pushed=lark_pushed,
    )


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


def _maybe_push_lark(cfg, title, summary, folder, emit):
    pusher = LarkPusher(cfg)
    if not pusher.is_configured():
        emit("Lark webhook 未配置,跳过推送 (设置 LARK_WEBHOOK_URL 或 config.json lark.webhook_url)")
        return False
    extra = f"输出目录: {folder}" if folder else ""
    try:
        pusher.push_meeting(title, summary, extra=extra)
        emit("已推送到飞书/Lark")
        return True
    except Exception as e:
        logger.warning("Lark push failed: %s", e)
        emit(f"飞书/Lark 推送失败: {e}")
        return False
