"""Email delivery via SMTP (SSL/TLS), with attachment support."""
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.header import Header

logger = logging.getLogger(__name__)


def _email_cfg(cfg):
    """Accept either the full app config or the email section itself."""
    if not isinstance(cfg, dict):
        return {}
    inner = cfg.get("email")
    if isinstance(inner, dict) and ("smtp_host" in inner or "smtp_user" in inner):
        return inner
    return cfg


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


class EmailSender:
    def __init__(self, cfg):
        self.cfg = cfg

    def is_configured(self):
        e = _email_cfg(self.cfg)
        return bool(e.get("smtp_host") and e.get("smtp_user") and e.get("smtp_password"))

    def test_connection(self):
        """Verify SMTP server/login without sending mail."""
        e = _email_cfg(self.cfg)
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
        e = _email_cfg(self.cfg)
        to_addrs = to_addrs or e.get("to_addrs") or []
        if not self.is_configured():
            raise RuntimeError("SMTP 未配置,请先在设置中填写 SMTP 信息")
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
            part.add_header("Content-Disposition", "attachment",
                            filename=("utf-8", "", os.path.basename(path)))
            msg.attach(part)

        server = connect_smtp(e, timeout=30)
        try:
            server.login(e["smtp_user"], e["smtp_password"])
            server.sendmail(e["smtp_user"], to_addrs + (cc_addrs or []),
                            msg.as_string())
        finally:
            try:
                server.quit()
            except Exception:
                pass
        return True
