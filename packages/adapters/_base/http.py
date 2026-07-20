"""Shared async HTTP client factory for adapters.

Centralizes timeouts, user-agent, retry, and (future) proxy rotation.
"""
from __future__ import annotations

import asyncio
import logging
import random
import ssl
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_UA = (
    "Credyx/0.1 (+https://credyx.ai; respectful crawler) "
    "httpx/{ver}"
).format(ver=httpx.__version__)


def _default_ssl_context() -> ssl.SSLContext | bool:
    """OS trust store when available — several registries (RS, TW, ZA) serve
    chains that certifi rejects but the platform store accepts."""
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        return True


_SSL_CONTEXT = _default_ssl_context()


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
        verify=_SSL_CONTEXT,
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


# --- Bot-wall detection + FlareSolverr fallback -----------------------------

_BOT_WALL_MARKERS = (
    "just a moment",
    "checking your browser",
    "cf-browser-verification",
    "cf-challenge",
    "attention required",
    "ddos protection by cloudflare",
    "enable javascript and cookies",
    "/cdn-cgi/challenge-platform/",
    "_incapsula_resource",
    "incapsula incident",
    "perimeterx",
    "px-captcha",
    "errors.edgesuite.net",
    "<title>access denied</title>",
    "akamaighost",
)

_BOT_WALL_STATUS_ALWAYS = {503, 520, 521, 522, 523, 524, 525, 526, 527}


def is_bot_wall(response: httpx.Response) -> bool:
    """Heuristic: does this response look like a Cloudflare/Akamai/PerimeterX challenge?"""
    if response.status_code in _BOT_WALL_STATUS_ALWAYS:
        return True
    body_lower = (response.text or "").lower()[:4000]
    if any(marker in body_lower for marker in _BOT_WALL_MARKERS):
        return True
    if response.status_code == 403:
        # Any 403 returning HTML (not JSON API error) is likely a bot wall.
        ctype = response.headers.get("content-type", "").lower()
        if "json" not in ctype and "<" in body_lower[:200]:
            return True
        server = response.headers.get("server", "").lower()
        if "cloudflare" in server or "akamai" in server or response.headers.get("cf-mitigated"):
            return True
    return False


async def fetch_with_bot_bypass(
    url: str,
    *,
    method: str = "GET",
    post_data: str | None = None,
    client: httpx.AsyncClient | None = None,
    timeout: float = 20.0,
) -> tuple[str, int, str]:
    """Fetch a URL with automatic FlareSolverr fallback on bot-wall detection.

    Returns ``(html_or_body_text, status_code, source)`` where source is
    ``"httpx"`` if the direct request succeeded, ``"flaresolverr"`` if the
    fallback was used.

    Use this from any adapter whose registry sometimes serves a Cloudflare /
    Akamai challenge. JSON APIs should keep using ``get_with_retry`` — they
    don't need this extra path.
    """
    owns_client = client is None
    if owns_client:
        client = build_http_client(timeout=timeout)
    try:
        if method.upper() == "POST":
            resp = await client.post(url, content=post_data, timeout=timeout)
        else:
            resp = await client.get(url, timeout=timeout)
        if not is_bot_wall(resp):
            return resp.text, resp.status_code, "httpx"
        logger.info("Bot wall detected on %s (status=%d) — falling back to FlareSolverr", url, resp.status_code)
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        logger.info("Transport error on %s (%s) — trying FlareSolverr", url, exc)
    finally:
        if owns_client:
            await client.aclose()

    from packages.adapters._base.flaresolverr import (
        FlareSolverrError,
        get_flaresolverr_client,
    )

    flare = get_flaresolverr_client()
    try:
        flare_resp = await flare.fetch_html(url, method=method, post_data=post_data)
    except FlareSolverrError as exc:
        raise httpx.HTTPError(f"Bot wall + FlareSolverr failed: {exc}") from exc
    return flare_resp.html, flare_resp.status, "flaresolverr"
