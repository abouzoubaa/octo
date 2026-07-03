"""Outbound email — the digest/briefing delivery transport.

Deliberately tiny: SMTP (STARTTLS) when configured, log-only otherwise, so the
weekly digest works in production with four env vars and stays dependency-free
locally. Anything richer (SES/Postmark API, DM delivery) slots in behind
``send_email`` without touching callers.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from cci_core.config import get_settings

log = logging.getLogger(__name__)


def email_configured() -> bool:
    return bool(get_settings().smtp_host)


def send_email(to: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True on handoff to the SMTP server;
    False (with a log line) when unconfigured or on transport failure — callers
    fall back to logging the content so nothing is silently lost."""
    s = get_settings()
    if not s.smtp_host:
        log.info("email transport unconfigured — would send to %s: %s", to, subject)
        return False
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password)
            smtp.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("email send to %s failed: %s", to, exc)
        return False
