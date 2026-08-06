"""Translation engine: local (argos-translate) + cloud (OpenAI-compatible / DeepL)."""
import logging
import urllib.request
import json

logger = logging.getLogger(__name__)


class Translator:
    def __init__(self, cfg):
        self.cfg = cfg
        self.mode = cfg["translate"].get("mode", "local")
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

    # ---- cloud ----
    def translate_cloud(self, text, src, dst):
        cloud = self.cfg["translate"]["cloud"]
        provider = cloud.get("provider", "openai")
        if provider == "deepl" and cloud.get("deepl_api_key"):
            return self._deepl(text, src, dst, cloud["deepl_api_key"])
        if cloud.get("api_key"):
            return self._openai(text, src, dst, cloud)
        return None

    def _openai(self, text, src, dst, cloud):
        import urllib.request as u

        body = json.dumps({
            "model": cloud.get("model", "gpt-4o-mini"),
            "messages": [
                {"role": "system",
                 "content": f"You are a professional translator. Translate the user text from {src} to {dst}. "
                            f"Output only the translation, no explanations."},
                {"role": "user", "content": text},
            ],
            "temperature": 0.2,
        }).encode("utf-8")
        req = u.Request(
            cloud.get("base_url", "https://api.openai.com/v1") + "/chat/completions",
            data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {cloud['api_key']}"},
        )
        with u.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"].strip()

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
        mode = mode or self.mode
        if src == "auto":
            src = "zh" if _looks_like_chinese(text) else "en"
        if src == dst:
            return text
        if mode == "local":
            out = self.translate_local(text, src, dst)
            if out:
                return out
            return self.translate_cloud(text, src, dst) or ""
        else:
            out = self.translate_cloud(text, src, dst)
            if out:
                return out
            return self.translate_local(text, src, dst) or ""


def _looks_like_chinese(text, ratio=0.15):
    if not text:
        return False
    cnt = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return cnt / max(1, len(text)) > ratio
