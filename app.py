"""MeetingAssist 启动入口。

用法:
    python app.py
    python app.py --file "录音.m4a"
    python app.py --file "录音.m4a" --out-dir "输出目录" --title "会议标题"

双击运行或命令行均可。带 --file 时不打开窗口,直接转写并在音频同目录写入摘要。
首次运行 Qwen3-ASR 识别会加载模型(约5-10秒)。
"""
import logging
import os
import sys

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _run_file(args):
    from core.config import load_config
    from core.file_job import process_audio_file

    cfg = load_config()

    def status(msg):
        print(msg, flush=True)

    def on_line(payload):
        print(f"[{payload['ts']}] {payload['text']}", flush=True)

    result = process_audio_file(
        args.file,
        cfg,
        out_dir=args.out_dir,
        title=args.title,
        on_line=on_line,
        on_status=status,
    )
    print("转写:", result["transcript"], flush=True)
    print("摘要:", result["summary"], flush=True)
    return 0


def main():
    import argparse

    parser = argparse.ArgumentParser(description="会议助手 MeetingAssist")
    parser.add_argument("--file", "-f", help="本地音频文件 (wav/m4a/mp3/flac)")
    parser.add_argument("--out-dir", help="输出目录,默认与音频同文件夹")
    parser.add_argument("--title", help="会议标题,默认用文件名")
    args = parser.parse_args()
    if args.file:
        return _run_file(args)

    from ui.main import MeetingApp

    app = MeetingApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
