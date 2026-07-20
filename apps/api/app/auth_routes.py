"""Authentication and account routes — /api/auth/*.

Flow:
- Register issues a verification email containing a single-use token. The
  token's sha256 hash is stored in Redis (24h TTL) so the raw token never
  hits the database.
- Login mints an access+refresh pair; refresh rotates the refresh token and
  blacklists the old jti.
- Password reset bumps ``User.password_version`` which invalidates every
  outstanding token via the ``pwv`` claim check in ``current_user``.

We deliberately use ``str`` for email fields to avoid the optional
``email-validator`` dependency. Format validation is done in-route.
"""
from __future__ import annotations

import hashlib
import logging
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.app.auth import (
    _blacklist_jti,
    _get_redis,
    bearer,
    create_access_token,
    create_refresh_token,
    current_user,
    decode_token,
    hash_password,
    pwd_ctx,
    verify_password,
)
from apps.api.app.config import get_settings
from apps.api.app.db import Subscription, User, UserRole, get_session
from apps.api.app.feature_gate import plan_features, plan_limits, plan_slug

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

# A precomputed bcrypt hash used to keep login response time constant when
# the email does not exist. Prevents a timing oracle for email enumeration.
_DUMMY_HASH = pwd_ctx.hash("placeholder-do-not-match")


def _normalize_email(raw: str) -> str:
    s = raw.strip().lower()
    if not _EMAIL_RE.match(s):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_email")
    return s


def _validate_password(pw: str) -> None:
    if len(pw) < 8:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "password_too_short")
    if not any(c.isdigit() for c in pw):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "password_needs_digit")


def _token_and_hash() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --- Schemas ----------------------------------------------------------------


class RegisterIn(BaseModel):
    email: str
    first_name: str = Field(..., min_length=1, max_length=128)
    last_name: str = Field(..., min_length=1, max_length=128)
    password: str


