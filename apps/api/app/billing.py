"""Billing domain helpers — subscription lookup, customer provisioning, and
the idempotent Stripe event applier used by the Celery worker.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app import stripe_client
from apps.api.app.db import (
    BillingPeriod,
    Plan,
    Subscription,
    SubscriptionStatus,
    User,
)

logger = logging.getLogger(__name__)


async def get_active_subscription(
    session: AsyncSession, user_id: uuid.UUID
) -> Subscription | None:
    stmt = (
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .where(
            Subscription.status.in_(
                [
                    SubscriptionStatus.active,
                    SubscriptionStatus.trialing,
                    SubscriptionStatus.past_due,
                ]
            )
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def ensure_stripe_customer(session: AsyncSession, user: User) -> str:
    if user.stripe_customer_id:
        return user.stripe_customer_id
    cid = await stripe_client.create_customer(
        email=user.email,
        name=f"{user.first_name} {user.last_name}",
        metadata={"user_id": str(user.id)},
    )
    user.stripe_customer_id = cid
    await session.commit()
    return cid


async def grant_free_subscription(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    plan_id: uuid.UUID,
    duration_days: int,
    admin_id: uuid.UUID,
    reason: str | None,
) -> Subscription:
    now = datetime.now(timezone.utc)
    sub = Subscription(
        user_id=user_id,
        plan_id=plan_id,
        status=SubscriptionStatus.active,
        billing_period=BillingPeriod.monthly,
        current_period_start=now,
        current_period_end=now + timedelta(days=duration_days),
        granted_by_admin_id=admin_id,
        granted_reason=reason,
    )
    session.add(sub)
    await session.commit()
    await session.refresh(sub)
    return sub


async def apply_stripe_subscription_event(
    session: AsyncSession, event
) -> None:
    """Idempotent upsert by ``stripe_subscription_id``.

    Out-of-order deliveries are dropped using the cached
    ``stripe_event_created_at``. Unknown customers or unknown price IDs are
    logged and skipped — we never raise into the Celery task body, because
    Stripe will redeliver and we want to swallow non-actionable state.
    """
    data = event["data"]["object"]
    sub_id = data["id"]
    customer_id = data.get("customer")
    user = (
        await session.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
    ).scalar_one_or_none()
    if not user:
        logger.warning(
            "stripe_subscription_user_not_found customer=%s sub=%s",
            customer_id,
            sub_id,
        )
        return

    existing = (
        await session.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == sub_id)
        )
    ).scalar_one_or_none()
    event_created = datetime.fromtimestamp(event["created"], tz=timezone.utc)
    if (
        existing
        and existing.stripe_event_created_at
        and existing.stripe_event_created_at >= event_created
    ):
        return

    status_map = {
        "active": SubscriptionStatus.active,
        "trialing": SubscriptionStatus.trialing,
        "past_due": SubscriptionStatus.past_due,
        "canceled": SubscriptionStatus.canceled,
        "incomplete": SubscriptionStatus.incomplete,
        "incomplete_expired": SubscriptionStatus.canceled,
    }
    new_status = status_map.get(data.get("status"), SubscriptionStatus.incomplete)

    items = data.get("items", {}).get("data", [])
    price_id = items[0]["price"]["id"] if items else None
    plan_q = select(Plan).where(
        (Plan.stripe_price_monthly_id == price_id)
        | (Plan.stripe_price_yearly_id == price_id)
    )
    plan = (await session.execute(plan_q)).scalar_one_or_none()
    if not plan:
        logger.warning(
            "stripe_subscription_plan_not_found price=%s sub=%s", price_id, sub_id
        )
        return

    period = (
        BillingPeriod.yearly
        if plan.stripe_price_yearly_id == price_id
        else BillingPeriod.monthly
    )
    period_start = (
        datetime.fromtimestamp(data["current_period_start"], tz=timezone.utc)
        if data.get("current_period_start")
        else None
    )
    period_end = (
        datetime.fromtimestamp(data["current_period_end"], tz=timezone.utc)
        if data.get("current_period_end")
        else None
    )
    canceled_at = (
        datetime.fromtimestamp(data["canceled_at"], tz=timezone.utc)
        if data.get("canceled_at")
        else None
    )

    if existing:
        existing.status = new_status
        existing.plan_id = plan.id
        existing.billing_period = period
        existing.stripe_event_created_at = event_created
        existing.current_period_start = period_start
        existing.current_period_end = period_end
        existing.canceled_at = canceled_at
    else:
        session.add(
            Subscription(
                user_id=user.id,
                plan_id=plan.id,
                status=new_status,
                billing_period=period,
                stripe_subscription_id=sub_id,
                stripe_customer_id=customer_id,
                stripe_event_created_at=event_created,
                current_period_start=period_start,
                current_period_end=period_end,
                canceled_at=canceled_at,
            )
        )
    await session.commit()
