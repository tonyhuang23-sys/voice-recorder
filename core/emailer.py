"""Email delivery via SMTP (SSL/TLS), with attachment support.

Recipient resolution (first non-empty wins):
  1. env MEETING_EMAIL_TO
  2. config email.to (string) or email.to_addrs (list)
  3. default gztonyhuang@outlook.com

SMTP can come from gitignored config.json or env (Gmail app password, etc.).
Never log passwords. Never commit them.
"""
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.header import Header

from .output import (
    ARTIFACT_SUMMARY,
    ARTIFACT_TRANSCRIPT,
    ARTIFACT_TRANSLATION,
    ARTIFACT_WAV,
    list_text_files,
)

logger = logging.getLogger(__name__)

DEFAULT_TO = "gztonyhuang@outlook.com"
DEFAULT_MAX_WAV = 20 * 1024 * 1024
ENV_TO = "MEETING_EMAIL_TO"


def _email_cfg(cfg):
    """Accept either the full app config or the email section itself."""
    if not isinstance(cfg, dict):
        return {}
    inner = cfg.get("email")
    if isinstance(inner, dict) and (
        "smtp_host" in inner or "smtp_user" in inner or "to" in inner or "to_addrs" in inner
    ):
        return inner
    return cfg


def _env(*names):
    for name in names:
        val = (os.environ.get(name) or "").strip()
        if val:
            return val
    return ""


def resolve_to_addrs(email_cfg=None):
    """Recipient list: env MEETING_EMAIL_TO → email.to / to_addrs → default."""
    raw = _env(ENV_TO)
    if not raw and isinstance(email_cfg, dict):
        raw = email_cfg.get("to") or ""
        if not raw:
            addrs = email_cfg.get("to_addrs") or []
            if isinstance(addrs, str):
                raw = addrs
            elif isinstance(addrs, (list, tuple)):
                raw = ", ".join(str(x) for x in addrs if x)
    if isinstance(raw, (list, tuple)):
        parts = [str(x).strip() for x in raw if str(x).strip()]
    else:
        parts = [x.strip() for x in str(raw or "").replace(";", ",").split(",") if x.strip()]
    return parts or [DEFAULT_TO]


def resolved_email_cfg(cfg):
    """Merge config + env. Gmail: GMAIL_USER / GMAIL_APP_PASSWORD → smtp.gmail.com."""
    e = dict(_email_cfg(cfg) or {})
    host = _env("MEETING_SMTP_HOST", "SMTP_HOST") or (e.get("smtp_host") or "").strip()
    user = _env("MEETING_SMTP_USER", "SMTP_USER", "GMAIL_USER") or (e.get("smtp_user") or "").strip()
    password = _env(
        "MEETING_SMTP_PASSWORD", "SMTP_PASSWORD", "GMAIL_APP_PASSWORD"
    ) or (e.get("smtp_password") or "").strip()
    from_addr = _env("MEETING_SMTP_FROM", "SMTP_FROM") or (e.get("from_addr") or "").strip()
    port_raw = _env("MEETING_SMTP_PORT", "SMTP_PORT")
    ssl_raw = _env("MEETING_SMTP_SSL", "SMTP_USE_SSL")

    gmail_env = bool(_env("GMAIL_USER", "GMAIL_APP_PASSWORD"))
    looks_gmail = (
        gmail_env
        or "gmail.com" in host.lower()
        or user.lower().endswith("@gmail.com")
    )
    if looks_gmail and not host:
        host = "smtp.gmail.com"

    if port_raw:
        port = int(port_raw)
    elif e.get("smtp_port"):
        port = int(e.get("smtp_port") or 465)
        if looks_gmail and host == "smtp.gmail.com" and not (e.get("smtp_host") or "").strip():
            port = 587
    elif looks_gmail:
        port = 587
    else:
        port = 465

    if ssl_raw:
        use_ssl = ssl_raw.lower() in ("1", "true", "yes", "on")
    elif looks_gmail and host == "smtp.gmail.com" and port == 587:
        use_ssl = False
    elif looks_gmail and host == "smtp.gmail.com" and not (e.get("smtp_host") or "").strip():
        use_ssl = False
    else:
        use_ssl = bool(e.get("use_ssl", True))

    try:
        max_wav = int(e.get("max_wav_bytes") or DEFAULT_MAX_WAV)
    except (TypeError, ValueError):
        max_wav = DEFAULT_MAX_WAV

    to_addrs = resolve_to_addrs(e)
    return {
        "smtp_host": host,
        "smtp_port": port,
        "smtp_user": user,
        "smtp_password": password,
        "use_ssl": use_ssl,
        "from_addr": from_addr or user,
        "to": to_addrs[0] if to_addrs else DEFAULT_TO,
        "to_addrs": to_addrs,
        "max_wav_bytes": max_wav,
    }


def connect_smtp(email_cfg, timeout=30):
    """Open an SMTP connection.

    Implicit SSL (SMTP_SSL, typically port 465) never calls STARTTLS.
    Plain SMTP may upgrade with STARTTLS when the server advertises it.
    """
    host = email_cfg["smtp_host"]
    port = int(email_cfg.get("smtp_port", 465))
    use_ssl = bool(email_cfg.get("use_ssl", True))
    if use_ssl:
        return smtplib.SMTP_SSL(host, port, timeout=timeout)
    server = smtplib.SMTP(host, port, timeout=timeout)
    server.ehlo()
    if server.has_extn("starttls"):
        server.starttls()
        server.ehlo()
    return server


