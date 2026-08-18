"""Lark/Feishu custom-bot webhook: text + a simple interactive card.

Webhook resolution (first non-empty wins):
  1. environment variable LARK_WEBHOOK_URL
  2. gitignored config.json → lark.webhook_url

Never log or raise the raw webhook URL (it is a secret).
"""
import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

ENV_WEBHOOK = "LARK_WEBHOOK_URL"
_TEXT_LIMIT = 8000
_CARD_LIMIT = 4000


def resolve_webhook_url(cfg=None):
    """Return the webhook URL from env or config, or '' if unset."""
    env = (os.environ.get(ENV_WEBHOOK) or "").strip()
    if env:
        return env
    if not cfg:
        return ""
    lark = cfg.get("lark") if isinstance(cfg, dict) else None
    if isinstance(lark, dict):
        return (lark.get("webhook_url") or "").strip()
    return ""


class LarkPusher:
    def __init__(self, cfg=None, webhook_url=None, timeout=None):
        self.cfg = cfg or {}
        lark = self.cfg.get("lark") if isinstance(self.cfg, dict) else {}
        if not isinstance(lark, dict):
            lark = {}
        self.webhook = (webhook_url or resolve_webhook_url(self.cfg)).strip()
        self.timeout = float(
            timeout if timeout is not None else lark.get("timeout_sec", 15) or 15
        )
        self.enabled = bool(lark.get("enabled", True))

    def is_configured(self):
        return bool(self.webhook) and self.webhook.startswith(("http://", "https://"))

    def should_push(self):
        return self.enabled and self.is_configured()

    def push_text(self, text):
        """POST a plain text message. Skip (return False) if webhook unset."""
        if not self.is_configured():
            logger.info("Lark webhook unset, skip text push")
            return False
        payload = {
            "msg_type": "text",
            "content": {"text": _clip(text, _TEXT_LIMIT)},
        }
        self._post(payload)
        return True

    def push_card(self, title, body, footer="MeetingAssist"):
        """POST a simple interactive card. Skip (return False) if webhook unset."""
        if not self.is_configured():
            logger.info("Lark webhook unset, skip card push")
            return False
        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "template": "blue",
                    "title": {
                        "tag": "plain_text",
                        "content": _clip(title or "会议摘要", 100),
                    },
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": _clip(body, _CARD_LIMIT),
                        },
                    },
                    {"tag": "hr"},
                    {
                        "tag": "note",
                        "elements": [
                            {"tag": "plain_text", "content": _clip(footer, 200)},
                        ],
                    },
                ],
            },
        }
        self._post(payload)
        return True

    def push_meeting(self, title, summary, extra=None, emailed=None):
        """POST Chinese summary as chat text + a card (no file attachments).

        Custom-bot webhooks cannot reliably attach binaries; chat = summary text.
        The card notes that the four files were emailed (or not, if email skipped).

        Returns True if at least one message was sent. Skips if webhook unset.
        Raises RuntimeError on HTTP / API failure (never includes the URL).
        """
        if not self.is_configured():
            logger.info("Lark webhook unset, skip meeting push")
            return False
        title = title or "会议记录"
        summary = summary or "（无摘要）"
        extra = extra or ""
        if emailed is True:
            mail_note = (
                "转写记录.txt、翻译.txt、中文摘要.txt 以及音频（WAV 或因体积压缩的 MP3）已通过邮件发送。"
            )
        elif emailed is False:
            mail_note = (
                "四个文件已保存在本地输出目录；邮件未发送（SMTP 未配置或发送失败）。"
            )
        else:
            mail_note = (
                "转写记录.txt、翻译.txt、中文摘要.txt 以及音频已通过邮件发送。"
            )
        # Chat = Chinese summary content (webhook cannot attach files).
        text = f"{title}\n\n{summary}"
        card_body = summary
        if extra:
            card_body = f"{card_body}\n\n{extra}"
        card_body = f"{card_body}\n\n{mail_note}"
        self.push_text(text)
        self.push_card(f"会议摘要 · {title}", card_body, footer=mail_note)
        logger.info("Lark meeting push ok")
        return True

    def _post(self, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.webhook,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                status = int(getattr(resp, "status", 200) or 200)
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Lark webhook HTTP {e.code}") from None
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            raise RuntimeError(f"Lark webhook request failed: {reason}") from None
        except TimeoutError:
            raise RuntimeError("Lark webhook timed out") from None
        if status < 200 or status >= 300:
            raise RuntimeError(f"Lark webhook HTTP {status}")
        _raise_if_lark_error(body)


def _raise_if_lark_error(body):
    if not body or not body.strip():
        return
    try:
        data = json.loads(body)
    except Exception:
        return
    if not isinstance(data, dict):
        return
    code = data.get("code", data.get("StatusCode", data.get("Code")))
    if code not in (None, 0, "0"):
        msg = data.get("msg") or data.get("StatusMessage") or data.get("message") or "error"
        raise RuntimeError(f"Lark webhook rejected: {msg}")


def _clip(text, limit):
    text = "" if text is None else str(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"