class LoginIn(BaseModel):
    email: str
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class MeOut(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    role: str
    email_verified: bool
    plan_slug: str | None
    plan_features: dict[str, Any]
    plan_limits: dict[str, Any]


class UpdateMeIn(BaseModel):
    first_name: str | None = Field(None, min_length=1, max_length=128)
    last_name: str | None = Field(None, min_length=1, max_length=128)


class ForgotPasswordIn(BaseModel):
    email: str


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str


class VerifyEmailIn(BaseModel):
    token: str


class RefreshIn(BaseModel):
    refresh_token: str


class RegisterOut(BaseModel):
    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    role: str
    email_verified: bool


class PreferencesOut(BaseModel):
    """User UI/UX preferences. Always an object, possibly empty."""

    preferences: dict[str, Any]


class PreferencesPatchIn(BaseModel):
    """Whitelisted preference keys. Unknown keys are dropped silently."""

    theme: str | None = Field(None, description="One of: system | light | dark")
    onboarded: bool | None = None
    default_country: str | None = Field(
        None, min_length=2, max_length=2, description="ISO 3166-1 alpha-2 country code"
    )
    compact_mode: bool | None = None

    @field_validator("theme")
    @classmethod
    def _theme_choice(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if v not in {"system", "light", "dark"}:
            raise ValueError("theme must be one of: system, light, dark")
        return v

    @field_validator("default_country")
    @classmethod
    def _country_upper(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not v.isalpha():
            raise ValueError("default_country must be 2 alphabetic characters")
        return v.upper()


# --- Helpers ---------------------------------------------------------------


async def _load_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    stmt = (
        select(User)
        .options(selectinload(User.subscriptions).selectinload(Subscription.plan))
        .where(User.id == user_id)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _me(user: User) -> MeOut:
    return MeOut(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role.value if isinstance(user.role, UserRole) else str(user.role),
        email_verified=user.email_verified_at is not None,
        plan_slug=plan_slug(user),
        plan_features=plan_features(user),
        plan_limits=plan_limits(user),
    )


# --- Endpoints --------------------------------------------------------------


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=RegisterOut)
async def register(body: RegisterIn, session: AsyncSession = Depends(get_session)) -> RegisterOut:
    settings = get_settings()
    email = _normalize_email(body.email)
    _validate_password(body.password)

    existing = (
        await session.execute(select(User).where(func.lower(User.email) == email))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "email_already_registered")

    bootstrap = (settings.bootstrap_admin_email or "").strip().lower()
    role = UserRole.admin if bootstrap and email == bootstrap else UserRole.user

    # Dev convenience: auto-verify email if no SMTP server configured (MailHog
    # default port 1025 doesn't deliver real mail, so users would be locked out).
    auto_verify = settings.smtp_host in ("localhost", "127.0.0.1", "mailhog") or settings.smtp_port == 1025

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        first_name=body.first_name.strip(),
        last_name=body.last_name.strip(),
        role=role,
        email_verified_at=datetime.now(timezone.utc) if auto_verify else None,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    raw_token, token_hash = _token_and_hash()
    r = await _get_redis()
    if r is not None:
        try:
            await r.set(f"verify:{token_hash}", str(user.id), ex=24 * 3600)
        except Exception as exc:
            logger.warning("failed to stash verify token: %s", exc)

    verify_url = f"{settings.public_app_url}/verify-email?token={raw_token}"
    try:
        from packages.email.tasks import send_verification_email

        send_verification_email.delay(user.email, user.first_name, verify_url)
    except Exception as exc:
        logger.warning("send_verification_email enqueue failed: %s", exc)

    return RegisterOut(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        role=user.role.value,
        email_verified=user.email_verified_at is not None,
    )


@router.post("/verify-email", status_code=status.HTTP_200_OK)
async def verify_email(body: VerifyEmailIn, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    token_hash = hashlib.sha256(body.token.encode("utf-8")).hexdigest()
    r = await _get_redis()
    if r is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "verify_store_unavailable")
    user_id_raw = await r.get(f"verify:{token_hash}")
    if not user_id_raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_or_expired_token")
    try:
        user_id = uuid.UUID(user_id_raw if isinstance(user_id_raw, str) else user_id_raw.decode())
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_token_payload") from exc
    user = await _load_user(session, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")
    user.email_verified_at = datetime.now(timezone.utc)
    await session.commit()
    try:
        await r.delete(f"verify:{token_hash}")
    except Exception:
        pass
    return {"status": "ok"}


@router.post("/login", response_model=TokenPair)
async def login(body: LoginIn, session: AsyncSession = Depends(get_session)) -> TokenPair:
    email = _normalize_email(body.email)
    user = (
        await session.execute(select(User).where(func.lower(User.email) == email))
    ).scalar_one_or_none()
    if not user:
        # Burn the same compute path to neutralize the timing oracle.
        verify_password(body.password, _DUMMY_HASH)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_credentials")
    if user.email_verified_at is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "email_not_verified")
    role_str = user.role.value if isinstance(user.role, UserRole) else str(user.role)
    return TokenPair(
        access_token=create_access_token(user.id, role_str, user.password_version),
        refresh_token=create_refresh_token(user.id, user.password_version),
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshIn, session: AsyncSession = Depends(get_session)) -> TokenPair:
    payload = decode_token(body.refresh_token, expected_type="refresh")
    jti = payload.get("jti")
    if jti:
        from apps.api.app.auth import _is_revoked

        if await _is_revoked(jti):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token_revoked")
    try:
        user_id = uuid.UUID(payload["sub"])
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_subject") from exc
    user = await _load_user(session, user_id)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user_not_found")
    if int(payload.get("pwv", -1)) != user.password_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "password_changed")

    if jti:
        await _blacklist_jti(jti, int(payload.get("exp", 0)))

    role_str = user.role.value if isinstance(user.role, UserRole) else str(user.role)
    return TokenPair(
        access_token=create_access_token(user.id, role_str, user.password_version),
        refresh_token=create_refresh_token(user.id, user.password_version),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def logout(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    _user: User = Depends(current_user),
) -> Response:
    if creds and creds.scheme.lower() == "bearer":
        try:
            payload = decode_token(creds.credentials, expected_type="access")
            jti = payload.get("jti")
            if jti:
                await _blacklist_jti(jti, int(payload.get("exp", 0)))
        except HTTPException:
            pass
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def forgot_password(body: ForgotPasswordIn, session: AsyncSession = Depends(get_session)) -> Response:
    settings = get_settings()
    _NO_BODY = Response(status_code=status.HTTP_204_NO_CONTENT)
    try:
        email = _normalize_email(body.email)
    except HTTPException:
        return _NO_BODY  # Always 204 — never leak account state.
    user = (
        await session.execute(select(User).where(func.lower(User.email) == email))
    ).scalar_one_or_none()
    if not user:
        return _NO_BODY
    raw_token, token_hash = _token_and_hash()
    r = await _get_redis()
    if r is not None:
        try:
            await r.set(f"pwreset:{token_hash}", str(user.id), ex=3600)
        except Exception as exc:
            logger.warning("failed to stash pwreset token: %s", exc)
            return _NO_BODY
    reset_url = f"{settings.public_app_url}/reset-password?token={raw_token}"
    try:
        from packages.email.tasks import send_password_reset

        send_password_reset.delay(user.email, user.first_name, reset_url)
    except Exception as exc:
        logger.warning("send_password_reset enqueue failed: %s", exc)
    return _NO_BODY


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(body: ResetPasswordIn, session: AsyncSession = Depends(get_session)) -> dict[str, str]:
    _validate_password(body.new_password)
    token_hash = hashlib.sha256(body.token.encode("utf-8")).hexdigest()
    r = await _get_redis()
    if r is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "reset_store_unavailable")
    user_id_raw = await r.get(f"pwreset:{token_hash}")
    if not user_id_raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_or_expired_token")
    try:
        user_id = uuid.UUID(user_id_raw if isinstance(user_id_raw, str) else user_id_raw.decode())
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_token_payload") from exc
    user = await _load_user(session, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")
    user.password_hash = hash_password(body.new_password)
    user.password_version = (user.password_version or 0) + 1
    await session.commit()
    try:
        await r.delete(f"pwreset:{token_hash}")
    except Exception:
        pass
    return {"status": "ok"}


@router.get("/me", response_model=MeOut)
async def get_me(user: User = Depends(current_user)) -> MeOut:
    return _me(user)


@router.patch("/me", response_model=MeOut)
async def patch_me(
    body: UpdateMeIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> MeOut:
    if body.first_name is not None:
        user.first_name = body.first_name.strip()
    if body.last_name is not None:
        user.last_name = body.last_name.strip()
    session.add(user)
    await session.commit()
    await session.refresh(user)
    fresh = await _load_user(session, user.id)
    assert fresh is not None
    return _me(fresh)


@router.get("/me/preferences", response_model=PreferencesOut)
async def get_me_preferences(user: User = Depends(current_user)) -> PreferencesOut:
    """Return the current user's preferences as an object (empty if unset)."""
    return PreferencesOut(preferences=dict(user.preferences or {}))


@router.patch("/me/preferences", response_model=PreferencesOut)
async def patch_me_preferences(
    body: PreferencesPatchIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> PreferencesOut:
    """Merge whitelisted preference keys into the user's preferences dict.

    Unknown keys are dropped silently by the Pydantic schema. Only fields the
    caller explicitly sets are written — `None` values are treated as omitted.
    """
    merged: dict[str, Any] = dict(user.preferences or {})
    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    merged.update(updates)
    user.preferences = merged
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return PreferencesOut(preferences=dict(user.preferences or {}))
