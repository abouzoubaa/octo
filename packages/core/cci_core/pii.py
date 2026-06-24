"""PII redaction for audience-supplied text (GDPR data minimisation).

Audience comments/queries are the demand signal — but we never need the
identifying bits. Redact emails, phone numbers, and long digit runs (card/SSN-ish)
before storing or sending to an LLM, so PII isn't persisted or leaked to providers.
"""
from __future__ import annotations

import re

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(r"(?<!\w)(\+?\d[\d\s().-]{7,}\d)(?!\w)")
_LONG_DIGITS = re.compile(r"\b\d{9,}\b")  # card / national-id-ish runs


def redact_pii(text: str | None) -> str | None:
    """Return text with emails/phones/long digit runs replaced by placeholders."""
    if not text:
        return text
    text = _EMAIL.sub("[email]", text)
    text = _LONG_DIGITS.sub("[number]", text)
    text = _PHONE.sub("[phone]", text)
    return text


def has_pii(text: str | None) -> bool:
    if not text:
        return False
    return bool(_EMAIL.search(text) or _PHONE.search(text) or _LONG_DIGITS.search(text))
