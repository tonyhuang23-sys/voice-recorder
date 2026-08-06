"""MeetingAssist 启动入口。

用法:
    python app.py

双击运行或命令行均可。首次运行 Qwen3-ASR 识别会加载模型(约5-10秒)。
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


def main():
    from ui.main import MeetingApp

    app = MeetingApp()
    app.mainloop()


if __name__ == "__main__":
    main()
