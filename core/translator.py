"""Translation: local Argos by default; optional OpenAI-compatible cloud if a key exists."""
import logging
import urllib.request
import json

from .llm import chat_completions, resolve_llm_cloud

logger = logging.getLogger(__name__)


class Translator:
    def __init__(self, cfg):
        self.cfg = cfg
        self.mode = (cfg.get("translate") or {}).get("mode", "local")
        self._argos = {}
        self._argos_ready = False

    # ---- local ----
    def _ensure_argos(self):
        if self._argos_ready:
            return True
        try:
            import argostranslate.translate as t

            langs = t.get_installed_languages()
            for l in langs:
                self._argos[l.code] = l
            self._argos_ready = True
            return True
        except Exception as e:
            logger.warning("argos not usable: %s", e)
            return False

    def translate_local(self, text, src, dst):
        if not self._ensure_argos():
            return None
        try:
            import argostranslate.translate as t

            langs = t.get_installed_languages()
            src_lang = next((l for l in langs if l.code == src), None)
            dst_lang = next((l for l in langs if l.code == dst), None)
            if src_lang is None or dst_lang is None:
                return None
            tr = src_lang.get_translation(dst_lang)
            return tr.translate(text)
        except Exception as e:
            logger.warning("local translate failed: %s", e)
            return None

    # ---- cloud (Grok / OpenAI-compatible / DeepL) ----
    def translate_cloud(self, text, src, dst):
        cloud = resolve_llm_cloud(self.cfg, "translate")
        if cloud.get("provider") == "deepl" and cloud.get("deepl_api_key"):
            return self._deepl(text, src, dst, cloud["deepl_api_key"])
        if not cloud.get("api_key"):
            return None
        try:
            return chat_completions(
                [
                    {"role": "system",
                     "content": (
                         f"You are a professional translator. Translate the user text "
                         f"from {src} to {dst}. Output only the translation, no explanations."
                     )},
                    {"role": "user", "content": text},
                ],
                cloud,
                timeout=60,
                temperature=0.2,
            )
        except Exception as e:
            logger.warning("cloud translate failed: %s", e)
            return None

    def _deepl(self, text, src, dst, key):
        params = json.dumps({
            "text": [text],
            "target_lang": "ZH" if dst == "zh" else "EN",
            "source_lang": "ZH" if src == "zh" else "EN",
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api-free.deepl.com/v2/translate",
            data=params,
            headers={"Content-Type": "application/json",
                     "Authorization": f"DeepL-Auth-Key {key}"},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
            return data["translations"][0]["text"]

    # ---- public ----
    def translate(self, text, src="auto", dst=None, mode=None):
        if not text or not text.strip():
            return ""
        dst = dst or self.cfg["translate"].get("target_lang", "zh")
        mode = mode or self.mode or "local"
        if src == "auto":
            src = "zh" if _looks_like_chinese(text) else "en"
        if src == dst:
            return text
        if mode == "local":
            out = self.translate_local(text, src, dst)
            if out:
                return out
            return self.translate_cloud(text, src, dst) or ""
        out = self.translate_cloud(text, src, dst)
        if out:
            return out
        logger.info("translate falling back to local Argos")
        return self.translate_local(text, src, dst) or ""


def _looks_like_chinese(text, ratio=0.15):
    if not text:
        return False
    cnt = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return cnt / max(1, len(text)) > ratio
