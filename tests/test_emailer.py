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

    def test_collect_txt_and_skip_huge_wav(self):
        with tempfile.TemporaryDirectory() as td:
            save_four_artifacts(td, [("00:00", "?", "hi")], [{"src": "hi", "dst": "你好"}], "摘要")
            wav = os.path.join(td, ARTIFACT_WAV)
            with open(wav, "wb") as f:
                f.write(b"0" * 100)
            paths, notes = collect_meeting_attachments(td, max_wav_bytes=10)
            names = [os.path.basename(p) for p in paths]
            self.assertIn(ARTIFACT_TRANSCRIPT, names)
            self.assertIn(ARTIFACT_TRANSLATION, names)
            self.assertIn(ARTIFACT_SUMMARY, names)
            self.assertNotIn(ARTIFACT_WAV, names)
            self.assertTrue(notes)
            self.assertTrue(all(n.endswith(".txt") for n in names))

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


if __name__ == "__main__":
    unittest.main()

