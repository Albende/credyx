"""Celery tasks for Stripe webhook processing.

Idempotency is enforced upstream by the webhook route via Redis ``SETNX`` on
``stripe:evt:{event_id}``. This task dispatches on ``event_type`` and calls
into the domain helpers in ``apps.api.app.billing``.

The Celery worker runs sync; we use ``asyncio.run`` to bridge into the
async SQLAlchemy session. Each task invocation gets its own short-lived
event loop — the engine pool itself is module-level cached, so reconnects
are cheap.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from packages.ingestion.celery_app import celery_app

logger = logging.getLogger(__name__)

_SUBSCRIPTION_EVENTS = {
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}


async def _run_async(event_id: str, event_type: str, event_obj: dict[str, Any]) -> None:
    """Async body — imports live here to keep Celery import-time cheap."""
    from apps.api.app.billing import apply_stripe_subscription_event
    from apps.api.app.db import get_sessionmaker

    sm = get_sessionmaker()

    # Reconstruct a minimal Stripe-event-shaped dict so apply_*_event sees
    # the same access pattern it would from the SDK.
    synthetic_event = {
        "id": event_id,
        "type": event_type,
        "created": int(event_obj.get("created") or time.time()),
        "data": {"object": event_obj},
    }

    async with sm() as session:
        if event_type in _SUBSCRIPTION_EVENTS:
            await apply_stripe_subscription_event(session, synthetic_event)
        elif event_type == "checkout.session.completed":
            # Customer/subscription linkage is owned by ensure_stripe_customer
            # at checkout creation; the subsequent customer.subscription.created
            # event applies the actual subscription row. Nothing else to do.
            logger.info(
                "stripe_checkout_completed user=%s sub=%s",
                event_obj.get("client_reference_id"),
                event_obj.get("subscription"),
            )
        elif event_type == "invoice.payment_succeeded":
            sub_id = event_obj.get("subscription")
            logger.info("stripe_invoice_paid sub=%s", sub_id)
        elif event_type == "invoice.payment_failed":
            sub_id = event_obj.get("subscription")
            logger.warning("stripe_invoice_failed sub=%s", sub_id)
        else:
            logger.debug("stripe_event_ignored type=%s", event_type)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def process_stripe_event(
    self, event_id: str, event_type: str, event_obj: dict[str, Any]
) -> None:
    """Handle a Stripe webhook event by id + type + data object.

    Fired once per event_id (Redis SETNX upstream). Failures are retried up
    to ``max_retries`` times with a 30s delay; after that we let the task
    fail visibly so it shows up in Celery's failure queue.
    """
    logger.info(
        "stripe_event_received event_id=%s type=%s", event_id, event_type
    )
    try:
        asyncio.run(_run_async(event_id, event_type, event_obj))
    except Exception as exc:
        logger.exception(
            "stripe_event_failed event_id=%s type=%s: %s", event_id, event_type, exc
        )
        raise self.retry(exc=exc) from exc
