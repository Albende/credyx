"""Shared Playwright browser pool.

Many country registries (GE NAPR's enreg, ME CRPS, MX SAT, IN MCA21,
DK virk.dk's SPA shell, etc.) can't be reached with a plain httpx GET:
they JS-render their result tables, gate behind a multi-step ViewState
form, or set session cookies on a landing page before accepting form
submits. Spinning up a fresh Chromium per adapter call is too slow and
too memory-hungry.

The `BrowserPool` keeps a single Chromium process alive and holds N
persistent `BrowserContext` instances in an `asyncio.Queue`. Adapters
acquire a context with `async with pool.acquire() as ctx:` and the
context is wiped (cookies cleared) and returned to the pool on exit.
Adapters that need a logged-in session can ask for a stable
`persistent_id="dk-virk"` — the pool keeps that context's storage state
across requests instead of wiping.

Failure handling:
- If the Chromium process dies between requests, the next `acquire()`
  detects it and rebuilds.
- If a single context throws while in use, the pool discards it and
  builds a replacement before returning to the queue — one bad page
  never poisons the pool.
- `stop()` is safe to call multiple times and idempotent on partial
  startup.

Lazy startup: the pool is not initialized at import time. The first
`acquire()` triggers `start()` under a lock; the FastAPI shutdown hook
calls `close_browser_pool()`.

Non-negotiable: this module does no CAPTCHA solving. If a page renders
a CAPTCHA, the caller must raise `BlockedByRegistryError` and surface a
501 — we do not silently retry or call a paid solver.
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

from packages.adapters._base.proxy import ProxyConfig, get_proxy_provider

if TYPE_CHECKING:
    from playwright.async_api import (
        Browser,
        BrowserContext,
        Playwright,
    )

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("invalid int for %s=%r, using default %d", name, raw, default)
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class BrowserPool:
    """Hot pool of Playwright Chromium contexts."""

    def __init__(
        self,
        *,
        pool_size: int | None = None,
        headless: bool | None = None,
        proxy: ProxyConfig | None = None,
    ) -> None:
        self._pool_size = (
            pool_size
            if pool_size is not None
            else _env_int("BROWSER_POOL_SIZE", 5)
        )
        self._headless = (
            headless
            if headless is not None
            else _env_bool("BROWSER_HEADLESS", True)
        )
        self._explicit_proxy = proxy

        self._lock = asyncio.Lock()
        self._started = False
        self._stopped = False

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._queue: asyncio.Queue[BrowserContext] | None = None
        self._persistent: dict[str, BrowserContext] = {}
        self._persistent_locks: dict[str, asyncio.Lock] = {}

    @property
    def pool_size(self) -> int:
        return self._pool_size

    @property
    def headless(self) -> bool:
        return self._headless

    @property
    def started(self) -> bool:
        return self._started

    async def start(self) -> None:
        """Launch Chromium and pre-warm `pool_size` contexts."""
        async with self._lock:
            if self._started:
                return
            await self._launch_locked()
            self._started = True
            self._stopped = False

    async def _launch_locked(self) -> None:
        from playwright.async_api import async_playwright

        proxy_cfg = self._explicit_proxy
        if proxy_cfg is None:
            proxy_cfg = await get_proxy_provider().get_proxy()

        launch_kwargs: dict[str, object] = {"headless": self._headless}
        if proxy_cfg is not None:
            launch_kwargs["proxy"] = proxy_cfg.to_playwright()

        logger.info(
            "BrowserPool launching Chromium (pool_size=%d, headless=%s, proxy=%s)",
            self._pool_size,
            self._headless,
            "yes" if proxy_cfg else "no",
        )
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(**launch_kwargs)

        self._queue = asyncio.Queue(maxsize=self._pool_size)
        for _ in range(self._pool_size):
            ctx = await self._new_context()
            self._queue.put_nowait(ctx)

    async def _new_context(
        self, *, user_agent: str | None = None, locale: str = "en-US"
    ) -> BrowserContext:
        assert self._browser is not None, "browser not launched"
        ctx_kwargs: dict[str, object] = {"locale": locale}
        if user_agent is not None:
            ctx_kwargs["user_agent"] = user_agent
        return await self._browser.new_context(**ctx_kwargs)

    async def stop(self) -> None:
        """Tear the pool down. Safe to call multiple times."""
        async with self._lock:
            if self._stopped or not self._started:
                self._started = False
                self._stopped = True
                return
            await self._teardown_locked()
            self._started = False
            self._stopped = True

    async def _teardown_locked(self) -> None:
        if self._queue is not None:
            while not self._queue.empty():
                try:
                    ctx = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                await _safe_close_context(ctx)
        for ctx in list(self._persistent.values()):
            await _safe_close_context(ctx)
        self._persistent.clear()
        self._persistent_locks.clear()

        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as exc:
                logger.warning("error closing Chromium: %s", exc)
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as exc:
                logger.warning("error stopping playwright: %s", exc)
        self._browser = None
        self._playwright = None
        self._queue = None

    def _browser_alive(self) -> bool:
        if self._browser is None:
            return False
        # Playwright's Browser.is_connected() is the canonical check.
        is_connected = getattr(self._browser, "is_connected", None)
        if is_connected is None:
            return True
        try:
            return bool(is_connected())
        except Exception:
            return False

    async def _ensure_started(self) -> None:
        if self._started and self._browser_alive():
            return
        async with self._lock:
            if self._started and self._browser_alive():
                return
            if self._started and not self._browser_alive():
                logger.warning("Chromium died; rebuilding pool")
                await self._teardown_locked()
                self._started = False
            await self._launch_locked()
            self._started = True
            self._stopped = False

    @asynccontextmanager
    async def acquire(
        self,
        *,
        user_agent: str | None = None,
        locale: str = "en-US",
        persistent_id: str | None = None,
    ) -> AsyncIterator[BrowserContext]:
        """Borrow a `BrowserContext` from the pool.

        `persistent_id` keeps the context (and its cookies / storage
        state) reserved for one logical session — useful for registries
        that require a sign-in step.
        """
        await self._ensure_started()
        assert self._queue is not None

        if persistent_id is not None:
            lock = self._persistent_locks.setdefault(persistent_id, asyncio.Lock())
            async with lock:
                ctx = self._persistent.get(persistent_id)
                if ctx is None or not _context_alive(ctx):
                    ctx = await self._new_context(
                        user_agent=user_agent, locale=locale
                    )
                    self._persistent[persistent_id] = ctx
                try:
                    yield ctx
                except Exception:
                    # Discard a poisoned persistent context so the next
                    # caller gets a fresh one.
                    self._persistent.pop(persistent_id, None)
                    await _safe_close_context(ctx)
                    raise
            return

        ctx = await self._queue.get()
        replacement_needed = False
        try:
            yield ctx
        except Exception:
            replacement_needed = True
            raise
        finally:
            if replacement_needed or not _context_alive(ctx):
                await _safe_close_context(ctx)
                try:
                    new_ctx = await self._new_context(
                        user_agent=user_agent, locale=locale
                    )
                except Exception as exc:
                    logger.error("failed to rebuild context: %s", exc)
                    # Put nothing back so capacity shrinks until next restart;
                    # better than blocking forever on a dead browser.
                    return
                await self._queue.put(new_ctx)
            else:
                await _wipe_context(ctx)
                await self._queue.put(ctx)


async def _wipe_context(ctx: BrowserContext) -> None:
    """Clear cookies + close all pages so the next borrower starts fresh."""
    try:
        await ctx.clear_cookies()
    except Exception as exc:
        logger.debug("clear_cookies failed: %s", exc)
    try:
        for page in list(ctx.pages):
            await page.close()
    except Exception as exc:
        logger.debug("page.close failed during wipe: %s", exc)


async def _safe_close_context(ctx: BrowserContext) -> None:
    try:
        await ctx.close()
    except Exception as exc:
        logger.debug("context close failed: %s", exc)


def _context_alive(ctx: BrowserContext) -> bool:
    browser = getattr(ctx, "browser", None)
    if browser is None:
        return True
    is_connected = getattr(browser, "is_connected", None)
    if is_connected is None:
        return True
    try:
        return bool(is_connected())
    except Exception:
        return False


_pool_singleton: BrowserPool | None = None


def get_browser_pool() -> BrowserPool:
    """Return (lazily constructing) the process-wide pool singleton."""
    global _pool_singleton
    if _pool_singleton is None:
        _pool_singleton = BrowserPool()
    return _pool_singleton


def set_browser_pool(pool: BrowserPool | None) -> None:
    """Replace the singleton, mostly for tests."""
    global _pool_singleton
    _pool_singleton = pool


async def close_browser_pool() -> None:
    """Stop and forget the singleton. FastAPI shutdown hook calls this."""
    global _pool_singleton
    if _pool_singleton is None:
        return
    pool = _pool_singleton
    _pool_singleton = None
    await pool.stop()
