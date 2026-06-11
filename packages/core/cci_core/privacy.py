"""Pseudonymisation helpers (GDPR).

Audience queries and comments are personal data if identifiable. We never store
raw commenter handles/IDs — only a salted hash, scoped per creator so the same
person cannot be correlated across creators.
"""
import hashlib
import hmac

from cci_core.config import get_settings


def pseudonymize(raw_identifier: str, creator_id: str) -> str:
    """Stable per-creator pseudonym for an audience member."""
    key = f"{get_settings().admin_token}:{creator_id}".encode()
    return hmac.new(key, raw_identifier.encode(), hashlib.sha256).hexdigest()[:32]
