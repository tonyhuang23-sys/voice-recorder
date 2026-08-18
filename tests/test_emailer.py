import unittest
from unittest import mock

from core.emailer import EmailSender, connect_smtp, _email_cfg


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


if __name__ == "__main__":
    unittest.main()
