"""Plan-based feature flag + per-window usage quota dependencies.

``requires_feature`` blocks the request when the user's active subscription
plan does not enable the named feature. ``consume_quota`` increments a Redis
counter scoped to (user, metric, window) and returns 429 once the limit is
exceeded.

If the user has no active subscription we fall back to ``FREE_PLAN_*``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status

from apps.api.app.auth import current_user
from apps.api.app.db import Subscription, SubscriptionStatus, UsageWindow, User, UserRole


FREE_PLAN_FEATURES: dict[str, bool] = {
    "risk_analysis": False,
    "pdf_extraction": False,
    "bulk_export": False,
    "api_access": False,
}

FREE_PLAN_LIMITS: dict[str, int] = {
    "searches_per_day": 10,
    "company_lookups_per_day": 5,
    "risk_analyses_per_month": 0,
    "financial_lookups_per_month": 5,
}


def _active_subscription(user: User) -> Subscription | None:
    for sub in user.subscriptions:
        if sub.status in (
            SubscriptionStatus.active,
            SubscriptionStatus.trialing,
            SubscriptionStatus.past_due,
        ):
            return sub
    return None


def plan_features(user: User) -> dict:
    sub = _active_subscription(user)
    if sub and sub.plan:
        return {**FREE_PLAN_FEATURES, **(sub.plan.features or {})}
    return dict(FREE_PLAN_FEATURES)


def plan_limits(user: User) -> dict:
    sub = _active_subscription(user)
    if sub and sub.plan:
        return {**FREE_PLAN_LIMITS, **(sub.plan.limits or {})}
    return dict(FREE_PLAN_LIMITS)


def plan_slug(user: User) -> str | None:
    sub = _active_subscription(user)
    if sub and sub.plan:
        return sub.plan.slug
    return None


def requires_feature(key: str):
    async def dep(user: User = Depends(current_user)) -> None:
        if user.role == UserRole.admin:
            return
        if not plan_features(user).get(key, False):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "feature_unavailable",
                    "feature": key,
                    "upgrade_url": "/pricing",
                },
            )

    return dep


def _bucket(window: UsageWindow) -> str:
    now = datetime.now(timezone.utc)
    if window == UsageWindow.day:
        return now.strftime("%Y-%m-%d")
    return now.strftime("%Y-%m")


def _ttl(window: UsageWindow) -> int:
    if window == UsageWindow.day:
        return 26 * 3600
    return 32 * 24 * 3600


async def _get_redis_safe():
    try:
        from apps.api.app.auth import _get_redis  # type: ignore[attr-defined]

        return await _get_redis()
    except Exception:
        return None


def consume_quota(metric: str, window: UsageWindow, amount: int = 1):
    async def dep(user: User = Depends(current_user)) -> None:
        if user.role == UserRole.admin:
            return
        limits = plan_limits(user)
        limit = limits.get(f"{metric}_per_{window.value}")
        # None means unlimited.
        if limit is None:
            return
        # 0 means explicitly disabled — surface as quota_exceeded without
        # touching Redis so users on the free plan get a deterministic 429.
        if limit <= 0:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "quota_exceeded",
                    "metric": metric,
                    "limit": limit,
                    "window": window.value,
                },
            )
        r = await _get_redis_safe()
        if r is None:
            return
        key = f"usage:{user.id}:{metric}:{window.value}:{_bucket(window)}"
        try:
            new_val = await r.incrby(key, amount)
            if new_val == amount:
                await r.expire(key, _ttl(window))
        except Exception:
            return
        if new_val > limit:
            try:
                await r.decrby(key, amount)
            except Exception:
                pass
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "quota_exceeded",
                    "metric": metric,
                    "limit": limit,
                    "window": window.value,
                },
            )

    return dep
