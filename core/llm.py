"""Optional OpenAI-compatible chat completions. A key is never required."""
import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

ENV_XAI_KEY = "XAI_API_KEY"
DEFAULT_XAI_BASE = "https://api.x.ai/v1"
DEFAULT_XAI_MODEL = "grok-3"


def resolve_llm_cloud(cfg, section="translate"):
    """Resolve api_key / base_url / model for translate or summary.

    Optional key (never required): env XAI_API_KEY, then config
    <section>.cloud.api_key. Empty key means cloud is skipped.
    """
    block = {}
    if isinstance(cfg, dict):
        block = (cfg.get(section) or {}).get("cloud") or {}
    if not isinstance(block, dict):
        block = {}
    key = (os.environ.get(ENV_XAI_KEY) or "").strip() or (block.get("api_key") or "").strip()
    base = (block.get("base_url") or DEFAULT_XAI_BASE).strip().rstrip("/")
    model = (block.get("model") or DEFAULT_XAI_MODEL).strip() or DEFAULT_XAI_MODEL
    provider = (block.get("provider") or "xai").strip() or "xai"
    return {
        "api_key": key,
        "base_url": base or DEFAULT_XAI_BASE,
        "model": model,
        "provider": provider,
        "deepl_api_key": (block.get("deepl_api_key") or "").strip(),
    }


def has_llm_key(cfg, section="translate"):
    return bool(resolve_llm_cloud(cfg, section).get("api_key"))


def chat_completions(messages, cloud, timeout=90, temperature=0.2):
    """POST /chat/completions. Raises on HTTP/API failure. Never logs the key."""
    if not cloud or not cloud.get("api_key"):
        raise RuntimeError("LLM API key unset")
    base = (cloud.get("base_url") or DEFAULT_XAI_BASE).rstrip("/")
    model = cloud.get("model") or DEFAULT_XAI_MODEL
    body = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }).encode("utf-8")
    req = urllib.request.Request(
        base + "/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cloud['api_key']}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"LLM HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"LLM request failed: {getattr(e, 'reason', e)}") from None
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise RuntimeError("LLM response invalid")
    if data.get("error"):
        msg = data["error"]
        if isinstance(msg, dict):
            msg = msg.get("message") or "error"
        raise RuntimeError(f"LLM rejected: {msg}")
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        raise RuntimeError("LLM response missing content") from None
