"""Output utilities: save the four meeting artifacts (wav + three .txt files)."""
import os
import datetime
import wave

from .config import OUTPUT_DIR

ARTIFACT_WAV = "audio.wav"
ARTIFACT_MP3 = "audio.mp3"
ARTIFACT_TRANSCRIPT = "转写记录.txt"
ARTIFACT_TRANSLATION = "翻译.txt"
ARTIFACT_SUMMARY = "会议摘要.txt"

EMPTY_TRANSCRIPT = "（无转写内容）\n"
EMPTY_TRANSLATION = "（无翻译内容）\n"
EMPTY_SUMMARY = "（无摘要）"


def meeting_folder(title="会议记录"):
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if c not in '\\/:*?"<>|' else "_" for c in title)
    folder = os.path.join(OUTPUT_DIR, f"{ts}_{safe}")
    os.makedirs(folder, exist_ok=True)
    return folder


def audio_path(folder, name=ARTIFACT_WAV):
    return os.path.join(folder, name)


def write_silent_wav(path, sample_rate=16000):
    """Write a valid empty 16 kHz mono wav so the audio artifact always exists."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sample_rate))
        w.writeframes(b"")
    return path


def ensure_wav_artifact(folder, wav_path=None, sample_rate=16000):
    dest = audio_path(folder)
    if wav_path and os.path.isfile(wav_path) and os.path.getsize(wav_path) >= 0:
        if os.path.abspath(wav_path) != os.path.abspath(dest):
            import shutil
            shutil.copy2(wav_path, dest)
        return dest
    if os.path.isfile(dest):
        return dest
    return write_silent_wav(dest, sample_rate=sample_rate)


def save_transcript(folder, transcript, translated_pairs=None, language="zh"):
    path = os.path.join(folder, ARTIFACT_TRANSCRIPT)
    with open(path, "w", encoding="utf-8") as f:
        f.write("时间\t发言人\t内容\n")
        rows = list(transcript or [])
        if not rows:
            f.write(EMPTY_TRANSCRIPT)
        else:
            for ts, speaker, text in rows:
                f.write(f"{ts}\t{speaker}\t{text}\n")
    return path


def save_translation(folder, pairs):
    path = os.path.join(folder, ARTIFACT_TRANSLATION)
    with open(path, "w", encoding="utf-8") as f:
        items = list(pairs or [])
        if not items:
            f.write(EMPTY_TRANSLATION)
        else:
            for item in items:
                f.write(f"原文: {item.get('src', '')}\n")
                f.write(f"译文: {item.get('dst', '')}\n")
                f.write("-" * 40 + "\n")
    return path


def save_summary(folder, summary_text):
    path = os.path.join(folder, ARTIFACT_SUMMARY)
    text = summary_text if (summary_text and str(summary_text).strip()) else EMPTY_SUMMARY
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def save_four_artifacts(folder, transcript, pairs, summary_text, wav_path=None,
                        sample_rate=16000):
    """Always write wav + 转写.txt + 翻译.txt + 中文摘要.txt."""
    files = {
        "audio": ensure_wav_artifact(folder, wav_path=wav_path, sample_rate=sample_rate),
        "transcript": save_transcript(folder, transcript),
        "translation": save_translation(folder, pairs),
        "summary": save_summary(folder, summary_text),
    }
    return files


def list_text_files(folder):
    if not folder or not os.path.isdir(folder):
        return []
    wanted = {ARTIFACT_TRANSCRIPT, ARTIFACT_TRANSLATION, ARTIFACT_SUMMARY}
    out = []
    for name in (ARTIFACT_TRANSCRIPT, ARTIFACT_TRANSLATION, ARTIFACT_SUMMARY):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            out.append(path)
    extra = [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.endswith(".txt") and f not in wanted and f != "watch_seen.json"
    ]
    return out + sorted(extra)


def looks_like_chinese(text, ratio=0.1):
    if not text:
        return False
    cnt = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return cnt / max(1, len(text)) > ratio
