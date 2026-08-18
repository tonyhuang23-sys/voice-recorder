import json
import os
import unittest
from unittest import mock

from core.config import DEFAULT_CONFIG
from core.llm import DEFAULT_XAI_BASE, DEFAULT_XAI_MODEL, resolve_llm_cloud
from core.summarizer import Summarizer
from core.translator import Translator


def _cfg(**cloud_overrides):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["translate"]["cloud"].update(cloud_overrides)
    cfg["summary"]["cloud"].update(cloud_overrides)
    return cfg


class LlmRoutingTests(unittest.TestCase):
    def test_defaults_prefer_grok_cloud(self):
        self.assertEqual(DEFAULT_CONFIG["translate"]["mode"], "cloud")
        self.assertEqual(DEFAULT_CONFIG["summary"]["mode"], "cloud")
        self.assertEqual(DEFAULT_CONFIG["translate"]["cloud"]["base_url"], DEFAULT_XAI_BASE)
        self.assertEqual(DEFAULT_CONFIG["summary"]["cloud"]["base_url"], DEFAULT_XAI_BASE)
        self.assertEqual(DEFAULT_CONFIG["translate"]["cloud"]["model"], DEFAULT_XAI_MODEL)
        self.assertEqual(DEFAULT_CONFIG["translate"]["cloud"]["api_key"], "")
        self.assertEqual(DEFAULT_CONFIG["summary"]["cloud"]["api_key"], "")

    def test_key_from_env_not_config(self):
        cfg = _cfg(api_key="from-config-not-secret")
        with mock.patch.dict(os.environ, {"XAI_API_KEY": "from-env-not-secret"}):
            cloud = resolve_llm_cloud(cfg, "translate")
        self.assertEqual(cloud["api_key"], "from-env-not-secret")
        self.assertEqual(cloud["base_url"], DEFAULT_XAI_BASE)

    def test_translate_no_key_falls_back_local(self):
        cfg = _cfg(api_key="")
        tr = Translator(cfg)
        with mock.patch.dict(os.environ, {"XAI_API_KEY": ""}, clear=False):
            os.environ.pop("XAI_API_KEY", None)
            with mock.patch.object(tr, "translate_local", return_value="本地译文") as loc:
                out = tr.translate("hello there", src="en", dst="zh")
        self.assertEqual(out, "本地译文")
        loc.assert_called()

    def test_translate_cloud_preferred(self):
        cfg = _cfg()
        tr = Translator(cfg)
        with mock.patch("core.translator.chat_completions", return_value="云端译文") as chat, \
             mock.patch.object(tr, "translate_local") as loc, \
             mock.patch("core.translator.resolve_llm_cloud",
                        return_value={"api_key": "test-not-a-real-key",
                                      "base_url": DEFAULT_XAI_BASE,
                                      "model": "grok-3",
                                      "provider": "xai",
                                      "deepl_api_key": ""}):
            out = tr.translate("hello there", src="en", dst="zh")
        self.assertEqual(out, "云端译文")
        chat.assert_called()
        loc.assert_not_called()

    def test_translate_cloud_error_falls_back_local(self):
        cfg = _cfg()
        tr = Translator(cfg)
        with mock.patch("core.translator.chat_completions",
                        side_effect=RuntimeError("LLM HTTP 401")), \
             mock.patch.object(tr, "translate_local", return_value="回退译文") as loc, \
             mock.patch("core.translator.resolve_llm_cloud",
                        return_value={"api_key": "test-not-a-real-key",
                                      "base_url": DEFAULT_XAI_BASE,
                                      "model": "grok-3",
                                      "provider": "xai",
                                      "deepl_api_key": ""}):
            out = tr.translate("hello there", src="en", dst="zh")
        self.assertEqual(out, "回退译文")
        loc.assert_called()

    def test_summary_no_key_uses_local(self):
        cfg = _cfg(api_key="")
        sm = Summarizer(cfg)
        lines = [("00:00", "A", "我们下周发布产品并且预算是一百万元")]
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XAI_API_KEY", None)
            with mock.patch.object(sm, "_cloud_summarize") as cloud:
                out = sm.summarize(lines, title="发布会")
        cloud.assert_not_called()
        self.assertIn("【会议主题】", out)
        self.assertIn("【关键要点】", out)
        self.assertIn("【结论与决议】", out)
        self.assertIn("【后续行动】", out)
        self.assertIn("本地", out)

    def test_summary_cloud_preferred(self):
        cfg = _cfg()
        sm = Summarizer(cfg)
        grok = "【会议主题】发布\n【关键要点】1. 预算\n【结论与决议】通过\n【后续行动】下周"
        with mock.patch("core.summarizer.chat_completions", return_value=grok) as chat, \
             mock.patch("core.summarizer.resolve_llm_cloud",
                        return_value={"api_key": "test-not-a-real-key",
                                      "base_url": DEFAULT_XAI_BASE,
                                      "model": "grok-3",
                                      "provider": "xai"}):
            out = sm.summarize([("00:00", "A", "hello meeting budget")], title="发布会")
        self.assertEqual(out, grok)
        chat.assert_called()
        sys_msg = chat.call_args[0][0][0]["content"]
        self.assertIn("会议主题", sys_msg)
        self.assertIn("关键要点", sys_msg)
        self.assertIn("结论与决议", sys_msg)
        self.assertIn("后续行动", sys_msg)

    def test_summary_cloud_error_falls_back_local(self):
        cfg = _cfg()
        sm = Summarizer(cfg)
        with mock.patch("core.summarizer.chat_completions",
                        side_effect=RuntimeError("LLM HTTP 500")), \
             mock.patch("core.summarizer.resolve_llm_cloud",
                        return_value={"api_key": "test-not-a-real-key",
                                      "base_url": DEFAULT_XAI_BASE,
                                      "model": "grok-3",
                                      "provider": "xai"}):
            out = sm.summarize([("00:00", "A", "我们决定下周上线并且需要测试")], title="会")
        self.assertIn("【会议主题】", out)
        self.assertIn("本地", out)

    def test_no_secret_in_defaults(self):
        dumped = json.dumps(DEFAULT_CONFIG)
        self.assertNotIn("xai-", dumped)
        self.assertIn('"api_key": ""', dumped)


if __name__ == "__main__":
    unittest.main()
