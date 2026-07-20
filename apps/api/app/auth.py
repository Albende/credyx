"""Password hashing, JWT issuance/validation, and FastAPI auth dependencies.

The JWT layer issues two token types — ``access`` (short-lived) and
``refresh`` (long-lived). Both carry the user's ``password_version`` so that
a password reset invalidates every outstanding token.

Token revocation uses a Redis-backed denylist keyed by the JWT ``jti``.
If Redis is unreachable we degrade open — the rest of the system already
treats Redis as best-effort (see ``rate_limit.py``).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.app.config import get_settings
from apps.api.app.db import Subscription, User, UserRole, get_session

logger = logging.getLogger(__name__)
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


def _peppered(pw: str) -> str:
    """Prepend the configured pepper. Bcrypt silently truncates past 72 bytes,
    which is fine here: a peppered password plus user secret stays well-defined,
    just capped. Document this for security review.
    """
    s = get_settings()
    return f"{s.password_pepper}{pw}"


def hash_password(pw: str) -> str:
    return pwd_ctx.hash(_peppered(pw))


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return pwd_ctx.verify(_peppered(pw), hashed)
    except Exception:
        return False


def _make_token(*, sub: str, typ: str, ttl: timedelta, extra: dict[str, Any]) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": sub,
        "typ": typ,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": uuid.uuid4().hex,
        **extra,
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def create_access_token(user_id: uuid.UUID, role: str, pwv: int) -> str:
    s = get_settings()
    return _make_token(
        sub=str(user_id),
        typ="access",
        ttl=timedelta(minutes=s.access_token_ttl_minutes),
        extra={"role": role, "pwv": pwv},
    )


def create_refresh_token(user_id: uuid.UUID, pwv: int) -> str:
    s = get_settings()
    return _make_token(
        sub=str(user_id),
        typ="refresh",
        ttl=timedelta(days=s.refresh_token_ttl_days),
        extra={"pwv": pwv},
    )


async def _get_redis():
    """Best-effort lazy fetch of the shared Redis client. Returns None if
    Redis is unavailable; callers must tolerate that and degrade open.
    """
    try:
        from apps.api.app.rate_limit import get_limiter

        limiter = await get_limiter()
        return limiter.redis
    except Exception as exc:
        logger.debug("redis unavailable for auth helper: %s", exc)
        return None


async def _is_revoked(jti: str) -> bool:
    r = await _get_redis()
    if r is None:
        return False
    try:
        return bool(await r.exists(f"revoked:{jti}"))
    except Exception:
        return False


async def _blacklist_jti(jti: str, exp: int) -> None:
    r = await _get_redis()
    if r is None:
        return
    now = int(datetime.now(timezone.utc).timestamp())
    ttl = max(1, exp - now)
    try:
        await r.set(f"revoked:{jti}", "1", ex=ttl)
    except Exception as exc:
        logger.warning("failed to blacklist jti=%s: %s", jti, exc)


def decode_token(token: str, *, expected_type: str) -> dict[str, Any]:
    """Decode and validate a JWT. Raises HTTPException(401) on any failure."""
    s = get_settings()
    try:
        payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_token") from exc
    if payload.get("typ") != expected_type:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong_token_type")
    return payload


async def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not creds or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "auth_required")
    payload = decode_token(creds.credentials, expected_type="access")
    jti = payload.get("jti")
    if jti and await _is_revoked(jti):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token_revoked")
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_subject") from exc
    pwv = int(payload.get("pwv", 0))
    stmt = (
        select(User)
        .options(selectinload(User.subscriptions).selectinload(Subscription.plan))
        .where(User.id == user_id)
    )
    user = (await session.execute(stmt)).scalar_one_or_none()
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user_not_found")
    if user.password_version != pwv:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "password_changed")
    return user


async def current_user_optional(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> User | None:
    if not creds or creds.scheme.lower() != "bearer":
        return None
    try:
        return await current_user(creds=creds, session=session)
    except HTTPException:
        return None


async def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin_required")
    return user
