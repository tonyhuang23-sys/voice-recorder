"""Speech Input - 语音识别输入法 (中文/英文)"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.speech_input import speech_input, hotkey_listener

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Speech Input - 语音识别输入法")
    parser.add_argument("--lang", choices=["cn", "en"], default="cn",
                        help="语言: cn=Qwen3中文, en=Whisper英文")
    parser.add_argument("--duration", type=int, default=10,
                        help="最大录音秒数 (默认10秒)")
    parser.add_argument("--hotkey", action="store_true",
                        help="热键模式: Ctrl+Alt+R 录音, Ctrl+Alt+Q 退出")
    args = parser.parse_args()

    if args.hotkey:
        hotkey_listener(lang=args.lang, duration=args.duration)
    else:
        speech_input(lang=args.lang, duration=args.duration)
