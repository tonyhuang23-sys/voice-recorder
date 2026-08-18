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
    ARTIFACT_MP3,
    ARTIFACT_SUMMARY,
    ARTIFACT_TRANSCRIPT,
    ARTIFACT_TRANSLATION,
    ARTIFACT_WAV,
    list_text_files,
)

logger = logging.getLogger(__name__)

DEFAULT_TO = "gztonyhuang@outlook.com"
GMAIL_ATTACH_LIMIT = 25 * 1024 * 1024
SPEECH_MP3_BITRATES = ("80k", "64k")  # try 80k first, then 64k if still over budget
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
        max_attach = int(
            e.get("max_attach_bytes") or e.get("max_wav_bytes") or GMAIL_ATTACH_LIMIT
        )
    except (TypeError, ValueError):
        max_attach = GMAIL_ATTACH_LIMIT

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
        "max_attach_bytes": max_attach,
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


def _file_size(path):
    try:
        return os.path.getsize(path) if path and os.path.isfile(path) else 0
    except OSError:
        return 0


def _mb(n):
    return n / (1024 * 1024)


def collect_meeting_attachments(folder, max_attach_bytes=GMAIL_ATTACH_LIMIT,
                                transcode_mp3=None):
    """Return (paths, notes). Original WAV always stays on disk.

    Attachments: three .txt files + WAV if wav+txts fit under Gmail's 25MB
    budget; otherwise a speech MP3 (never silently drop a large WAV).
    """
    from .audio_source import convert_to_speech_mp3

    encode = transcode_mp3 or convert_to_speech_mp3
    limit = int(max_attach_bytes or GMAIL_ATTACH_LIMIT)
    attachments = []
    notes = []
    if not folder or not os.path.isdir(folder):
        notes.append("未找到输出目录,无法附加会议文件。")
        return attachments, notes

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
    txt_size = sum(_file_size(p) for p in attachments)

    wav = os.path.join(folder, ARTIFACT_WAV)
    if not os.path.isfile(wav):
        notes.append("未找到原始 WAV,邮件未附音频。完整录音应保存在输出目录。")
        return attachments, notes

    wav_size = _file_size(wav)
    if wav_size + txt_size <= limit:
        attachments.append(wav)
        return attachments, notes

    mp3 = os.path.join(folder, ARTIFACT_MP3)
    last_rate = SPEECH_MP3_BITRATES[0]
    mp3_size = 0
    encode_error = None
    for rate in SPEECH_MP3_BITRATES:
        last_rate = rate
        try:
            encode(wav, mp3, bitrate=rate)
        except Exception as e:
            encode_error = e
            logger.warning("mp3 transcode failed (%s): %s", rate, e)
            continue
        mp3_size = _file_size(mp3)
        if mp3_size > 0 and mp3_size + txt_size <= limit:
            attachments.append(mp3)
            notes.append(
                f"原始 WAV 约 {_mb(wav_size):.1f}MB,与文本合计超过 Gmail {_mb(limit):.0f}MB "
                f"附件上限,已压缩为 audio.mp3({_mb(mp3_size):.1f}MB, {rate} mono) 随信附上。"
                f"因 WAV 过大,音频以 MP3 发送。完整 WAV 仍保存在本地: {wav}"
            )
            return attachments, notes

    if mp3_size <= 0:
        err = encode_error or "unknown"
        notes.append(
            f"原始 WAV 约 {_mb(wav_size):.1f}MB,超过 Gmail {_mb(limit):.0f}MB 附件上限,"
            f"且转 MP3 失败({err})。未静默丢弃: 完整 WAV 仍在本地 {wav}"
        )
        return attachments, notes

    notes.append(
        f"原始 WAV 约 {_mb(wav_size):.1f}MB,已尝试压缩为 MP3({last_rate}, "
        f"约 {_mb(mp3_size):.1f}MB),仍超过 Gmail {_mb(limit):.0f}MB 附件上限,"
        f"因此未能把音频放进附件(未使用网盘链接)。完整 WAV 与 MP3 均在本地: {folder}"
    )
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
        """Email Chinese summary and attach txts plus WAV or speech MP3.

        Original WAV always remains in the output folder. If wav+txts exceed
        Gmail's 25MB budget, attach a compressed MP3 and explain that in the body.
        """
        e = self.resolved()
        to_addrs = to_addrs or e.get("to_addrs") or [DEFAULT_TO]
        attachments, notes = collect_meeting_attachments(
            folder, max_attach_bytes=e.get("max_attach_bytes", GMAIL_ATTACH_LIMIT),
        )
        names = [os.path.basename(p) for p in attachments]
        audio_label = ARTIFACT_WAV if ARTIFACT_WAV in names else (
            ARTIFACT_MP3 if ARTIFACT_MP3 in names else "（音频见正文说明）"
        )
        body_parts = [
            f"会议标题: {title or '会议记录'}",
            f"收件人: {', '.join(to_addrs)}",
            "",
            "【中文摘要】",
            summary or "（无摘要）",
            "",
            f"附件: {ARTIFACT_TRANSCRIPT} / {ARTIFACT_TRANSLATION} / {ARTIFACT_SUMMARY} / {audio_label}",
        ]
        if notes:
            body_parts.extend(["", *notes])
        if folder:
            body_parts.extend(["", f"输出目录(含完整 WAV): {folder}"])
        self.send(
            subject=f"[会议摘要] {title or '会议记录'}",
            body="\n".join(body_parts),
            to_addrs=to_addrs,
            attachments=attachments,
        )
        return {
            "to": list(to_addrs),
            "attachments": names,
            "notes": notes,
        }
