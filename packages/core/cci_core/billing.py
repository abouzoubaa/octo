"""Subscriptions: plan-based feature gating + usage quotas + a billing provider.

Plans (plan §13): free → creator (~$49–99) → pro (~$149–299). Features and monthly
quotas are declared per plan; gating is a single assert_feature/check_quota call.
The billing provider is a thin interface (Stripe behind it) with an offline fake so
the whole flow is testable without a Stripe account.
"""
from __future__ import annotations

import hmac
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cci_core.config import get_settings
from cci_core.models import Event, Plan, Subscription

# Feature → minimum plan that includes it. Higher plans inherit lower-plan features.
PLAN_RANK = {Plan.free: 0, Plan.creator: 1, Plan.pro: 2}

FEATURE_MIN_PLAN: dict[str, Plan] = {
    # creator tier
    "radar": Plan.creator,
    "briefing": Plan.creator,
    "answer_card": Plan.creator,
    "affiliate_mapping": Plan.creator,
    "email_capture": Plan.creator,
    # pro tier
    "comment_to_dm": Plan.pro,
    "draft_generator": Plan.pro,
    "sponsor_reports": Plan.pro,
    "storefront": Plan.pro,
    "repurposing": Plan.pro,
    "multi_platform": Plan.pro,
}

# Monthly quotas per plan (None = unlimited). Metric names match event kinds / counters.
PLAN_QUOTAS: dict[Plan, dict[str, int | None]] = {
    Plan.free: {"drafts": 0, "dm_sent": 0},
    Plan.creator: {"drafts": 20, "dm_sent": 0},
    Plan.pro: {"drafts": None, "dm_sent": None},
}


class PlanError(Exception):
    """Raised when a creator's plan doesn't permit an action."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code  # "upgrade_required" | "quota_exceeded"


def get_subscription(session: Session, creator_id: str) -> Subscription:
    sub = session.get(Subscription, creator_id)
    if sub is None:
        sub = Subscription(creator_id=creator_id, plan=Plan.free)
        session.add(sub)
        session.flush()
    return sub


def plan_for(session: Session, creator_id: str) -> Plan:
    return get_subscription(session, creator_id).plan


def has_feature(session: Session, creator_id: str, feature: str) -> bool:
    needed = FEATURE_MIN_PLAN.get(feature)
    if needed is None:
        return True  # ungated
    return PLAN_RANK[plan_for(session, creator_id)] >= PLAN_RANK[needed]


def assert_feature(session: Session, creator_id: str, feature: str) -> None:
    if not has_feature(session, creator_id, feature):
        needed = FEATURE_MIN_PLAN[feature]
        raise PlanError(f"'{feature}' requires the {needed.value} plan",
                        code="upgrade_required")


def _month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def usage_this_month(session: Session, creator_id: str, metric: str) -> int:
    return session.scalar(
        select(func.count(Event.id)).where(
            Event.creator_id == creator_id, Event.kind == metric,
            Event.ts >= _month_start())
    ) or 0


def check_quota(session: Session, creator_id: str, metric: str) -> None:
    """Raise PlanError if the creator is at/over their monthly quota for `metric`.

    Locks the subscription row (SELECT … FOR UPDATE) so two concurrent requests
    can't both pass the check and overrun the quota — the second blocks until the
    first commits its usage event.
    """
    sub = session.get(Subscription, creator_id)
    if sub is None:
        sub = get_subscription(session, creator_id)
    else:
        # take a row lock to serialize concurrent quota checks for this creator
        session.refresh(sub, with_for_update=True)
    quota = PLAN_QUOTAS.get(sub.plan, {}).get(metric)
    if quota is None:
        return  # unlimited
    if usage_this_month(session, creator_id, metric) >= quota:
        raise PlanError(f"monthly '{metric}' quota ({quota}) reached — upgrade for more",
                        code="quota_exceeded")


def apply_subscription_event(session: Session, creator_id: str, *, plan: Plan,
                             status: str = "active", customer_id: str | None = None,
                             subscription_id: str | None = None,
                             period_end: datetime | None = None) -> Subscription:
    """Idempotently apply a billing state change (from a webhook or manual set)."""
    sub = get_subscription(session, creator_id)
    sub.plan = plan
    sub.status = status
    if customer_id:
        sub.stripe_customer_id = customer_id
    if subscription_id:
        sub.stripe_subscription_id = subscription_id
    if period_end:
        sub.current_period_end = period_end
    sub.updated_at = datetime.now(timezone.utc)
    return sub


# --------------------------------------------------------------- billing provider


class BillingProvider(ABC):
    name = "billing"

    @abstractmethod
    def create_checkout(self, creator_id: str, plan: Plan, success_url: str) -> str:
        """Return a checkout URL for the creator to subscribe to `plan`."""

    @abstractmethod
    def parse_webhook(self, raw_body: bytes, signature: str | None) -> dict | None:
        """Verify + normalise a provider webhook from the RAW request bytes into
        {creator_id, plan, status} — or None if the signature is invalid/unparseable.
        Implementations MUST authenticate before trusting the body."""


class FakeBilling(BillingProvider):
    """Offline billing for dev/tests. The webhook requires a shared secret when one
    is configured (CCI_STRIPE_WEBHOOK_SECRET); without a secret it only works in
    debug mode (the route refuses the fake provider in production)."""

    name = "fake"

    def create_checkout(self, creator_id: str, plan: Plan, success_url: str) -> str:
        return f"{success_url}?fake_checkout=1&creator={creator_id}&plan={plan.value}"

    def parse_webhook(self, raw_body: bytes, signature: str | None) -> dict | None:
        import json

        secret = get_settings().stripe_webhook_secret
        if secret and not (signature and hmac.compare_digest(signature, secret)):
            return None  # wrong/absent shared secret
        try:
            payload = json.loads(raw_body or b"{}")
        except (ValueError, TypeError):
            return None
        if "creator_id" not in payload or "plan" not in payload:
            return None
        return {"creator_id": payload["creator_id"], "plan": Plan(payload["plan"]),
                "status": payload.get("status", "active")}


class StripeBilling(BillingProvider):
    """Stripe-backed billing. Verifies the webhook signature over the RAW body via
    stripe.Webhook.construct_event before trusting any field."""

    name = "stripe"

    def __init__(self, api_key: str, price_ids: dict[str, str], webhook_secret: str):
        self.api_key = api_key
        self.price_ids = price_ids
        self.webhook_secret = webhook_secret

    def create_checkout(self, creator_id: str, plan: Plan, success_url: str) -> str:
        import stripe  # lazy

        stripe.api_key = self.api_key
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": self.price_ids[plan.value], "quantity": 1}],
            success_url=success_url,
            client_reference_id=creator_id,
            metadata={"creator_id": creator_id, "plan": plan.value},
        )
        return session.url

    def parse_webhook(self, raw_body: bytes, signature: str | None) -> dict | None:
        import stripe

        if not self.webhook_secret or not signature:
            return None
        try:
            event = stripe.Webhook.construct_event(raw_body, signature, self.webhook_secret)
        except Exception:  # noqa: BLE001 — invalid signature / malformed
            return None
        meta = event["data"]["object"].get("metadata", {})
        if not meta.get("creator_id"):
            return None
        return {"creator_id": meta["creator_id"], "plan": Plan(meta.get("plan", "creator")),
                "status": "active"}


def get_billing_provider() -> BillingProvider:
    s = get_settings()
    if s.billing_provider == "stripe" and s.stripe_api_key:
        return StripeBilling(s.stripe_api_key, s.stripe_price_ids, s.stripe_webhook_secret)
    return FakeBilling()
