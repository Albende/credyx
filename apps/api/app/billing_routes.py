"""Customer-facing billing endpoints.

These are deliberately thin — they marshal request → Stripe via the client
and return URLs / DTOs. Webhook-driven state changes flow through
``apply_stripe_subscription_event`` from the Celery worker.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.app import stripe_client
from apps.api.app.auth import current_user
from apps.api.app.billing import ensure_stripe_customer, get_active_subscription
from apps.api.app.config import get_settings
from apps.api.app.db import (
    BillingPeriod,
    Plan,
    Subscription,
    SubscriptionStatus,
    User,
    get_session,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/billing", tags=["billing"])


class PlanPublic(BaseModel):
    slug: str
    name: str
    description: str | None
    price_monthly_cents: int
    price_yearly_cents: int
    currency: str
    features: dict
    limits: dict
    is_active: bool


class SubscriptionPublic(BaseModel):
    id: uuid.UUID
    plan_slug: str
    plan_name: str
    status: str
    billing_period: str
    current_period_start: datetime | None
    current_period_end: datetime | None
    canceled_at: datetime | None


class CheckoutBody(BaseModel):
    plan_slug: str = Field(..., min_length=1)
    billing_period: str = Field(..., pattern="^(monthly|yearly)$")


class CancelBody(BaseModel):
    subscription_id: uuid.UUID


class UrlResponse(BaseModel):
    checkout_url: str | None = None
    portal_url: str | None = None


@router.get("/plans", response_model=list[PlanPublic])
async def list_plans(session: AsyncSession = Depends(get_session)) -> list[PlanPublic]:
    rows = (
        await session.execute(
            select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.price_monthly_cents)
        )
    ).scalars().all()
    return [
        PlanPublic(
            slug=p.slug,
            name=p.name,
            description=p.description,
            price_monthly_cents=p.price_monthly_cents,
            price_yearly_cents=p.price_yearly_cents,
            currency=p.currency,
            features=p.features or {},
            limits=p.limits or {},
            is_active=p.is_active,
        )
        for p in rows
    ]


@router.get("/me/subscription", response_model=SubscriptionPublic | None)
async def my_subscription(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> SubscriptionPublic | None:
    sub = await get_active_subscription(session, user.id)
    if not sub:
        return None
    plan = (await session.execute(select(Plan).where(Plan.id == sub.plan_id))).scalar_one()
    return SubscriptionPublic(
        id=sub.id,
        plan_slug=plan.slug,
        plan_name=plan.name,
        status=sub.status.value if hasattr(sub.status, "value") else str(sub.status),
        billing_period=sub.billing_period.value
        if hasattr(sub.billing_period, "value")
        else str(sub.billing_period),
        current_period_start=sub.current_period_start,
        current_period_end=sub.current_period_end,
        canceled_at=sub.canceled_at,
    )


@router.post("/checkout-session", response_model=UrlResponse)
async def create_checkout_session(
    body: CheckoutBody,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> UrlResponse:
    settings = get_settings()
    plan = (
        await session.execute(select(Plan).where(Plan.slug == body.plan_slug))
    ).scalar_one_or_none()
    if not plan or not plan.is_active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "plan_not_found")
    price_id = (
        plan.stripe_price_monthly_id
        if body.billing_period == "monthly"
        else plan.stripe_price_yearly_id
    )
    if not price_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "plan_not_synced_to_stripe"
        )
    customer_id = await ensure_stripe_customer(session, user)
    url = await stripe_client.create_checkout_session(
        customer_id=customer_id,
        price_id=price_id,
        success_url=settings.billing_success_url,
        cancel_url=settings.billing_cancel_url,
        user_id=str(user.id),
        plan_slug=plan.slug,
    )
    return UrlResponse(checkout_url=url)


@router.post("/portal-session", response_model=UrlResponse)
async def create_portal_session(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> UrlResponse:
    settings = get_settings()
    customer_id = await ensure_stripe_customer(session, user)
    url = await stripe_client.create_billing_portal_session(
        customer_id=customer_id,
        return_url=settings.billing_success_url,
    )
    return UrlResponse(portal_url=url)


@router.post("/cancel")
async def cancel_subscription(
    body: CancelBody,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    sub = (
        await session.execute(
            select(Subscription).where(Subscription.id == body.subscription_id)
        )
    ).scalar_one_or_none()
    if not sub or sub.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "subscription_not_found")
    if not sub.stripe_subscription_id:
        sub.status = SubscriptionStatus.canceled
        sub.canceled_at = datetime.now(timezone.utc)
        await session.commit()
        return {"canceled": True, "via": "local"}
    await stripe_client.cancel_subscription(
        sub.stripe_subscription_id, at_period_end=True
    )
    sub.canceled_at = datetime.now(timezone.utc)
    await session.commit()
    return {"canceled": True, "via": "stripe", "at_period_end": True}
