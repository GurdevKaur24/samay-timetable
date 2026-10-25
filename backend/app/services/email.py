"""Sending email (invites and password resets) through any SMTP server, e.g. Gmail with an app password or Brevo.

Off unless SAMAY_SMTP_HOST and SAMAY_EMAIL_FROM are set; then the app shows links on screen for the coordinator to
share instead. Credentials come only from the environment, never from the code.
"""

import logging
import smtplib
from email.message import EmailMessage

from .. import config

log = logging.getLogger("samay.email")


def smtp_sender():
    """A function (to, subject, text) -> bool that sends one email, or None when email isn't set up."""
    if not (config.SMTP_HOST and config.EMAIL_FROM):
        return None

    def send(to: str, subject: str, text: str) -> bool:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = config.EMAIL_FROM, to, subject
        msg.set_content(text)
        try:
            if config.SMTP_PORT == 465:
                server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=15)
            else:
                server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15)
                server.starttls()
            with server:
                if config.SMTP_USER:
                    server.login(config.SMTP_USER, config.SMTP_PASSWORD)
                server.send_message(msg)
            return True
        except (OSError, smtplib.SMTPException) as e:
            log.warning("Email to %s couldn't be sent: %s", to, e)
            return False

    return send
