"""Shared async HTTP client factory for adapters.

Centralizes timeouts, user-agent, retry, and (future) proxy rotation.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_UA = (
    "CreditLens/0.1 (+https://github.com/creditlens; respectful crawler) "
    "httpx/{ver}"
).format(ver=httpx.__version__)


def build_http_client(
    *,
    base_url: str | None = None,
    timeout: float = 20.0,
    headers: dict[str, str] | None = None,
    auth: httpx.Auth | tuple[str, str] | None = None,
    follow_redirects: bool = True,
) -> httpx.AsyncClient:
    """Build an httpx AsyncClient with sane defaults."""
    final_headers = {"User-Agent": DEFAULT_UA, "Accept-Language": "en;q=0.9"}
    if headers:
        final_headers.update(headers)
    return httpx.AsyncClient(
        base_url=base_url or "",
        timeout=httpx.Timeout(timeout),
        headers=final_headers,
        auth=auth,
        follow_redirects=follow_redirects,
    )


async def get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_attempts: int = 3,
    backoff_base: float = 0.8,
    **kwargs: Any,
) -> httpx.Response:
    """GET with exponential backoff on transient failures."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = await client.get(url, **kwargs)
            if response.status_code == 429:
                # Honor Retry-After if present.
                retry_after = float(response.headers.get("Retry-After", 5))
                logger.warning("429 on %s, sleeping %.1fs", url, retry_after)
                await asyncio.sleep(retry_after)
                continue
            return response
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_exc = exc
            sleep_for = backoff_base * (2 ** (attempt - 1)) + random.uniform(0, 0.25)
            logger.warning(
                "Transient error on %s (attempt %d/%d): %s — sleeping %.2fs",
                url, attempt, max_attempts, exc, sleep_for,
            )
            await asyncio.sleep(sleep_for)
    assert last_exc is not None
    raise last_exc
