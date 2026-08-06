"""Email delivery via SMTP (SSL/TLS), with attachment support."""
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.header import Header

logger = logging.getLogger(__name__)


class EmailSender:
    def __init__(self, cfg):
        self.cfg = cfg

    def is_configured(self):
        e = self.cfg["email"]
        return bool(e.get("smtp_host") and e.get("smtp_user") and e.get("smtp_password"))

    def test_connection(self):
        """Verify SMTP server/login without sending mail."""
        e = self.cfg["email"]
        if not self.is_configured():
            raise RuntimeError("SMTP 未配置")
        port = int(e.get("smtp_port", 465))
        use_ssl = bool(e.get("use_ssl", True))
        if use_ssl:
            server = smtplib.SMTP_SSL(e["smtp_host"], port, timeout=20)
        else:
            server = smtplib.SMTP(e["smtp_host"], port, timeout=20)
            server.ehlo()
            server.starttls()
        try:
            server.login(e["smtp_user"], e["smtp_password"])
            return True
        finally:
            server.quit()

    def send(self, subject, body, to_addrs=None, attachments=None, cc_addrs=None):
        e = self.cfg["email"]
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

        port = int(e.get("smtp_port", 465))
        use_ssl = bool(e.get("use_ssl", True))
        if use_ssl:
            server = smtplib.SMTP_SSL(e["smtp_host"], port, timeout=30)
        else:
            server = smtplib.SMTP(e["smtp_host"], port, timeout=30)
            server.ehlo()
            server.starttls()
        try:
            server.login(e["smtp_user"], e["smtp_password"])
            server.sendmail(e["smtp_user"], to_addrs + (cc_addrs or []),
                            msg.as_string())
        finally:
            server.quit()
        return True
