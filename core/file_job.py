"""Headless job: transcribe a local audio file and write summary beside it."""
import logging
import os
import threading

from copy import deepcopy

from .asr import ASRManager
from .audio_source import FileSource
from .output import save_summary, save_transcript
from .pipeline import MeetingPipeline
from .summarizer import Summarizer

logger = logging.getLogger(__name__)


def _safe_stem(name):
    stem = os.path.splitext(os.path.basename(name))[0].strip() or "录音"
    return "".join(c if c not in '\\/:*?"<>|' else "_" for c in stem)


def process_audio_file(audio_path, cfg, out_dir=None, title=None,
                       asr=None, translator=None, on_line=None, on_status=None):
    """Transcribe ``audio_path`` and write 转写 + summary into the same folder.

    Returns a dict with keys: folder, transcript, summary, lines, summary_text, title.
    """
    audio_path = os.path.abspath(os.path.expanduser(audio_path))
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"音频文件不存在: {audio_path}")

    folder = os.path.abspath(out_dir) if out_dir else os.path.dirname(audio_path)
    os.makedirs(folder, exist_ok=True)
    title = (title or _safe_stem(audio_path)).strip() or "会议记录"
    stem = _safe_stem(title)

    cfg = deepcopy(cfg)
    cfg.setdefault("translate", {})["auto"] = False

    if on_status:
        on_status("正在加载音频...")
    source = FileSource(audio_path, sample_rate=int(cfg["audio"]["sample_rate"]))
    asr = asr or ASRManager(cfg)

    lines_box = []
    done = threading.Event()

    def callback(kind, payload):
        if kind == "line":
            lines_box.append((payload["ts"], payload["speaker"], payload["text"]))
            if on_line:
                on_line(payload)
        elif kind == "status" and on_status and payload:
            on_status(payload)
        elif kind == "done":
            done.set()

    if on_status:
        on_status("正在转写...")
    pipeline = MeetingPipeline(
        cfg, asr=asr, translator=translator, source=source, callback=callback)
    pipeline.start()
    timeout = max(120.0, len(source._samples) / max(1, source.sample_rate) * 8 + 60)
    if pipeline.thread:
        pipeline.thread.join(timeout=timeout)
    if pipeline.running:
        pipeline.stop()
    done.wait(timeout=5)

    lines = pipeline.get_transcript() or lines_box
    if on_status:
        on_status("正在生成摘要...")
    summary_text = Summarizer(cfg).summarize(lines, title=title)

    transcript_name = f"{stem}_转写记录.txt"
    summary_txt_name = f"{stem}_会议摘要.txt"
    summary_md_name = f"{stem}_summary.md"
    transcript_path = save_transcript(folder, lines, filename=transcript_name)
    summary_txt_path = save_summary(folder, summary_text, filename=summary_txt_name)
    summary_md_path = os.path.join(folder, summary_md_name)
    with open(summary_md_path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n")
        f.write(f"来源文件: `{os.path.basename(audio_path)}`\n\n")
        f.write(summary_text.rstrip() + "\n")

    if on_status:
        on_status(f"已保存到: {folder}")
    logger.info("file job done: %s -> %s", audio_path, folder)
    return {
        "folder": folder,
        "transcript": transcript_path,
        "summary": summary_md_path,
        "summary_txt": summary_txt_path,
        "lines": lines,
        "summary_text": summary_text,
        "title": title,
    }
