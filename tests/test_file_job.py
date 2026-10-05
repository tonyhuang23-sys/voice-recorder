"""Tests for local-file transcription job (mocked ASR, no models required)."""
import os
import tempfile
import unittest
import wave

import numpy as np

from core.audio_source import FileSource, load_wav_samples
from core.config import DEFAULT_CONFIG
from core.file_job import process_audio_file
from core.pipeline import MeetingPipeline


def _write_sine_wav(path, seconds=3.0, sr=16000, amp=0.3, freq=220.0):
    n = int(seconds * sr)
    t = np.arange(n, dtype=np.float32) / sr
    samples = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


class FakeASR:
    def transcribe(self, samples, sample_rate, priority=None):
        rms = float(np.sqrt(np.mean(np.square(samples)))) if len(samples) else 0
        if rms < 0.01:
            return "", "fake"
        return "涛涛车业合作讨论航改燃项目进度与下一步安排", "fake"


class FakeTranslator:
    def translate(self, *args, **kwargs):
        return ""


def _cfg():
    import json
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["audio"]["silence_threshold"] = 0.05
    cfg["audio"]["silence_dur_to_stop"] = 0.4
    cfg["audio"]["max_segment_sec"] = 2.0
    cfg["translate"]["auto"] = False
    return cfg


class FileSourceTests(unittest.TestCase):
    def test_eof_after_chunks(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_sine_wav(os.path.join(d, "a.wav"), seconds=1.2)
            src = FileSource(path, sample_rate=16000, chunk_sec=0.5)
            n = 0
            while True:
                c = src.read()
                if c is None:
                    break
                n += 1
            self.assertGreaterEqual(n, 2)
            self.assertTrue(src.eof)

    def test_load_wav_samples(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_sine_wav(os.path.join(d, "b.wav"), seconds=0.5)
            samples, sr = load_wav_samples(path)
            self.assertEqual(sr, 16000)
            self.assertGreater(len(samples), 1000)


class PipelineEofTests(unittest.TestCase):
    def test_pipeline_stops_at_file_end(self):
        cfg = _cfg()
        samples = 0.3 * np.sin(2 * np.pi * 220 * np.arange(16000 * 3) / 16000)
        src = FileSource(path="memory.wav", samples=samples.astype(np.float32),
                         sample_rate=16000)
        pipe = MeetingPipeline(cfg, asr=FakeASR(), translator=FakeTranslator(),
                               source=src)
        pipe.start()
        pipe.thread.join(timeout=15)
        self.assertFalse(pipe.running)
        lines = pipe.get_transcript()
        self.assertGreaterEqual(len(lines), 1)
        self.assertIn("涛涛车业", lines[0][2])


class FileJobTests(unittest.TestCase):
    def test_writes_transcript_and_summary_beside_audio(self):
        with tempfile.TemporaryDirectory() as d:
            audio = _write_sine_wav(
                os.path.join(d, "2026年10月05日 12点31分.wav"), seconds=3.0)
            result = process_audio_file(
                audio, _cfg(), asr=FakeASR(), translator=FakeTranslator())
            self.assertTrue(os.path.isfile(result["transcript"]))
            self.assertTrue(os.path.isfile(result["summary"]))
            self.assertEqual(os.path.dirname(result["summary"]), d)
            with open(result["summary"], encoding="utf-8") as f:
                md = f.read()
            self.assertIn("涛涛车业", md)
            self.assertIn("2026年10月05日 12点31分", os.path.basename(result["transcript"]))

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            process_audio_file(
                "/tmp/definitely-missing-audio-xyz.m4a",
                _cfg(), asr=FakeASR(), translator=FakeTranslator())


if __name__ == "__main__":
    unittest.main()
