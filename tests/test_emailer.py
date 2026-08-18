import os
import tempfile
import unittest
from unittest import mock

from core.emailer import (
    DEFAULT_TO,
    EmailSender,
    collect_meeting_attachments,
    connect_smtp,
    resolve_to_addrs,
    resolved_email_cfg,
    _email_cfg,
)
from core.output import (
    ARTIFACT_MP3,
    ARTIFACT_SUMMARY,
    ARTIFACT_TRANSCRIPT,
    ARTIFACT_TRANSLATION,
    ARTIFACT_WAV,
    save_four_artifacts,
)


class _DummySMTP:
    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.ext = {"starttls": True}
        self.calls = []

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self):
        self.calls.append("starttls")

    def has_extn(self, name):
        return bool(self.ext.get(name))

    def login(self, user, password):
        self.calls.append("login")

    def quit(self):
        self.calls.append("quit")


class EmailerTests(unittest.TestCase):
    def test_ssl_never_calls_starttls(self):
        created = []

        class SSL(_DummySMTP):
            def __init__(self, host, port, timeout=None):
                super().__init__(host, port, timeout)
                created.append(self)

        with mock.patch("core.emailer.smtplib.SMTP_SSL", SSL), \
             mock.patch("core.emailer.smtplib.SMTP") as plain:
            server = connect_smtp(
                {"smtp_host": "smtp.example.com", "smtp_port": 465, "use_ssl": True},
                timeout=5,
            )
        self.assertEqual(len(created), 1)
        self.assertNotIn("starttls", created[0].calls)
        plain.assert_not_called()
        self.assertIs(server, created[0])

    def test_plain_may_starttls(self):
        created = []

        class Plain(_DummySMTP):
            def __init__(self, host, port, timeout=None):
                super().__init__(host, port, timeout)
                created.append(self)

        with mock.patch("core.emailer.smtplib.SMTP", Plain), \
             mock.patch("core.emailer.smtplib.SMTP_SSL") as ssl:
            connect_smtp(
                {"smtp_host": "smtp.example.com", "smtp_port": 587, "use_ssl": False},
            )
        ssl.assert_not_called()
        self.assertIn("starttls", created[0].calls)

    def test_accepts_email_section_or_full_cfg(self):
        section = {"smtp_host": "h", "smtp_user": "u", "smtp_password": "p"}
        self.assertEqual(_email_cfg(section)["smtp_host"], "h")
        self.assertEqual(_email_cfg({"email": section})["smtp_user"], "u")
        sender = EmailSender(section)
        self.assertTrue(sender.is_configured())

    def test_default_recipient(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MEETING_EMAIL_TO", None)
            self.assertEqual(resolve_to_addrs({}), [DEFAULT_TO])
            self.assertEqual(DEFAULT_TO, "gztonyhuang@outlook.com")
            self.assertEqual(
                resolve_to_addrs({"to": "a@example.com"}),
                ["a@example.com"],
            )

    def test_recipient_env_wins(self):
        with mock.patch.dict(os.environ, {"MEETING_EMAIL_TO": "other@example.com"}):
            self.assertEqual(
                resolve_to_addrs({"to": "gztonyhuang@outlook.com"}),
                ["other@example.com"],
            )

    def test_gmail_env_smtp(self):
        env = {
            "GMAIL_USER": "you@gmail.com",
            "GMAIL_APP_PASSWORD": "not-a-real-password",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            for key in ("SMTP_HOST", "MEETING_SMTP_HOST", "SMTP_PASSWORD"):
                os.environ.pop(key, None)
            e = resolved_email_cfg({"email": {}})
        self.assertEqual(e["smtp_host"], "smtp.gmail.com")
        self.assertEqual(e["smtp_user"], "you@gmail.com")
        self.assertEqual(e["smtp_port"], 587)
        self.assertFalse(e["use_ssl"])
        with mock.patch.dict(os.environ, env):
            self.assertTrue(EmailSender({"email": {}}).is_configured())

    def test_small_wav_attached_with_txts(self):
        with tempfile.TemporaryDirectory() as td:
            save_four_artifacts(td, [("00:00", "?", "hi")], [{"src": "hi", "dst": "你好"}], "摘要")
            paths, notes = collect_meeting_attachments(td)
            names = [os.path.basename(p) for p in paths]
            self.assertIn(ARTIFACT_WAV, names)
            self.assertIn(ARTIFACT_TRANSCRIPT, names)
            self.assertFalse(notes)
            self.assertTrue(os.path.isfile(os.path.join(td, ARTIFACT_WAV)))

    def test_huge_wav_is_not_silently_skipped(self):
        """Replaces the old 'skip huge wav' behavior: must transcode to MP3."""
        with tempfile.TemporaryDirectory() as td:
            save_four_artifacts(td, [("00:00", "?", "hi")], [{"src": "hi", "dst": "你好"}], "摘要")
            wav = os.path.join(td, ARTIFACT_WAV)
            with open(wav, "wb") as f:
                f.write(b"W" * 200)
            called = []

            def fake_mp3(src, dst, bitrate="80k"):
                called.append(bitrate)
                with open(dst, "wb") as out:
                    out.write(b"M" * 20)
                return dst

            paths, notes = collect_meeting_attachments(
                td, max_attach_bytes=150, transcode_mp3=fake_mp3,
            )
            names = [os.path.basename(p) for p in paths]
            self.assertTrue(called, "ffmpeg/mp3 transcode must run for a large wav")
            self.assertIn(ARTIFACT_MP3, names)
            self.assertNotIn(ARTIFACT_WAV, names)
            self.assertTrue(os.path.isfile(wav))
            self.assertFalse(any("未随信附上" in n and "mp3" not in n.lower() for n in notes))
            self.assertTrue(any("压缩" in n for n in notes))

    def test_large_wav_transcodes_to_mp3(self):
        with tempfile.TemporaryDirectory() as td:
            save_four_artifacts(td, [("00:00", "?", "hi")], [{"src": "hi", "dst": "你好"}], "摘要")
            wav = os.path.join(td, ARTIFACT_WAV)
            with open(wav, "wb") as f:
                f.write(b"W" * 200)

            def fake_mp3(src, dst, bitrate="80k"):
                self.assertTrue(os.path.isfile(src))
                with open(dst, "wb") as out:
                    out.write(b"M" * 20)
                return dst

            paths, notes = collect_meeting_attachments(
                td, max_attach_bytes=150, transcode_mp3=fake_mp3,
            )
            names = [os.path.basename(p) for p in paths]
            self.assertIn(ARTIFACT_TRANSCRIPT, names)
            self.assertIn(ARTIFACT_TRANSLATION, names)
            self.assertIn(ARTIFACT_SUMMARY, names)
            self.assertIn(ARTIFACT_MP3, names)
            self.assertNotIn(ARTIFACT_WAV, names)
            self.assertTrue(os.path.isfile(wav), "original wav must stay on disk")
            self.assertTrue(any("压缩" in n and "mp3" in n.lower() for n in notes))

    def test_mp3_still_over_limit_is_explained(self):
        with tempfile.TemporaryDirectory() as td:
            save_four_artifacts(td, [("00:00", "?", "hi")], [{"src": "hi", "dst": "你好"}], "摘要")
            wav = os.path.join(td, ARTIFACT_WAV)
            with open(wav, "wb") as f:
                f.write(b"W" * 200)

            def huge_mp3(src, dst, bitrate="80k"):
                with open(dst, "wb") as out:
                    out.write(b"M" * 200)
                return dst

            paths, notes = collect_meeting_attachments(
                td, max_attach_bytes=80, transcode_mp3=huge_mp3,
            )
            names = [os.path.basename(p) for p in paths]
            self.assertNotIn(ARTIFACT_WAV, names)
            self.assertNotIn(ARTIFACT_MP3, names)
            self.assertTrue(os.path.isfile(wav))
            joined = "\n".join(notes)
            self.assertIn("仍超过", joined)
            self.assertIn("未使用网盘", joined)

    def test_send_meeting_package_body_and_attachments(self):
        sent = {}

        class Dummy(EmailSender):
            def is_configured(self):
                return True

            def send(self, subject, body, to_addrs=None, attachments=None, cc_addrs=None):
                sent["subject"] = subject
                sent["body"] = body
                sent["to"] = to_addrs
                sent["attachments"] = [os.path.basename(p) for p in attachments or []]
                return True

        with tempfile.TemporaryDirectory() as td:
            save_four_artifacts(
                td, [("00:00", "?", "hello")], [{"src": "hello", "dst": "你好"}],
                "这是中文摘要",
            )
            Dummy({"email": {"to": "gztonyhuang@outlook.com"}}).send_meeting_package(
                "周会", "这是中文摘要", td, to_addrs=["gztonyhuang@outlook.com"],
            )
        self.assertIn("这是中文摘要", sent["body"])
        self.assertIn("周会", sent["subject"])
        self.assertEqual(sent["to"], ["gztonyhuang@outlook.com"])
        for name in (ARTIFACT_TRANSCRIPT, ARTIFACT_TRANSLATION, ARTIFACT_SUMMARY, ARTIFACT_WAV):
            self.assertIn(name, sent["attachments"])
        self.assertIn("audio.wav", sent["body"])

    def test_send_package_mentions_mp3_compression(self):
        sent = {}

        class Dummy(EmailSender):
            def is_configured(self):
                return True

            def send(self, subject, body, to_addrs=None, attachments=None, cc_addrs=None):
                sent["body"] = body
                sent["attachments"] = [os.path.basename(p) for p in attachments or []]
                return True

            def resolved(self):
                return {
                    "to_addrs": ["gztonyhuang@outlook.com"],
                    "max_attach_bytes": 150,
                }

        with tempfile.TemporaryDirectory() as td:
            save_four_artifacts(
                td, [("00:00", "?", "hello")], [{"src": "hello", "dst": "你好"}],
                "这是中文摘要",
            )
            with open(os.path.join(td, ARTIFACT_WAV), "wb") as f:
                f.write(b"W" * 200)

            def fake_mp3(src, dst, bitrate="80k"):
                with open(dst, "wb") as out:
                    out.write(b"M" * 20)
                return dst

            with mock.patch("core.audio_source.convert_to_speech_mp3", side_effect=fake_mp3):
                Dummy({}).send_meeting_package("周会", "这是中文摘要", td)

        self.assertIn(ARTIFACT_MP3, sent["attachments"])
        self.assertNotIn(ARTIFACT_WAV, sent["attachments"])
        self.assertIn("压缩", sent["body"])
        self.assertIn("mp3", sent["body"].lower())


if __name__ == "__main__":
    unittest.main()

