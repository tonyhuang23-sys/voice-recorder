"""Speech input: record from mic, transcribe (CN/EN), copy to clipboard."""
import sys
import os
import time
import threading
import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

import sounddevice as sd
import pyperclip
from core.asr import ASRManager
from core.config import load_config


def record_audio(duration=10, sample_rate=16000, silence_threshold=0.02,
                 silence_duration=2.0):
    """Record from microphone. Returns float32 samples."""
    print(f"Recording {duration}s at {sample_rate}Hz...")
    chunks = []
    chunk_samples = int(0.5 * sample_rate)
    silence_chunks = 0
    max_chunks = int(duration / 0.5)

    def callback(indata, frames, time_info, status):
        if status:
            print(status, file=sys.stderr)
        chunks.append(indata.copy())
        rms = np.sqrt(np.mean(indata ** 2))
        if rms < silence_threshold:
            nonlocal silence_chunks
            silence_chunks += 1
        else:
            silence_chunks = 0

    with sd.InputStream(samplerate=sample_rate, channels=1,
                        dtype="float32", blocksize=chunk_samples,
                        callback=callback):
        for _ in range(max_chunks):
            time.sleep(0.5)
            if silence_chunks >= int(silence_duration / 0.5):
                print("Silence detected, stopping.")
                break

    if not chunks:
        return None
    return np.concatenate(chunks, axis=0).flatten()


def transcribe(samples, asr, lang="cn"):
    """Transcribe with Qwen3 (cn) or Whisper (en)."""
    if samples is None or len(samples) < 16000:
        return ""
    if lang == "cn":
        try:
            return asr.transcribe_qwen3(samples, 16000)
        except Exception as e:
            print(f"Qwen3 failed: {e}, falling back to Whisper")
            return asr.transcribe_whisper(samples, 16000, language="zh")
    else:
        return asr.transcribe_whisper(samples, 16000, language="en")


def copy_to_clipboard(text):
    pyperclip.copy(text)
    print(f"Copied {len(text)} chars to clipboard")


def speech_input(lang="cn", duration=10):
    """Record, transcribe, copy to clipboard."""
    cfg = load_config()
    asr = ASRManager(cfg)
    samples = record_audio(duration=duration)
    text = transcribe(samples, asr, lang=lang)
    if text.strip():
        print(f"Transcribed: {text}")
        copy_to_clipboard(text)
    else:
        print("No speech detected")
    return text


def hotkey_listener(lang="cn", duration=10):
    """Listen for Ctrl+Alt+R hotkey, then record and transcribe."""
    import keyboard

    print(f"Speech Input ready. Press Ctrl+Alt+R to record ({lang}, {duration}s). Ctrl+Alt+Q to quit.")

    def on_hotkey():
        try:
            speech_input(lang=lang, duration=duration)
        except Exception as e:
            print(f"Error: {e}")

    keyboard.add_hotkey("ctrl+alt+r", on_hotkey)
    keyboard.wait("ctrl+alt+q")
    print("Speech Input stopped.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Speech Input - Record and transcribe")
    parser.add_argument("--lang", choices=["cn", "en"], default="cn", help="Language (cn=Qwen3, en=Whisper)")
    parser.add_argument("--duration", type=int, default=10, help="Max recording seconds")
    parser.add_argument("--hotkey", action="store_true", help="Run in hotkey mode")
    args = parser.parse_args()

    if args.hotkey:
        hotkey_listener(lang=args.lang, duration=args.duration)
    else:
        speech_input(lang=args.lang, duration=args.duration)
