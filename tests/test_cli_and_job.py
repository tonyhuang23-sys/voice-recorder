import io
import math
import os
import struct
import tempfile
import unittest
import wave
from unittest import mock

import cli
from core.job import run_meeting_job
from core.pipeline import MeetingPipeline
from core.watch import discover_ready, is_media_file, mark_seen


def _write_tone_wav(path, seconds=2.0, sr=16000):
    n = int(sr * seconds)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            v = int(0.25 * 32767 * math.sin(2 * math.pi * 440 * i / sr))
            frames += struct.pack("<h", v)
        w.writeframes(frames)


class FakeASR:
    def transcribe(self, samples, sample_rate):
        return "hello meeting", "fake"


class FakeTranslator:
    def translate(self, text, src="en", dst="zh", mode=None):
        return "你好会议"


class FakeSummarizer:
    def summarize(self, lines, title="会议记录", engine=None):
        return f"摘要:{title}"


class _StartProbe:
    def __init__(self):
        self.started = False
        self.stopped = False
        self._n = 0

    def start(self):
        self.started = True
        return self

    def read(self, timeout=0.5):
        self._n += 1
        if self._n > 2:
            return None
        import numpy as np
        return np.zeros(8000, dtype=np.float32)

    def stop(self):
        self.stopped = True

    @property
    def exhausted(self):
        return self._n > 2


class CliJobTests(unittest.TestCase):
    def test_cli_help(self):
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            with self.assertRaises(SystemExit) as ctx:
                cli.build_parser().parse_args(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        out = buf.getvalue()
        self.assertIn("--file", out)
        self.assertIn("--watch", out)
        self.assertIn("--push-lark", out)
        self.assertIn("--email", out)

    def test_cli_requires_source(self):
        with self.assertRaises(SystemExit):
            cli.build_parser().parse_args([])

    def test_cli_does_not_import_tk(self):
        self.assertNotIn("tkinter", cli.__dict__)
        with open(cli.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("tkinter", src)
        self.assertNotIn("from ui", src)

    def test_pipeline_calls_source_start(self):
        cfg = {
            "audio": {
                "sample_rate": 16000,
                "silence_threshold": 0.02,
                "silence_dur_to_stop": 1.5,
                "max_segment_sec": 30,
            },
            "translate": {"target_lang": "zh", "auto": False},
        }
        src = _StartProbe()
        pipe = MeetingPipeline(cfg, asr=FakeASR(), translator=FakeTranslator(), source=src)
        pipe.start()
        self.assertTrue(src.started)
        pipe.stop()

    def test_job_persists_audio_and_outputs(self):
        from core.config import DEFAULT_CONFIG
        import json

        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        env_clear = {
            "LARK_WEBHOOK_URL": "",
            "GMAIL_USER": "",
            "GMAIL_APP_PASSWORD": "",
            "SMTP_PASSWORD": "",
            "MEETING_SMTP_PASSWORD": "",
        }
        with tempfile.TemporaryDirectory() as td:
            wav = os.path.join(td, "in.wav")
            _write_tone_wav(wav)
            with mock.patch("core.job.output.OUTPUT_DIR", td), \
                 mock.patch("core.output.OUTPUT_DIR", td), \
                 mock.patch.dict(os.environ, env_clear, clear=False):
                result = run_meeting_job(
                    cfg,
                    title="单元测试",
                    target_lang="zh",
                    file_path=wav,
                    push_lark=True,
                    asr=FakeASR(),
                    translator=FakeTranslator(),
                    summarizer=FakeSummarizer(),
                    log=lambda m: None,
                )
            self.assertTrue(result.ok)
            self.assertTrue(os.path.isfile(os.path.join(result.folder, "audio.wav")))
            self.assertTrue(os.path.isfile(os.path.join(result.folder, "转写记录.txt")))
            self.assertTrue(os.path.isfile(os.path.join(result.folder, "翻译.txt")))
            self.assertTrue(os.path.isfile(os.path.join(result.folder, "会议摘要.txt")))
            with open(os.path.join(result.folder, "翻译.txt"), encoding="utf-8") as f:
                trans = f.read()
            self.assertTrue(trans.strip())
            self.assertNotEqual(trans.strip(), "")
            self.assertIn("摘要:", result.summary)
            self.assertFalse(result.lark_pushed)
            self.assertFalse(result.email_sent)

    def test_watch_ready_files(self):
        with tempfile.TemporaryDirectory() as td:
            good = os.path.join(td, "zoom_audio.m4a")
            skip = os.path.join(td, "clip.part")
            with open(good, "wb") as f:
                f.write(b"xx")
            with open(skip, "wb") as f:
                f.write(b"yy")
            os.utime(good, (0, 0))
            self.assertTrue(is_media_file(good))
            self.assertFalse(is_media_file(skip))
            seen = {}
            ready = discover_ready(td, seen, settle_sec=0)
            self.assertEqual([p for p, _ in ready], [os.path.abspath(good)])
            mark_seen(seen, good, ready[0][1])
            self.assertEqual(discover_ready(td, seen, settle_sec=0), [])


if __name__ == "__main__":
    unittest.main()
