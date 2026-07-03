"""Billing API: subscription status, checkout, plan changes, and the provider webhook.

Admin-scoped except the webhook (provider-authenticated by signature). Plan changes
flow through apply_subscription_event so manual and webhook paths stay consistent.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from cci_api.deps import require_admin
from cci_core.billing import (
    PLAN_QUOTAS,
    apply_subscription_event,
    get_billing_provider,
    get_subscription,
    usage_this_month,
)
from cci_core.config import get_settings
from cci_core.db import get_db
from cci_core.models import Plan

log = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])
admin_router = APIRouter(prefix="/billing", tags=["billing"],
                         dependencies=[Depends(require_admin)])


@admin_router.get("/creators/{creator_id}/subscription")
def subscription(creator_id: str, db: Session = Depends(get_db)) -> dict:
    from cci_core.billing import PLAN_COST_CAP_CENTS
    from cci_core.cost import monthly_cost_cents

    sub = get_subscription(db, creator_id)
    quotas = PLAN_QUOTAS.get(sub.plan, {})
    return {
        "plan": sub.plan.value, "status": sub.status,
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "usage": {m: {"used": usage_this_month(db, creator_id, m), "quota": q}
                  for m, q in quotas.items()},
        "ai_cost": {"used_cents": monthly_cost_cents(db, creator_id),
                    "cap_cents": PLAN_COST_CAP_CENTS.get(sub.plan)},
    }


class CheckoutIn(BaseModel):
    plan: str  # creator | pro


@admin_router.post("/creators/{creator_id}/checkout")
def checkout(creator_id: str, body: CheckoutIn, db: Session = Depends(get_db)) -> dict:
    try:
        plan = Plan(body.plan)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"invalid plan '{body.plan}'")
    success_url = f"{get_settings().public_base_url.rstrip('/')}/studio/{creator_id}"
    url = get_billing_provider().create_checkout(creator_id, plan, success_url)
    return {"checkout_url": url}


class SetPlanIn(BaseModel):
    plan: str
    status: str = "active"


@admin_router.put("/creators/{creator_id}/plan")
def set_plan(creator_id: str, body: SetPlanIn, db: Session = Depends(get_db)) -> dict:
    """Manual plan set (paid pilots / support). Webhooks use the same path."""
    try:
        plan = Plan(body.plan)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"invalid plan '{body.plan}'")
    sub = apply_subscription_event(db, creator_id, plan=plan, status=body.status)
    return {"plan": sub.plan.value, "status": sub.status}


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)) -> dict:
    """Provider subscription-lifecycle webhook — authenticated by signature over the
    RAW body. The fake provider is refused in production (it can't authenticate)."""
    s = get_settings()
    if s.billing_provider == "fake" and not s.debug:
        raise HTTPException(status_code=403, detail="fake billing webhook disabled in production")
    raw = await request.body()
    signature = request.headers.get("stripe-signature")
    event = get_billing_provider().parse_webhook(raw, signature)
    if event is None:
        return {"received": True, "applied": False}  # bad signature / unparseable
    apply_subscription_event(db, event["creator_id"], plan=event["plan"],
                             status=event.get("status", "active"))
    return {"received": True, "applied": True}
