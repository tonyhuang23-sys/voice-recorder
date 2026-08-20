"""Headless MeetingAssist CLI (no Tk).

Usage:
    python cli.py --file meeting.mp4 --title "周会" --target-lang zh --push-lark --email
    python cli.py --url https://www.youtube.com/watch?v=... --title "talk"
    python cli.py --mic --title "live"
    python cli.py --loopback --title "zoom"
    python cli.py --watch DIR --push-lark
"""
import argparse
import io
import logging
import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")


def _configure_stdio():
    """Make stdout/stderr utf-8 so argparse help does not crash on Windows cp1252."""
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
            continue
        except (AttributeError, OSError, ValueError):
            pass
        buf = getattr(stream, "buffer", None)
        if buf is None:
            continue
        try:
            setattr(sys, name, io.TextIOWrapper(buf, encoding="utf-8", errors="replace"))
        except Exception:
            pass


_configure_stdio()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cli")


def build_parser():
    p = argparse.ArgumentParser(
        prog="cli.py",
        description=(
            "MeetingAssist headless pipeline: ASR -> translate -> Chinese summary "
            "-> four artifacts -> Lark/email"
        ),
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", metavar="PATH",
                     help="local audio or video; extract 16 kHz mono wav via ffmpeg")
    src.add_argument("--url", metavar="URL",
                     help="download audio with yt-dlp (same path as the GUI link source)")
    src.add_argument("--loopback", action="store_true",
                     help="capture system audio (Stereo Mix / virtual cable)")
    src.add_argument("--mic", action="store_true",
                     help="capture the default (or --device) microphone")
    src.add_argument("--watch", metavar="DIR",
                     help="watch a folder for Zoom/Teams/Meet/Lark local recordings")
    p.add_argument("--title", default="会议记录",
                   help="meeting title (default: meeting)")
    p.add_argument("--target-lang", default="zh", dest="target_lang",
                   help="translation target language (default: zh)")
    p.add_argument("--push-lark", action="store_true",
                   help="push Chinese summary text/card to Lark (also auto if webhook configured)")
    p.add_argument("--email", action="store_true",
                   help="email .txt artifacts + speech mp3 to MEETING_EMAIL_TO / email.to (also auto if SMTP configured)")
    p.add_argument("--device", type=int, default=None,
                   help="optional sounddevice input index for --mic / --loopback")
    p.add_argument("--watch-settle", type=float, default=8.0, dest="watch_settle",
                   help="seconds a recording must stay unchanged before processing (default: 8)")
    p.add_argument("--poll", type=float, default=3.0,
                   help="--watch poll interval in seconds (default: 3)")
    return p


def main(argv=None):
    _configure_stdio()
    args = build_parser().parse_args(argv)
    from core.config import load_config
    from core.job import run_meeting_job

    cfg = load_config()
    cfg.setdefault("translate", {})["target_lang"] = args.target_lang

    def emit(msg):
        print(msg, flush=True)

    if args.watch:
        return _run_watch(cfg, args, emit)

    live = "mic" if args.mic else ("loopback" if args.loopback else None)
    result = run_meeting_job(
        cfg,
        title=args.title,
        target_lang=args.target_lang,
        file_path=args.file,
        url=args.url,
        live=live,
        device_index=args.device,
        push_lark=args.push_lark,
        send_email=args.email,
        log=emit,
    )
    if not result.ok:
        emit(f"失败: {result.error}")
        return 1
    emit("完成")
    return 0


def _run_watch(cfg, args, emit):
    from core.job import run_meeting_job
    from core.watch import discover_ready, load_seen, mark_seen, save_seen

    root = os.path.abspath(args.watch)
    if not os.path.isdir(root):
        emit(f"监视目录不存在: {root}")
        return 1
    emit(f"监视目录: {root} (Zoom/Teams/Meet/Lark 本地录像; Ctrl+C 结束)")
    seen = load_seen()
    failures = 0
    try:
        while True:
            ready = discover_ready(root, seen, settle_sec=args.watch_settle)
            for path, token in ready:
                stem = os.path.splitext(os.path.basename(path))[0]
                title = args.title if args.title and args.title != "会议记录" else stem
                if args.title and args.title != "会议记录":
                    title = f"{args.title}_{stem}"
                emit(f"发现录像: {path}")
                result = run_meeting_job(
                    cfg,
                    title=title,
                    target_lang=args.target_lang,
                    file_path=path,
                    push_lark=args.push_lark,
                    send_email=args.email,
                    log=emit,
                )
                mark_seen(seen, path, token)
                save_seen(seen)
                if not result.ok:
                    failures += 1
                    emit(f"处理失败: {result.error}")
                else:
                    emit(f"处理完成: {result.folder}")
            import time
            time.sleep(max(0.5, float(args.poll)))
    except KeyboardInterrupt:
        emit("监视已停止")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
