"""Team & role-based access (v3) + audit trail + API keys.

Owner / creator / analytics-only VA / contractor roles so Sift scales from solo
to team, with capability gating and an audit trail.
"""
from __future__ import annotations

import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from cci_core.models import ROLE_CAPABILITIES, ApiKey, AuditLog, TeamMember, TeamRole


# ----------------------------------------------------------------- team & roles


def add_member(session: Session, creator_id: str, email: str, role: TeamRole) -> TeamMember:
    existing = session.scalar(
        select(TeamMember).where(TeamMember.creator_id == creator_id,
                                 TeamMember.email == email))
    if existing:
        existing.role = role
        session.flush()
        return existing
    member = TeamMember(creator_id=creator_id, email=email, role=role)
    session.add(member)
    session.flush()
    return member


def has_capability(session: Session, creator_id: str, email: str, capability: str) -> bool:
    """Does this team member's role grant the capability?"""
    member = session.scalar(
        select(TeamMember).where(TeamMember.creator_id == creator_id,
                                 TeamMember.email == email))
    if member is None:
        return False
    return capability in ROLE_CAPABILITIES.get(member.role, set())


def audit(session: Session, creator_id: str, actor: str, action: str,
          detail: dict | None = None) -> None:
    session.add(AuditLog(creator_id=creator_id, actor=actor, action=action, detail=detail))


# --------------------------------------------------------------------- API keys


def mint_api_key(session: Session, creator_id: str, name: str,
                 scopes: list[str] | None = None) -> tuple[ApiKey, str]:
    """Create an API key. Returns (record, full_key); the full key is shown ONCE.

    The prefix is an INDEPENDENT non-secret identifier (not a slice of the secret),
    so storing/indexing/logging it never leaks secret material.
    """
    prefix = secrets.token_hex(4)  # non-secret lookup id, independent of the secret
    secret = secrets.token_urlsafe(24)
    full = f"sift_{prefix}_{secret}"
    key_hash = hashlib.sha256(full.encode()).hexdigest()
    record = ApiKey(creator_id=creator_id, name=name, prefix=prefix,
                    key_hash=key_hash, scopes=scopes or [])
    session.add(record)
    session.flush()
    return record, full


def verify_api_key(session: Session, full_key: str) -> ApiKey | None:
    """Look up + verify an API key by its hash. None if unknown or revoked."""
    if not full_key or not full_key.startswith("sift_"):
        return None
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    record = session.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
    if record is None or record.revoked:
        return None
    return record


def revoke_api_key(session: Session, key_id: str) -> bool:
    record = session.get(ApiKey, key_id)
    if record is None:
        return False
    record.revoked = True
    session.flush()  # ensure the revocation persists even without an outer commit
    return True
