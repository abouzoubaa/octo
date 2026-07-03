"""Pseudonymisation helpers (GDPR).

Audience queries and comments are personal data if identifiable. We never store
raw commenter handles/IDs — only a salted hash, scoped per creator so the same
person cannot be correlated across creators.
"""
import hashlib
import hmac

from cci_core.config import get_settings


def pseudonymize(raw_identifier: str, creator_id: str) -> str:
    """Stable per-creator pseudonym for an audience member.

    Keyed on a dedicated `pseudonym_secret` so audience identity isn't tied to the
    operator auth token — rotating the admin token must not break GDPR pseudonym
    continuity, nor should leaking it let an attacker recompute pseudonyms. Falls
    back to admin_token when unset, preserving existing pseudonyms.
    """
    s = get_settings()
    secret = s.pseudonym_secret or s.admin_token
    key = f"{secret}:{creator_id}".encode()
    return hmac.new(key, raw_identifier.encode(), hashlib.sha256).hexdigest()[:32]
