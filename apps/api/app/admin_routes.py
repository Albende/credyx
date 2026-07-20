"""Admin API — every route requires ``require_admin``.

Side-effecting endpoints write an ``AuditLog`` row alongside the change so
that grants, demotions, plan edits and Stripe syncs are all reconstructible.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.app import stripe_client
from apps.api.app.auth import require_admin
from apps.api.app.billing import grant_free_subscription
from apps.api.app.config import get_settings
from apps.api.app.db import (
    AuditLog,
    BillingPeriod,
    Plan,
    Subscription,
    SubscriptionStatus,
    User,
    UserRole,
    get_session,
)
from apps.api.app.rate_limit import get_limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- Pydantic schemas -------------------------------------------------------


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    role: str
    email_verified: bool
    stripe_customer_id: str | None
    created_at: datetime
    active_plan_slug: str | None = None


class UserDetail(UserOut):
    subscriptions: list[dict] = []


class UserUpdate(BaseModel):
    role: str | None = None
    email_verified: bool | None = None
    first_name: str | None = None
    last_name: str | None = None


class GrantBody(BaseModel):
    plan_slug: str
    duration_days: int = Field(..., gt=0, le=3650)
    reason: str | None = None


class PlanIn(BaseModel):
    slug: str
    name: str
    description: str | None = None
    price_monthly_cents: int = 0
    price_yearly_cents: int = 0
    currency: str = "usd"
    features: dict = {}
    limits: dict = {}
    is_active: bool = True


class PlanPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    price_monthly_cents: int | None = None
    price_yearly_cents: int | None = None
    currency: str | None = None
    features: dict | None = None
    limits: dict | None = None
    is_active: bool | None = None


class PlanOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    price_monthly_cents: int
    price_yearly_cents: int
    currency: str
    features: dict
    limits: dict
    stripe_product_id: str | None
    stripe_price_monthly_id: str | None
    stripe_price_yearly_id: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SubscriptionOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_email: str | None
    plan_slug: str | None
    status: str
    billing_period: str
    current_period_start: datetime | None
    current_period_end: datetime | None
    canceled_at: datetime | None
    stripe_subscription_id: str | None
    created_at: datetime


class AuditOut(BaseModel):
    id: int
    action: str
    target_type: str
    target_id: str | None
    user_id: uuid.UUID | None
    admin_id: uuid.UUID | None
    payload: dict
    created_at: datetime


# --- Helpers ----------------------------------------------------------------


async def _audit(
    session: AsyncSession,
    *,
    admin: User,
    action: str,
    target_type: str,
    target_id: str | None,
    payload: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    entry = AuditLog(
        admin_id=admin.id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        payload=payload or {},
        ip=(request.client.host if (request and request.client) else None),
        user_agent=(request.headers.get("user-agent") if request else None),
    )
    session.add(entry)
    await session.commit()


def _user_out(u: User) -> UserOut:
    active = next(
        (
            s
            for s in (u.subscriptions or [])
            if s.status
            in (
                SubscriptionStatus.active,
                SubscriptionStatus.trialing,
                SubscriptionStatus.past_due,
            )
        ),
        None,
    )
    return UserOut(
        id=u.id,
        email=u.email,
        first_name=u.first_name,
        last_name=u.last_name,
        role=u.role.value if hasattr(u.role, "value") else str(u.role),
        email_verified=u.email_verified_at is not None,
        stripe_customer_id=u.stripe_customer_id,
        created_at=u.created_at,
        active_plan_slug=(active.plan.slug if active and active.plan else None),
    )


def _plan_out(p: Plan) -> PlanOut:
    return PlanOut(
        id=p.id,
        slug=p.slug,
        name=p.name,
        description=p.description,
        price_monthly_cents=p.price_monthly_cents,
        price_yearly_cents=p.price_yearly_cents,
        currency=p.currency,
        features=p.features or {},
        limits=p.limits or {},
        stripe_product_id=p.stripe_product_id,
        stripe_price_monthly_id=p.stripe_price_monthly_id,
        stripe_price_yearly_id=p.stripe_price_yearly_id,
        is_active=p.is_active,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


# --- Users ------------------------------------------------------------------


@router.get("/users", response_model=dict)
async def list_users(
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    stmt = select(User).options(
        selectinload(User.subscriptions).selectinload(Subscription.plan)
    )
    count_stmt = select(func.count(User.id))
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(User.email).like(like),
                func.lower(User.first_name).like(like),
                func.lower(User.last_name).like(like),
            )
        )
        count_stmt = count_stmt.where(
            or_(
                func.lower(User.email).like(like),
                func.lower(User.first_name).like(like),
                func.lower(User.last_name).like(like),
            )
        )
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(User.created_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).scalars().unique().all()
    return {
        "users": [_user_out(u).model_dump() for u in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/users/{user_id}", response_model=UserDetail)
async def get_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> UserDetail:
    user = (
        await session.execute(
            select(User)
            .options(
                selectinload(User.subscriptions).selectinload(Subscription.plan)
            )
            .where(User.id == user_id)
        )
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")
    base = _user_out(user)
    subs = [
        {
            "id": str(s.id),
            "plan_slug": s.plan.slug if s.plan else None,
            "status": s.status.value if hasattr(s.status, "value") else str(s.status),
            "billing_period": s.billing_period.value
            if hasattr(s.billing_period, "value")
            else str(s.billing_period),
            "current_period_start": s.current_period_start,
            "current_period_end": s.current_period_end,
            "canceled_at": s.canceled_at,
            "stripe_subscription_id": s.stripe_subscription_id,
        }
        for s in (user.subscriptions or [])
    ]
    return UserDetail(**base.model_dump(), subscriptions=subs)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    user = (
        await session.execute(
            select(User)
            .options(
                selectinload(User.subscriptions).selectinload(Subscription.plan)
            )
            .where(User.id == user_id)
        )
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")

    changes: dict[str, Any] = {}
    if body.role is not None and body.role != (
        user.role.value if hasattr(user.role, "value") else str(user.role)
    ):
        if body.role not in {"user", "admin"}:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_role")
        if user.role == UserRole.admin and body.role == "user":
            admin_count = (
                await session.execute(
                    select(func.count(User.id)).where(User.role == UserRole.admin)
                )
            ).scalar_one()
            if admin_count <= 1:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "cannot_demote_last_admin"
                )
        changes["role"] = body.role
        user.role = UserRole(body.role)
    if body.email_verified is not None:
        new_val = (
            datetime.now(timezone.utc) if body.email_verified else None
        )
        if (user.email_verified_at is None) != (new_val is None):
            changes["email_verified"] = body.email_verified
            user.email_verified_at = new_val
    if body.first_name is not None and body.first_name != user.first_name:
        changes["first_name"] = body.first_name
        user.first_name = body.first_name
    if body.last_name is not None and body.last_name != user.last_name:
        changes["last_name"] = body.last_name
        user.last_name = body.last_name

    if changes:
        await session.commit()
        await _audit(
            session,
            admin=admin,
            action="user.update",
            target_type="user",
            target_id=str(user.id),
            payload=changes,
            request=request,
        )
    return _user_out(user)


@router.post("/users/{user_id}/grant-plan", response_model=SubscriptionOut)
async def admin_grant_plan(
    user_id: uuid.UUID,
    body: GrantBody,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> SubscriptionOut:
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")
    plan = (
        await session.execute(select(Plan).where(Plan.slug == body.plan_slug))
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "plan_not_found")
    existing = (
        await session.execute(
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
    ).scalar_one_or_none()
    if existing:
        existing.status = SubscriptionStatus.canceled
        existing.canceled_at = datetime.now(timezone.utc)
        await session.commit()
    sub = await grant_free_subscription(
        session,
        user_id=user_id,
        plan_id=plan.id,
        duration_days=body.duration_days,
        admin_id=admin.id,
        reason=body.reason,
    )
    await _audit(
        session,
        admin=admin,
        action="subscription.grant",
        target_type="user",
        target_id=str(user_id),
        payload={
            "plan_slug": body.plan_slug,
            "duration_days": body.duration_days,
            "reason": body.reason,
            "subscription_id": str(sub.id),
        },
        request=request,
    )
    return SubscriptionOut(
        id=sub.id,
        user_id=sub.user_id,
        user_email=user.email,
        plan_slug=plan.slug,
        status=sub.status.value if hasattr(sub.status, "value") else str(sub.status),
        billing_period=sub.billing_period.value
        if hasattr(sub.billing_period, "value")
        else str(sub.billing_period),
        current_period_start=sub.current_period_start,
        current_period_end=sub.current_period_end,
        canceled_at=sub.canceled_at,
        stripe_subscription_id=sub.stripe_subscription_id,
        created_at=sub.created_at,
    )


@router.post("/users/{user_id}/revoke-subscription")
async def admin_revoke_subscription(
    user_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    sub = (
        await session.execute(
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
    ).scalar_one_or_none()
    if not sub:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no_active_subscription")
    if sub.stripe_subscription_id:
        try:
            await stripe_client.cancel_subscription(
                sub.stripe_subscription_id, at_period_end=False
            )
        except Exception as exc:
            logger.warning("stripe_cancel_failed sub=%s: %s", sub.id, exc)
    sub.status = SubscriptionStatus.canceled
    sub.canceled_at = datetime.now(timezone.utc)
    await session.commit()
    await _audit(
        session,
        admin=admin,
        action="subscription.revoke",
        target_type="subscription",
        target_id=str(sub.id),
        payload={"user_id": str(user_id)},
        request=request,
    )
    return {"revoked": True, "subscription_id": str(sub.id)}


# --- Plans ------------------------------------------------------------------


@router.get("/plans", response_model=list[PlanOut])
async def admin_list_plans(
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[PlanOut]:
    rows = (
        await session.execute(select(Plan).order_by(Plan.price_monthly_cents))
    ).scalars().all()
    return [_plan_out(p) for p in rows]


@router.post("/plans", response_model=PlanOut, status_code=201)
async def admin_create_plan(
    body: PlanIn,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> PlanOut:
    existing = (
        await session.execute(select(Plan).where(Plan.slug == body.slug))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "plan_slug_exists")
    plan = Plan(
        slug=body.slug,
        name=body.name,
        description=body.description,
        price_monthly_cents=body.price_monthly_cents,
        price_yearly_cents=body.price_yearly_cents,
        currency=body.currency,
        features=body.features,
        limits=body.limits,
        is_active=body.is_active,
    )
    session.add(plan)
    await session.commit()
    await session.refresh(plan)
    await _audit(
        session,
        admin=admin,
        action="plan.create",
        target_type="plan",
        target_id=str(plan.id),
        payload=body.model_dump(),
        request=request,
    )
    return _plan_out(plan)


@router.patch("/plans/{slug}", response_model=PlanOut)
async def admin_update_plan(
    slug: str,
    body: PlanPatch,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> PlanOut:
    plan = (
        await session.execute(select(Plan).where(Plan.slug == slug))
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "plan_not_found")
    changes: dict[str, Any] = {}
    for field, value in body.model_dump(exclude_unset=True).items():
        if getattr(plan, field) != value:
            changes[field] = value
            setattr(plan, field, value)
    if changes:
        await session.commit()
        await session.refresh(plan)
        await _audit(
            session,
            admin=admin,
            action="plan.update",
            target_type="plan",
            target_id=str(plan.id),
            payload=changes,
            request=request,
        )
    return _plan_out(plan)


@router.post("/plans/{slug}/sync-stripe", response_model=PlanOut)
async def admin_sync_plan_to_stripe(
    slug: str,
    request: Request,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> PlanOut:
    plan = (
        await session.execute(select(Plan).where(Plan.slug == slug))
    ).scalar_one_or_none()
    if not plan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "plan_not_found")

    lock_key = f"lock:plan-sync:{slug}"
    lock_acquired = False
    redis = None
    try:
        limiter = await get_limiter()
        redis = limiter.redis
        lock_acquired = await redis.set(lock_key, "1", ex=30, nx=True)
    except Exception as exc:
        logger.warning("sync-stripe redis unavailable: %s — proceeding unlocked", exc)
    if redis is not None and not lock_acquired:
        raise HTTPException(status.HTTP_409_CONFLICT, "sync_in_progress")

    try:
        product_id = await stripe_client.create_or_update_product(plan)
        currency = plan.currency or get_settings().stripe_default_currency
        monthly_id = (
            await stripe_client.create_or_update_price(
                product_id,
                plan.price_monthly_cents,
                currency,
                "month",
                plan.stripe_price_monthly_id,
            )
            if plan.price_monthly_cents > 0
            else None
        )
        yearly_id = (
            await stripe_client.create_or_update_price(
                product_id,
                plan.price_yearly_cents,
                currency,
                "year",
                plan.stripe_price_yearly_id,
            )
            if plan.price_yearly_cents > 0
            else None
        )
        plan.stripe_product_id = product_id
        plan.stripe_price_monthly_id = monthly_id
        plan.stripe_price_yearly_id = yearly_id
        await session.commit()
        await session.refresh(plan)
        await _audit(
            session,
            admin=admin,
            action="plan.sync_stripe",
            target_type="plan",
            target_id=str(plan.id),
            payload={
                "stripe_product_id": product_id,
                "stripe_price_monthly_id": monthly_id,
                "stripe_price_yearly_id": yearly_id,
            },
            request=request,
        )
    finally:
        if redis is not None and lock_acquired:
            try:
                await redis.delete(lock_key)
            except Exception:
                pass
    return _plan_out(plan)


# --- Subscriptions ----------------------------------------------------------


@router.get("/subscriptions", response_model=dict)
async def admin_list_subscriptions(
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    stmt = (
        select(Subscription, User, Plan)
        .join(User, Subscription.user_id == User.id)
        .join(Plan, Subscription.plan_id == Plan.id, isouter=True)
    )
    count_stmt = select(func.count(Subscription.id))
    if status_filter:
        try:
            sval = SubscriptionStatus(status_filter)
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "invalid_status"
            ) from exc
        stmt = stmt.where(Subscription.status == sval)
        count_stmt = count_stmt.where(Subscription.status == sval)
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(Subscription.created_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).all()
    items = [
        SubscriptionOut(
            id=sub.id,
            user_id=sub.user_id,
            user_email=u.email if u else None,
            plan_slug=p.slug if p else None,
            status=sub.status.value if hasattr(sub.status, "value") else str(sub.status),
            billing_period=sub.billing_period.value
            if hasattr(sub.billing_period, "value")
            else str(sub.billing_period),
            current_period_start=sub.current_period_start,
            current_period_end=sub.current_period_end,
            canceled_at=sub.canceled_at,
            stripe_subscription_id=sub.stripe_subscription_id,
            created_at=sub.created_at,
        ).model_dump()
        for sub, u, p in rows
    ]
    return {"items": items, "page": page, "page_size": page_size, "total": total}


# --- Audit log --------------------------------------------------------------


@router.get("/audit-log", response_model=dict)
async def admin_audit_log(
    action: str | None = None,
    admin_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    stmt = select(AuditLog)
    count_stmt = select(func.count(AuditLog.id))
    if action:
        stmt = stmt.where(AuditLog.action == action)
        count_stmt = count_stmt.where(AuditLog.action == action)
    if admin_id:
        stmt = stmt.where(AuditLog.admin_id == admin_id)
        count_stmt = count_stmt.where(AuditLog.admin_id == admin_id)
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(AuditLog.created_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).scalars().all()
    items = [
        AuditOut(
            id=r.id,
            action=r.action,
            target_type=r.target_type,
            target_id=r.target_id,
            user_id=r.user_id,
            admin_id=r.admin_id,
            payload=r.payload or {},
            created_at=r.created_at,
        ).model_dump()
        for r in rows
    ]
    return {"items": items, "page": page, "page_size": page_size, "total": total}


# --- Metrics ----------------------------------------------------------------


@router.get("/metrics", response_model=dict)
async def admin_metrics(
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    total_users = (await session.execute(select(func.count(User.id)))).scalar_one()

    active_states = [
        SubscriptionStatus.active,
        SubscriptionStatus.trialing,
        SubscriptionStatus.past_due,
    ]
    sub_rows = (
        await session.execute(
            select(Plan.slug, func.count(Subscription.id))
            .join(Subscription, Subscription.plan_id == Plan.id)
            .where(Subscription.status.in_(active_states))
            .group_by(Plan.slug)
        )
    ).all()
    active_subscriptions = {slug: count for slug, count in sub_rows}

    mrr_rows = (
        await session.execute(
            select(
                Subscription.billing_period,
                Plan.price_monthly_cents,
                Plan.price_yearly_cents,
                func.count(Subscription.id),
            )
            .join(Plan, Subscription.plan_id == Plan.id)
            .where(Subscription.status.in_([SubscriptionStatus.active, SubscriptionStatus.trialing]))
            .group_by(
                Subscription.billing_period,
                Plan.price_monthly_cents,
                Plan.price_yearly_cents,
            )
        )
    ).all()
    mrr_cents = 0
    for period, monthly, yearly, count in mrr_rows:
        period_val = period.value if hasattr(period, "value") else str(period)
        if period_val == "yearly":
            mrr_cents += int((yearly or 0) / 12) * count
        else:
            mrr_cents += (monthly or 0) * count
    arr_cents = mrr_cents * 12

    thirty_days_ago = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=30)
    churn_30d = (
        await session.execute(
            select(func.count(Subscription.id))
            .where(Subscription.canceled_at.is_not(None))
            .where(Subscription.canceled_at >= thirty_days_ago)
        )
    ).scalar_one()

    dau_today = 0
    try:
        limiter = await get_limiter()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        dau_today = int(await limiter.redis.pfcount(f"dau:{today}") or 0)
    except Exception:
        dau_today = 0

    return {
        "total_users": total_users,
        "active_subscriptions": active_subscriptions,
        "mrr_cents": mrr_cents,
        "arr_cents": arr_cents,
        "churn_30d": churn_30d,
        "dau_today": dau_today,
    }
