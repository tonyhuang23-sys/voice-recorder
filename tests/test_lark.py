import json
import os
import unittest
from unittest import mock

from core.lark import LarkPusher, resolve_webhook_url


class LarkTests(unittest.TestCase):
    def test_skip_when_unset(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LARK_WEBHOOK_URL", None)
            pusher = LarkPusher({"lark": {"webhook_url": ""}})
            self.assertFalse(pusher.is_configured())
            self.assertFalse(pusher.push_text("hi"))
            self.assertFalse(pusher.push_card("t", "b"))
            self.assertFalse(pusher.push_meeting("t", "s"))

    def test_env_overrides_config(self):
        cfg = {"lark": {"webhook_url": "https://example.com/from-config"}}
        with mock.patch.dict(os.environ, {"LARK_WEBHOOK_URL": "https://example.com/from-env"}):
            self.assertEqual(resolve_webhook_url(cfg), "https://example.com/from-env")

    def test_push_text_and_card(self):
        posts = []

        class Resp:
            status = 200

            def read(self):
                return b'{"StatusCode":0,"code":0}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            posts.append(json.loads(req.data.decode("utf-8")))
            self.assertNotIn("open.feishu.cn", req.full_url)  # placeholder host
            return Resp()

        pusher = LarkPusher(
            {"lark": {"timeout_sec": 2}},
            webhook_url="https://example.com/hook/test-token",
        )
        with mock.patch("core.lark.urllib.request.urlopen", side_effect=fake_urlopen):
            self.assertTrue(pusher.push_meeting("周会", "要点一", extra="dir"))
        kinds = [p.get("msg_type") for p in posts]
        self.assertEqual(kinds, ["text", "interactive"])
        self.assertIn("周会", posts[0]["content"]["text"])
        self.assertEqual(posts[1]["card"]["header"]["title"]["content"], "会议摘要 · 周会")

    def test_http_error_hides_webhook(self):
        import urllib.error

        def boom(req, timeout=None):
            raise urllib.error.HTTPError(
                "https://example.com/hook/SECRETTOKEN", 400, "bad", hdrs=None, fp=None
            )

        pusher = LarkPusher(webhook_url="https://example.com/hook/SECRETTOKEN")
        with mock.patch("core.lark.urllib.request.urlopen", side_effect=boom):
            with self.assertRaises(RuntimeError) as ctx:
                pusher.push_text("hi")
        self.assertNotIn("SECRETTOKEN", str(ctx.exception))
        self.assertIn("HTTP 400", str(ctx.exception))

    def test_non_2xx_status(self):
        class Resp:
            status = 500

            def read(self):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        pusher = LarkPusher(webhook_url="https://example.com/hook/x")
        with mock.patch("core.lark.urllib.request.urlopen", return_value=Resp()):
            with self.assertRaises(RuntimeError) as ctx:
                pusher.push_text("hi")
        self.assertIn("HTTP 500", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
