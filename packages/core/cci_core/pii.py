"""PII redaction for audience-supplied text (GDPR data minimisation).

Audience comments/queries are the demand signal — but we never need the
identifying bits. Redact emails, phone numbers, and long digit runs (card/SSN-ish)
before storing or sending to an LLM, so PII isn't persisted or leaked to providers.
"""
from __future__ import annotations

import re

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# candidate phone run: digits + separators. We only redact it if it actually
# contains enough DIGITS to be a phone number — so "2 - 3 - 4 split" (numeric
# question content) is NOT mangled, while "+1 (415) 555-1234" is.
_PHONE_CANDIDATE = re.compile(r"(?<![\w@])(\+?\d[\d\s().\-]{6,}\d)(?![\w@])")
_LONG_DIGITS = re.compile(r"\b\d{9,}\b")  # card / national-id-ish runs
_MIN_PHONE_DIGITS = 7


def _redact_phone(match: re.Match) -> str:
    digits = sum(c.isdigit() for c in match.group(0))
    return "[phone]" if digits >= _MIN_PHONE_DIGITS else match.group(0)


def redact_pii(text: str | None) -> str | None:
    """Return text with emails/phones/long digit runs replaced by placeholders.

    Phone redaction requires a real phone-like digit count, so ordinary numeric
    content in questions (rep schemes, prices, measurements) is preserved.
    """
    if not text:
        return text
    text = _EMAIL.sub("[email]", text)
    text = _LONG_DIGITS.sub("[number]", text)
    text = _PHONE_CANDIDATE.sub(_redact_phone, text)
    return text


def has_pii(text: str | None) -> bool:
    if not text:
        return False
    if _EMAIL.search(text) or _LONG_DIGITS.search(text):
        return True
    return any(_redact_phone(m) == "[phone]" for m in _PHONE_CANDIDATE.finditer(text))