def collect_meeting_attachments(folder, max_wav_bytes=DEFAULT_MAX_WAV):
    """Return (paths, notes). Text artifacts are always .txt. WAV only if small enough."""
    attachments = []
    notes = []
    if folder and os.path.isdir(folder):
        for name in (ARTIFACT_TRANSCRIPT, ARTIFACT_TRANSLATION, ARTIFACT_SUMMARY):
            path = os.path.join(folder, name)
            if os.path.isfile(path):
                attachments.append(path)
        extras = [
            p for p in list_text_files(folder)
            if os.path.basename(p) not in {
                ARTIFACT_TRANSCRIPT, ARTIFACT_TRANSLATION, ARTIFACT_SUMMARY,
            }
        ]
        attachments.extend(extras)
        wav = os.path.join(folder, ARTIFACT_WAV)
        if os.path.isfile(wav):
            size = os.path.getsize(wav)
            if size <= int(max_wav_bytes or DEFAULT_MAX_WAV):
                attachments.append(wav)
            else:
                mb = size / (1024 * 1024)
                limit = int(max_wav_bytes or DEFAULT_MAX_WAV) / (1024 * 1024)
                notes.append(
                    f"原始 WAV 约 {mb:.1f}MB,超过附件上限 {limit:.0f}MB,未随信附上。"
                    f"请在本地输出目录查看: {wav}"
                )
    for path in attachments:
        if path.lower().endswith((".doc", ".docx", ".pdf")):
            raise RuntimeError("meeting text artifacts must be .txt")
    return attachments, notes


class EmailSender:
    def __init__(self, cfg):
        self.cfg = cfg

    def resolved(self):
        return resolved_email_cfg(self.cfg)

    def is_configured(self):
        e = self.resolved()
        return bool(e.get("smtp_host") and e.get("smtp_user") and e.get("smtp_password"))

    def test_connection(self):
        """Verify SMTP server/login without sending mail."""
        e = self.resolved()
        if not self.is_configured():
            raise RuntimeError("SMTP 未配置")
        server = connect_smtp(e, timeout=20)
        try:
            server.login(e["smtp_user"], e["smtp_password"])
            return True
        finally:
            try:
                server.quit()
            except Exception:
                pass

    def send(self, subject, body, to_addrs=None, attachments=None, cc_addrs=None):
        e = self.resolved()
        to_addrs = to_addrs or e.get("to_addrs") or [DEFAULT_TO]
        if not self.is_configured():
            raise RuntimeError("SMTP 未配置,请先在设置中填写 SMTP 信息,或设置 GMAIL_USER / GMAIL_APP_PASSWORD")
        if not to_addrs:
            raise RuntimeError("收件人邮箱为空")

        msg = MIMEMultipart()
        msg["From"] = e.get("from_addr") or e.get("smtp_user")
        msg["To"] = ", ".join(to_addrs)
        if cc_addrs:
            msg["Cc"] = ", ".join(cc_addrs)
        msg["Subject"] = Header(subject, "utf-8")
        msg.attach(MIMEText(body, "plain", "utf-8"))

        for path in attachments or []:
            if not path or not os.path.exists(path):
                continue
            with open(path, "rb") as f:
                part = MIMEApplication(f.read(), _subtype="octet-stream")
            filename = os.path.basename(path)
            part.add_header("Content-Disposition", "attachment",
                            filename=("utf-8", "", filename))
            msg.attach(part)

        server = connect_smtp(e, timeout=30)
        try:
            server.login(e["smtp_user"], e["smtp_password"])
            server.sendmail(e["smtp_user"], list(to_addrs) + (cc_addrs or []),
                            msg.as_string())
        finally:
            try:
                server.quit()
            except Exception:
                pass
        return True

    def send_meeting_package(self, title, summary, folder, to_addrs=None):
        """Email Chinese summary in the body and attach the four artifacts.

        Text files are .txt. WAV is attached only when under max_wav_bytes.
        """
        e = self.resolved()
        to_addrs = to_addrs or e.get("to_addrs") or [DEFAULT_TO]
        attachments, notes = collect_meeting_attachments(
            folder, max_wav_bytes=e.get("max_wav_bytes", DEFAULT_MAX_WAV),
        )
        body_parts = [
            f"会议标题: {title or '会议记录'}",
            f"收件人: {', '.join(to_addrs)}",
            "",
            "【中文摘要】",
            summary or "（无摘要）",
            "",
            "附件: 转写记录.txt / 翻译.txt / 会议摘要.txt"
            + (" / audio.wav" if any(p.endswith(ARTIFACT_WAV) for p in attachments) else ""),
        ]
        if notes:
            body_parts.extend(["", *notes])
        if folder:
            body_parts.extend(["", f"输出目录: {folder}"])
        self.send(
            subject=f"[会议摘要] {title or '会议记录'}",
            body="\n".join(body_parts),
            to_addrs=to_addrs,
            attachments=attachments,
        )
        return {
            "to": list(to_addrs),
            "attachments": [os.path.basename(p) for p in attachments],
            "notes": notes,
        }
