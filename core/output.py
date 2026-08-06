"""Output utilities: save transcript / summary / minutes to files."""
import os
import datetime

from .config import OUTPUT_DIR


def meeting_folder(title="会议记录"):
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if c not in '\\/:*?"<>|' else "_" for c in title)
    folder = os.path.join(OUTPUT_DIR, f"{ts}_{safe}")
    os.makedirs(folder, exist_ok=True)
    return folder


def save_transcript(folder, transcript, translated_pairs=None, language="zh"):
    path = os.path.join(folder, "转写记录.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("时间\t发言人\t内容\n")
        for ts, speaker, text in transcript:
            f.write(f"{ts}\t{speaker}\t{text}\n")
    return path


def save_translation(folder, pairs):
    path = os.path.join(folder, "翻译.txt")
    with open(path, "w", encoding="utf-8") as f:
        for item in pairs:
            f.write(f"原文: {item['src']}\n")
            f.write(f"译文: {item['dst']}\n")
            f.write("-" * 40 + "\n")
    return path


def save_summary(folder, summary_text):
    path = os.path.join(folder, "会议摘要.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(summary_text)
    return path
