"""Redis-backed IP rate limiter (sliding window via INCR + EXPIRE)."""
from __future__ import annotations

import time
from typing import Awaitable, Callable

import redis.asyncio as aioredis
from fastapi import HTTPException, Request, Response, status

from apps.api.app.config import get_settings


class RateLimiter:
    def __init__(self, redis: aioredis.Redis, *, per_minute: int) -> None:
        self.redis = redis
        self.per_minute = per_minute

    async def check(self, ip: str) -> tuple[bool, int]:
        window = int(time.time() // 60)
        key = f"rl:{ip}:{window}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, 70)
        return count <= self.per_minute, count


_limiter: RateLimiter | None = None


async def get_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        settings = get_settings()
        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        _limiter = RateLimiter(redis, per_minute=settings.rate_limit_per_minute)
    return _limiter


async def rate_limit_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    if request.url.path.startswith(("/health", "/docs", "/openapi", "/redoc", "/api/countries")):
        return await call_next(request)
    ip = (
        (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    try:
        limiter = await get_limiter()
        allowed, count = await limiter.check(ip)
    except Exception:
        # Fail-open on Redis outage — better to serve than to block.
        return await call_next(request)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {count}/min for {ip}",
        )
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(limiter.per_minute)
    response.headers["X-RateLimit-Remaining"] = str(max(0, limiter.per_minute - count))
    return response
