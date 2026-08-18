"""Audio sources: microphone, system-loopback (WASAPI/Stereo Mix), files, and meeting links."""
import logging
import os
import queue
import shutil
import subprocess
import threading
import wave

import numpy as np

logger = logging.getLogger(__name__)

MEDIA_EXTS = {
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wma",
    ".mp4", ".mkv", ".webm", ".mov", ".avi",
}


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

        if self.stream is not None:
            return self
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
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None


class LoopbackCapture(MicrophoneCapture):
    """System audio loopback via Stereo Mix or WASAPI virtual cable."""

    def start(self):
        if self.stream is not None:
            return self
        return super().start()


class FileSource:
    """Plays back a fully-loaded audio file as chunks for the pipeline."""

    def __init__(self, wav_path, sr=16000):
        self.wav_path = wav_path
        self.sample_rate = sr
        self._pos = 0
        self._done = False
        self._q = []
        with wave.open(wav_path, "rb") as w:
            self.sample_rate = w.getframerate() or sr
            nch = w.getnchannels() or 1
            raw = w.readframes(w.getnframes())
            width = w.getsampwidth()
        if width == 2:
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
        elif width == 4:
            samples = np.frombuffer(raw, dtype=np.float32).copy()
        else:
            raise RuntimeError(f"unsupported wav sample width: {width}")
        if nch > 1:
            samples = samples.reshape(-1, nch)[:, 0]
        self._samples = samples
        self._fill()

    def _fill(self):
        chunk = int(self.sample_rate * 0.5) or 8000
        i = 0
        while i < len(self._samples):
            self._q.append(self._samples[i:i + chunk].copy())
            i += chunk

    def start(self):
        return self

    def read(self, timeout=0.5):
        if self._q:
            return self._q.pop(0)
        self._done = True
        return None

    def stop(self):
        # Do not wipe unread chunks — pipeline.stop() may race the worker.
        self._done = True

    @property
    def exhausted(self):
        return self._done and not self._q


class WavWriter:
    """Append float32 mono samples to a 16-bit PCM wav file."""

    def __init__(self, path, sample_rate=16000):
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        self.path = path
        self._wf = wave.open(path, "wb")
        self._wf.setnchannels(1)
        self._wf.setsampwidth(2)
        self._wf.setframerate(int(sample_rate))
        self._closed = False

    def write(self, samples):
        if self._closed or samples is None:
            return
        pcm = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
        self._wf.writeframes((pcm * 32767.0).astype(np.int16).tobytes())

    def close(self):
        if not self._closed:
            try:
                self._wf.close()
            finally:
                self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class TeeSource:
    """Wrap a capture source and persist every chunk to a wav file."""

    def __init__(self, source, wav_path, sample_rate=16000):
        self.source = source
        self.wav_path = wav_path
        self.sample_rate = int(sample_rate)
        self.writer = WavWriter(wav_path, self.sample_rate)

    def start(self):
        if hasattr(self.source, "start"):
            self.source.start()
        return self

    def read(self, timeout=0.5):
        chunk = self.source.read(timeout=timeout)
        if chunk is not None:
            try:
                self.writer.write(chunk)
            except Exception as e:
                logger.warning("audio persist failed: %s", e)
        return chunk

    def stop(self):
        try:
            if hasattr(self.source, "stop"):
                self.source.stop()
        finally:
            self.writer.close()

    @property
    def exhausted(self):
        return bool(getattr(self.source, "exhausted", False))


def ffmpeg_bin():
    return os.environ.get("FFMPEG_BIN", "ffmpeg")


def ffmpeg_available():
    try:
        proc = subprocess.run(
            [ffmpeg_bin(), "-version"],
            capture_output=True,
            timeout=10,
        )
        return proc.returncode == 0
    except Exception:
        return False


def is_16k_mono_wav(path):
    if not path or os.path.splitext(path)[1].lower() != ".wav":
        return False
    try:
        with wave.open(path, "rb") as w:
            return (
                w.getnchannels() == 1
                and int(w.getframerate()) == 16000
                and w.getsampwidth() == 2
            )
    except Exception:
        return False


def convert_to_16k_mono(src, dst):
    """Extract/convert any audio or video file to 16 kHz mono PCM wav via ffmpeg."""
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    if not os.path.isfile(src):
        raise RuntimeError(f"audio/video file not found: {src}")
    proc = subprocess.run(
        [
            ffmpeg_bin(), "-y", "-i", src,
            "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", dst,
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not os.path.isfile(dst) or os.path.getsize(dst) == 0:
        err = (proc.stderr or proc.stdout or "")[-2000:]
        raise RuntimeError(f"ffmpeg failed to extract 16k mono wav: {err}")
    return dst


def ensure_16k_mono_wav(src, dst):
    """Copy if already 16k mono wav; otherwise convert with ffmpeg.

    If ffmpeg is missing and the source is already a compatible wav, copy it.
    """
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)
    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    if is_16k_mono_wav(src):
        if src != dst:
            shutil.copy2(src, dst)
        return dst
    if not ffmpeg_available():
        raise RuntimeError(
            "ffmpeg not found. Install ffmpeg to extract audio from video/other formats, "
            "or pass a 16 kHz mono WAV."
        )
    return convert_to_16k_mono(src, dst)


def _convert_to_16k_mono(src, dst):
    return convert_to_16k_mono(src, dst)


def download_audio_from_link(url, out_path):
    """Download audio from a meeting/stream link using yt-dlp.

    Returns the local 16 kHz mono wav path, or raises on failure.
    """
    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    stem = os.path.splitext(out_path)[0]
    cmd = [
        "yt-dlp",
        "-x",                       # extract audio
        "--audio-format", "wav",
        "--audio-quality", "0",
        "--no-playlist",
        "-o", stem + ".%(ext)s",
        url,
    ]
    logger.info("Downloading link: %s", url)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {(proc.stderr or '')[-2000:]}")
    produced = None
    parent = os.path.dirname(stem)
    base_name = os.path.basename(stem)
    for f in os.listdir(parent):
        if not f.startswith(base_name):
            continue
        full = os.path.join(parent, f)
        if full.endswith((".wav", ".m4a", ".mp3", ".webm", ".opus")):
            produced = full
            break
    if not produced:
        raise RuntimeError("yt-dlp finished but no audio file found")
    ensure_16k_mono_wav(produced, out_path)
    if os.path.abspath(produced) != out_path:
        try:
            os.remove(produced)
        except OSError:
            pass
    return out_path
