"""Stripe webhook receiver.

Signature verification happens on the raw body bytes (Stripe's payload is
signed exactly, so calling ``await request.json()`` first would corrupt the
HMAC). Event dedup uses Redis ``SETNX`` keyed by ``stripe:evt:{id}`` with a
7-day TTL — covers retries from Stripe's exponential backoff.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, status

from apps.api.app import stripe_client
from apps.api.app.rate_limit import get_limiter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhooks"])

_DEDUP_TTL_SECONDS = 7 * 24 * 3600


@router.post("/api/webhooks/stripe")
async def stripe_webhook(request: Request) -> dict:
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    if not sig:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing_signature")
    try:
        event = stripe_client.construct_event(payload, sig)
    except Exception as exc:
        logger.warning("stripe_webhook_signature_invalid: %s", exc)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_signature") from exc

    event_id = event["id"]
    event_type = event["type"]

    try:
        limiter = await get_limiter()
        was_set = await limiter.redis.set(
            f"stripe:evt:{event_id}", "1", ex=_DEDUP_TTL_SECONDS, nx=True
        )
        if not was_set:
            logger.info("stripe_webhook_dedup event_id=%s", event_id)
            return {"received": True, "dedup": True}
    except Exception as exc:
        logger.warning("stripe_webhook_redis_unavailable: %s — processing anyway", exc)

    try:
        from packages.billing.tasks import process_stripe_event

        process_stripe_event.delay(event_id, event_type, dict(event["data"]["object"]))
    except Exception as exc:
        logger.exception("stripe_webhook_enqueue_failed event_id=%s: %s", event_id, exc)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "enqueue_failed"
        ) from exc

    return {"received": True}
