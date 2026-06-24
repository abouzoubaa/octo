"""Transparent at-rest encryption for sensitive columns (e.g. OAuth tokens).

`EncryptedString` is a SQLAlchemy TypeDecorator: values are plaintext in Python
and ciphertext in the database. Keyed by `CCI_ENCRYPTION_KEY` (a Fernet key,
i.e. 32 url-safe-base64 bytes). If no key is configured the type passes through
unchanged (dev convenience) and logs a one-time warning — set a key in prod.

Generate a key:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import logging
from functools import lru_cache

from sqlalchemy import String, TypeDecorator

from cci_core.config import get_settings

log = logging.getLogger(__name__)

_PREFIX = "enc:v1:"  # marks ciphertext so we can decrypt only what we encrypted


@lru_cache
def _fernet():
    key = get_settings().encryption_key
    if not key:
        log.warning("CCI_ENCRYPTION_KEY is unset — sensitive columns are stored in "
                    "plaintext. Set a Fernet key before production.")
        return None
    from cryptography.fernet import Fernet

    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value: str | None) -> str | None:
    if value is None:
        return None
    f = _fernet()
    if f is None or value.startswith(_PREFIX):
        return value
    return _PREFIX + f.encrypt(value.encode()).decode()


def decrypt(value: str | None) -> str | None:
    if value is None or not value.startswith(_PREFIX):
        return value  # plaintext (no key configured when written) — pass through
    f = _fernet()
    if f is None:
        log.error("ciphertext present but no CCI_ENCRYPTION_KEY to decrypt it")
        return value
    return f.decrypt(value[len(_PREFIX):].encode()).decode()


class EncryptedString(TypeDecorator):
    """A String column whose value is encrypted at rest, transparent in Python."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):  # Python → DB
        return encrypt(value)

    def process_result_value(self, value, dialect):  # DB → Python
        return decrypt(value)
