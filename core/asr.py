"""Dual-engine ASR: Qwen3-ASR (Chinese-first) + faster-whisper (English-first)."""
import logging
import numpy as np

logger = logging.getLogger(__name__)


class ASRManager:
    """Manages two offline ASR engines and picks per audio language priority."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.qwen3 = None
        self.whisper = None
        self._qwen3_sr = 16000
        self._whisper_sr = 16000

    # ---- Qwen3-ASR ----
    def _load_qwen3(self):
        if self.qwen3 is not None:
            return self.qwen3
        import sherpa_onnx

        q = self.cfg["asr"]["qwen3"]
        logger.info("Loading Qwen3-ASR (this takes a few seconds)...")
        self.qwen3 = sherpa_onnx.OfflineRecognizer.from_qwen3_asr(
            conv_frontend=q["conv_frontend"],
            encoder=q["encoder"],
            decoder=q["decoder"],
            tokenizer=q["tokenizer"],
            max_new_tokens=int(q.get("max_new_tokens", 128)),
            num_threads=int(q.get("num_threads", 4)),
        )
        logger.info("Qwen3-ASR loaded.")
        return self.qwen3

    def transcribe_qwen3(self, samples, sample_rate=16000):
        rec = self._load_qwen3()
        s = rec.create_stream()
        s.accept_waveform(int(sample_rate), np.asarray(samples, dtype=np.float32))
        rec.decode_stream(s)
        return s.result.text.strip()

    # ---- Whisper ----
    def _load_whisper(self):
        if self.whisper is not None:
            return self.whisper
        from faster_whisper import WhisperModel

        w = self.cfg["asr"]["whisper"]
        logger.info("Loading faster-whisper '%s'...", w.get("model", "small"))
        self.whisper = WhisperModel(
            w.get("model", "small"),
            device=w.get("device", "cpu"),
            compute_type=w.get("compute_type", "int8"),
            download_root=w.get("model_dir"),
        )
        logger.info("Whisper loaded.")
        return self.whisper

    def transcribe_whisper(self, samples, sample_rate=16000, language=None):
        model = self._load_whisper()
        w = self.cfg["asr"]["whisper"]
        lang = language or w.get("language") or "en"
        segments, _info = model.transcribe(
            np.asarray(samples, dtype=np.float32),
            language=lang,
            beam_size=5,
            vad_filter=False,
        )
        parts = [seg.text.strip() for seg in segments]
        return " ".join(p for p in parts if p).strip()

    # ---- Public ----
    def transcribe(self, samples, sample_rate, priority=None):
        """Transcribe with auto language routing.

        priority: 'cn' (Qwen3 first) or 'en' (Whisper first) or None (config default).
        For simplicity: route by explicit priority; auto-detection can be added.
        """
        priority = priority or self.cfg["asr"].get("lang_priority", "cn")
        if priority == "cn":
            try:
                return self.transcribe_qwen3(samples, sample_rate), "qwen3"
            except Exception as e:
                logger.warning("Qwen3-ASR failed (%s), falling back to Whisper.", e)
                return self.transcribe_whisper(samples, sample_rate), "whisper"
        else:
            try:
                return self.transcribe_whisper(samples, sample_rate), "whisper"
            except Exception as e:
                logger.warning("Whisper failed (%s), falling back to Qwen3-ASR.", e)
                return self.transcribe_qwen3(samples, sample_rate), "qwen3"

    def unload(self):
        self.qwen3 = None
        self.whisper = None
