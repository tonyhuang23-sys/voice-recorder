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


def find_ffmpeg():
    """Locate ffmpeg: env, PATH, then common Windows install locations."""
    env = os.environ.get("FFMPEG_BIN")
    if env and os.path.isfile(env):
        return env
    import shutil

    which = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if which:
        return which
    from .config import APP_DIR

    candidates = [
        os.path.join(APP_DIR, "ffmpeg.exe"),
        os.path.join(APP_DIR, "ffmpeg"),
        r"C:\Engineering Soft\VoiceRecorder-2.0\ffmpeg.exe",
        r"C:\Users\ht_34\AppData\Local\Programs\Python\Python311\ffmpeg.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return "ffmpeg"


def _convert_to_16k_mono(src, dst):
    ffmpeg = find_ffmpeg()
    proc = subprocess.run(
        [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
         "-i", src, "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", dst],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not os.path.isfile(dst):
        err = (proc.stderr or proc.stdout or "").strip()[-800:]
        raise RuntimeError(f"ffmpeg 转码失败 ({ffmpeg}): {err or 'no output'}")


def load_wav_samples(wav_path):
    """Load a PCM WAV as float32 mono samples. Returns (samples, sample_rate)."""
    import wave

    with wave.open(wav_path, "rb") as w:
        sr = w.getframerate()
        nch = w.getnchannels()
        sw = w.getsampwidth()
        n = w.getnframes()
        raw = w.readframes(n)
    if sw == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        data = np.frombuffer(raw, dtype=np.float32)
    else:
        raise RuntimeError(f"不支持的 WAV 采样宽度: {sw} bytes")
    if nch > 1:
        data = data.reshape(-1, nch).mean(axis=1)
    return data, sr


def load_audio_file(path, sample_rate=16000):
    """Load m4a/mp3/wav/flac/ogg as 16 kHz mono float32 samples."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"音频文件不存在: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext == ".wav":
        try:
            samples, sr = load_wav_samples(path)
            if sr == sample_rate:
                return samples, sr
        except Exception:
            pass
    import tempfile

    fd, tmp = tempfile.mkstemp(suffix="_16k.wav")
    os.close(fd)
    try:
        _convert_to_16k_mono(path, tmp)
        samples, sr = load_wav_samples(tmp)
        return samples, sr
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


class FileSource:
    """Feeds a local audio file to the meeting pipeline as 0.5s chunks.

    Supports wav / m4a / mp3 / flac / ogg via ffmpeg. Sets ``eof`` when
    the file has been fully consumed so the pipeline can flush and stop.
    """

    def __init__(self, path, sample_rate=16000, chunk_sec=0.5, samples=None):
        self.path = path
        self.eof = False
        if samples is not None:
            self._samples = np.asarray(samples, dtype=np.float32)
            self.sample_rate = int(sample_rate)
        else:
            self._samples, self.sample_rate = load_audio_file(path, sample_rate)
        chunk = max(1, int(self.sample_rate * chunk_sec))
        self._q = []
        i = 0
        while i < len(self._samples):
            self._q.append(self._samples[i:i + chunk].copy())
            i += chunk
        if not self._q:
            self.eof = True

    def read(self, timeout=0.5):
        if self._q:
            return self._q.pop(0)
        self.eof = True
        return None

    def stop(self):
        self._q = []
        self.eof = True
