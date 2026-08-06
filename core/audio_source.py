"""Audio sources: microphone, system-loopback (WASAPI/Stereo Mix), and meeting links."""
import logging
import os
import queue
import subprocess
import threading
import time

import numpy as np

logger = logging.getLogger(__name__)


def find_loopback_device():
    """Best-effort find of a system audio capture device (Stereo Mix / WASAPI loopback)."""
    try:
        import sounddevice as sd

        names = sd.query_devices()
        for i, d in enumerate(names):
            n = (d["name"] or "").lower()
            if d["max_input_channels"] > 0 and (
                "stereo mix" in n
                or "loopback" in n
                or "what u hear" in n
                or "sonido" in n
            ):
                return i
    except Exception:
        pass
    return None


def list_input_devices():
    try:
        import sounddevice as sd

        out = []
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                out.append((i, d["name"], d["max_input_channels"], d["default_samplerate"]))
        return out
    except Exception:
        return []


class MicrophoneCapture:
    """Streams microphone audio in float32 chunks via sounddevice."""

    def __init__(self, cfg, device_index=None):
        self.cfg = cfg
        self.sample_rate = int(cfg["audio"]["sample_rate"])
        self.device_index = device_index
        self.q = queue.Queue()
        self.stop_flag = threading.Event()
        self.stream = None

    def _callback(self, indata, frames, time_info, status):
        if self.stop_flag.is_set():
            return
        self.q.put(indata[:, 0].copy())

    def start(self):
        import sounddevice as sd

        self.stop_flag.clear()
        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=self.device_index,
            callback=self._callback,
            blocksize=int(self.sample_rate * 0.5),
        )
        self.stream.start()
        return self

    def read(self, timeout=0.5):
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        self.stop_flag.set()
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None


class LoopbackCapture(MicrophoneCapture):
    """System audio loopback via Stereo Mix or WASAPI virtual cable."""

    def start(self):
        import sounddevice as sd

        self.stop_flag.clear()
        # If explicit loopback device given, use it; else try Stereo Mix.
        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="float32",
            device=self.device_index,
            callback=self._callback,
            blocksize=int(self.sample_rate * 0.5),
        )
        self.stream.start()
        return self


def download_audio_from_link(url, out_path):
    """Download audio from a meeting/stream link using yt-dlp.

    Returns the local audio file path, or raises on failure.
    """
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cmd = [
        "yt-dlp",
        "-x",                       # extract audio
        "--audio-format", "wav",
        "--audio-quality", "0",
        "--no-playlist",
        "-o", os.path.splitext(out_path)[0] + ".%(ext)s",
        url,
    ]
    logger.info("Downloading link: %s", url)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {proc.stderr[-2000:]}")
    # find produced file
    base = os.path.splitext(out_path)[0]
    for f in os.listdir(os.path.dirname(base)):
        if f.startswith(os.path.basename(base)):
            full = os.path.join(os.path.dirname(base), f)
            if full.endswith(".wav") or full.endswith(".m4a") or full.endswith(".mp3"):
                # convert to 16k mono wav for consistency
                conv = base + "_16k.wav"
                _convert_to_16k_mono(full, conv)
                return conv
    raise RuntimeError("yt-dlp finished but no audio file found")


def _convert_to_16k_mono(src, dst):
    ffmpeg = os.environ.get("FFMPEG_BIN", "ffmpeg")
    subprocess.run(
        [ffmpeg, "-y", "-i", src, "-ac", "1", "-ar", "16000", dst],
        capture_output=True,
    )
