"""Trust-calibrated agent permission ladder (Wave D).

One global approval setting is too blunt: auto-appending an approved UTM is far
lower risk than auto-answering a health question. Permissions are PER ACTION TYPE
on a ladder — recommend → draft → batch → auto — with a risk ceiling per action,
plus an anomaly pause kill-switch. Approval-by-default still holds: an action only
runs automatically when its level is 'auto', the creator opted in, automation isn't
paused, and (for DMs) the citation gate has passed.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from cci_core.agent_foundations import get_rules

# ladder, low → high autonomy
LEVELS = ["recommend", "draft", "batch", "auto"]
_RANK = {lvl: i for i, lvl in enumerate(LEVELS)}

# per-action risk → the HIGHEST autonomy a creator may grant it
RISK_CEILING = {
    "affiliate_inject": "auto",      # low risk: approved link + UTM
    "offer_cta": "auto",             # low risk
    "loop_close": "batch",           # medium: a value-first notify
    "draft_generate": "auto",        # creator still reviews the draft before posting
    "dm_reply": "batch",             # high: speaks in the creator's voice publicly
    "public_comment_reply": "batch",  # high
}
# conservative defaults if the creator hasn't set a preference
DEFAULT_LEVEL = {
    "affiliate_inject": "draft",
    "offer_cta": "draft",
    "loop_close": "draft",
    "draft_generate": "draft",
    "dm_reply": "draft",
    "public_comment_reply": "recommend",
}


def _ceil(action: str, level: str) -> str:
    """Clamp a requested level to the action's risk ceiling."""
    ceiling = RISK_CEILING.get(action, "draft")
    return level if _RANK.get(level, 0) <= _RANK[ceiling] else ceiling


def permission_for(session: Session, creator_id: str, action: str) -> str:
    """Effective permission level for an action (clamped to its risk ceiling)."""
    rules = get_rules(session, creator_id)
    configured = (rules.action_permissions or {}).get(action, DEFAULT_LEVEL.get(action, "recommend"))
    if configured not in LEVELS:
        configured = DEFAULT_LEVEL.get(action, "recommend")
    return _ceil(action, configured)


def set_permission(session: Session, creator_id: str, action: str, level: str) -> str:
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}")
    if action not in RISK_CEILING:
        raise ValueError(f"unknown action '{action}'")
    rules = get_rules(session, creator_id)
    perms = dict(rules.action_permissions or {})
    perms[action] = _ceil(action, level)
    rules.action_permissions = perms
    return perms[action]


def can_auto_execute(session: Session, creator_id: str, action: str) -> bool:
    """May this action run with NO human in the loop right now?

    Requires: level 'auto' (after ceiling), automation not paused. DM-type actions
    additionally require the per-intent opt-in + eval gate (checked by the caller).
    """
    rules = get_rules(session, creator_id)
    if rules.automation_paused:
        return False
    return permission_for(session, creator_id, action) == "auto"


def pause_automation(session: Session, creator_id: str, *, paused: bool = True) -> None:
    """Anomaly kill-switch — pause/resume all automated execution for a creator."""
    get_rules(session, creator_id).automation_paused = paused


def permission_summary(session: Session, creator_id: str) -> dict:
    rules = get_rules(session, creator_id)
    return {
        "automation_paused": rules.automation_paused,
        "actions": {a: {"level": permission_for(session, creator_id, a),
                        "ceiling": RISK_CEILING[a]} for a in RISK_CEILING},
    }
