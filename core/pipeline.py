"""Real-time meeting pipeline: capture -> segment -> ASR -> translate -> log."""
import logging
import time
import threading

import numpy as np

from .asr import ASRManager
from .translator import Translator

logger = logging.getLogger(__name__)


class MeetingPipeline:
    """Consumes audio chunks from a capture source, runs ASR + translation,
    and maintains a transcript list. Runs ASR in a worker thread."""

    def __init__(self, cfg, asr=None, translator=None, source=None, callback=None):
        self.cfg = cfg
        self.asr = asr or ASRManager(cfg)
        self.translator = translator or Translator(cfg)
        self.source = source  # capture object with .read(timeout) / .stop()
        self.callback = callback  # fn(kind, payload)

        self.transcript = []       # list of (ts_str, speaker, text)
        self.running = False
        self.thread = None

        self._buffer = np.zeros(0, dtype=np.float32)
        self._sr = int(cfg["audio"]["sample_rate"])
        self._silence_threshold = float(cfg["audio"]["silence_threshold"])
        self._silence_dur = float(cfg["audio"]["silence_dur_to_stop"])
        self._max_seg = float(cfg["audio"]["max_segment_sec"])
        self._min_seg = 0.5  # min speech before decoding
        self._silence_samples = 0
        self._speech_samples = 0
        self._lock = threading.Lock()

    # ---- public API ----
    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.source:
            try:
                self.source.stop()
            except Exception:
                pass
        if self.thread:
            self.thread.join(timeout=5)

    def add_line(self, ts, speaker, text):
        with self._lock:
            self.transcript.append((ts, speaker, text))
        if self.callback:
            try:
                self.callback("line", {"ts": ts, "speaker": speaker, "text": text})
            except Exception as e:
                logger.warning("callback error: %s", e)

    def get_transcript(self):
        with self._lock:
            return list(self.transcript)

    # ---- processing loop ----
    def _run(self):
        while self.running:
            chunk = self.source.read(timeout=0.5) if self.source else None
            if chunk is None:
                continue
            self._process_chunk(chunk)
        # flush remaining
        if len(self._buffer) > self._sr * self._min_seg:
            self._decode_segment(self._buffer)
            self._buffer = np.zeros(0, dtype=np.float32)

    def _process_chunk(self, chunk):
        chunk = np.asarray(chunk, dtype=np.float32)
        self._buffer = np.concatenate([self._buffer, chunk]) if self._buffer.size else chunk

        rms = float(np.sqrt(np.mean(chunk ** 2))) if chunk.size else 0.0
        if rms < self._silence_threshold:
            self._silence_samples += chunk.size
            if self._speech_samples > 0 and \
               self._silence_samples > self._sr * self._silence_dur:
                # end of an utterance
                if len(self._buffer) > self._sr * self._min_seg:
                    self._decode_segment(self._buffer)
                self._buffer = np.zeros(0, dtype=np.float32)
                self._silence_samples = 0
                self._speech_samples = 0
        else:
            self._silence_samples = 0
            self._speech_samples += chunk.size
            if len(self._buffer) > self._sr * self._max_seg:
                self._decode_segment(self._buffer)
                self._buffer = np.zeros(0, dtype=np.float32)
                self._silence_samples = 0
                self._speech_samples = 0

    def _decode_segment(self, samples):
        try:
            if self.callback:
                self.callback("status", "识别中...")
            text, engine = self.asr.transcribe(samples, self._sr)
            text = text.strip()
            if text:
                ts = time.strftime("%H:%M:%S", time.localtime())
                self.add_line(ts, "?", text)
                # translation
                target = self.cfg["translate"].get("target_lang", "zh")
                src = "zh" if _cn(text) else "en"
                if src != target and self.cfg["translate"].get("auto", True):
                    try:
                        trans = self.translator.translate(text, src, target)
                        if trans:
                            self.callback("trans", {"src": text, "dst": trans,
                                                    "engine": engine})
                    except Exception as e:
                        logger.warning("translate error: %s", e)
            if self.callback:
                self.callback("status", "")
        except Exception as e:
            logger.exception("decode error")
            if self.callback:
                self.callback("status", f"错误: {e}")


def _cn(text):
    n = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return n / max(1, len(text)) > 0.1
