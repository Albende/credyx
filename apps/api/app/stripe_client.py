"""Thin async wrapper around the sync `stripe` SDK.

All blocking calls go through ``asyncio.to_thread`` so the FastAPI event loop
keeps spinning. Stripe is initialized lazily once per process — pulling
``stripe_api_key`` from settings on first use.
"""
from __future__ import annotations

import asyncio
from typing import Any

import stripe

from apps.api.app.config import get_settings

_initialized = False


def _init() -> None:
    global _initialized
    if _initialized:
        return
    s = get_settings()
    if s.stripe_api_key:
        stripe.api_key = s.stripe_api_key
    _initialized = True


async def create_or_update_product(plan) -> str:
    """Return product_id. Reuses ``plan.stripe_product_id`` if set."""
    _init()

    def _do() -> str:
        if plan.stripe_product_id:
            stripe.Product.modify(
                plan.stripe_product_id,
                name=plan.name,
                description=plan.description or "",
                active=plan.is_active,
            )
            return plan.stripe_product_id
        prod = stripe.Product.create(
            name=plan.name,
            description=plan.description or "",
            metadata={"plan_slug": plan.slug},
        )
        return prod.id

    return await asyncio.to_thread(_do)


async def create_or_update_price(
    product_id: str,
    amount_cents: int,
    currency: str,
    interval: str,
    existing_id: str | None,
) -> str:
    """Stripe Prices are immutable. If existing_id matches amount/interval, keep it.
    Otherwise create new and archive old.
    """
    _init()

    def _do() -> str:
        if existing_id:
            try:
                p = stripe.Price.retrieve(existing_id)
                if (
                    p.unit_amount == amount_cents
                    and p.currency == currency
                    and p.recurring
                    and p.recurring.interval == interval
                ):
                    return existing_id
                stripe.Price.modify(existing_id, active=False)
            except stripe.error.InvalidRequestError:
                pass
        new = stripe.Price.create(
            product=product_id,
            unit_amount=amount_cents,
            currency=currency,
            recurring={"interval": interval},
        )
        return new.id

    return await asyncio.to_thread(_do)


async def create_checkout_session(
    *,
    customer_id: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    user_id: str,
    plan_slug: str,
) -> str:
    _init()

    def _do() -> str:
        sess = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=user_id,
            metadata={"user_id": user_id, "plan_slug": plan_slug},
        )
        return sess.url

    return await asyncio.to_thread(_do)


async def create_billing_portal_session(*, customer_id: str, return_url: str) -> str:
    _init()

    def _do() -> str:
        sess = stripe.billing_portal.Session.create(
            customer=customer_id, return_url=return_url
        )
        return sess.url

    return await asyncio.to_thread(_do)


async def create_customer(*, email: str, name: str, metadata: dict) -> str:
    _init()

    def _do() -> str:
        c = stripe.Customer.create(email=email, name=name, metadata=metadata)
        return c.id

    return await asyncio.to_thread(_do)


async def cancel_subscription(subscription_id: str, *, at_period_end: bool = True) -> dict:
    _init()

    def _do() -> dict:
        return stripe.Subscription.modify(
            subscription_id, cancel_at_period_end=at_period_end
        )

    return await asyncio.to_thread(_do)


def construct_event(payload: bytes, sig_header: str) -> Any:
    """Verify signature on raw body. Raises on invalid sig."""
    s = get_settings()
    return stripe.Webhook.construct_event(payload, sig_header, s.stripe_webhook_secret)
