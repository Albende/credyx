"""Pool-lifecycle tests with a fake `playwright.async_api` module.

These tests never spawn a real Chromium process; instead they install a
minimal in-memory stand-in for `playwright.async_api` so we can validate
acquire/release semantics, browser-death recovery, context wipe, and
persistent-session reuse without the install footprint.
"""
from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

import pytest

from packages.adapters._base import browser as browser_mod
from packages.adapters._base.browser import (
    BrowserPool,
    close_browser_pool,
    get_browser_pool,
    set_browser_pool,
)
from packages.adapters._base.proxy import (
    EnvProxyProvider,
    NoopProxyProvider,
    ProxyConfig,
    get_proxy_provider,
    set_proxy_provider,
)


# --- Fake Playwright -------------------------------------------------------

class _FakeContext:
    def __init__(self, browser: "_FakeBrowser", **kwargs: Any) -> None:
        self.browser = browser
        self.kwargs = kwargs
        self.pages: list[Any] = []
        self.closed = False
        self.cookies_cleared = 0

    async def clear_cookies(self) -> None:
        self.cookies_cleared += 1

    async def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self) -> None:
        self.connected = True
        self.contexts: list[_FakeContext] = []

    def is_connected(self) -> bool:
        return self.connected

    async def new_context(self, **kwargs: Any) -> _FakeContext:
        ctx = _FakeContext(self, **kwargs)
        self.contexts.append(ctx)
        return ctx

    async def close(self) -> None:
        self.connected = False


class _FakeChromium:
    def __init__(self, parent: "_FakePlaywright") -> None:
        self.parent = parent

    async def launch(self, **kwargs: Any) -> _FakeBrowser:
        self.parent.launch_kwargs.append(kwargs)
        b = _FakeBrowser()
        self.parent.browsers.append(b)
        return b


class _FakePlaywright:
    def __init__(self) -> None:
        self.chromium = _FakeChromium(self)
        self.launch_kwargs: list[dict[str, Any]] = []
        self.browsers: list[_FakeBrowser] = []
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True


class _FakeAsyncPlaywrightContext:
    def __init__(self) -> None:
        self.pw = _FakePlaywright()

    async def start(self) -> _FakePlaywright:
        return self.pw


def _install_fake_playwright(monkeypatch: pytest.MonkeyPatch) -> _FakeAsyncPlaywrightContext:
    """Inject a fake `playwright.async_api` into sys.modules.

    Returns the holder so tests can inspect launch args / browsers.
    """
    holder = _FakeAsyncPlaywrightContext()

    def async_playwright() -> _FakeAsyncPlaywrightContext:
        return holder

    fake_module = types.ModuleType("playwright.async_api")
    fake_module.async_playwright = async_playwright  # type: ignore[attr-defined]
    fake_module.Browser = _FakeBrowser  # type: ignore[attr-defined]
    fake_module.BrowserContext = _FakeContext  # type: ignore[attr-defined]
    fake_module.Playwright = _FakePlaywright  # type: ignore[attr-defined]

    parent = types.ModuleType("playwright")
    parent.async_api = fake_module  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "playwright", parent)
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_module)
    return holder


@pytest.fixture(autouse=True)
def _reset_singletons() -> None:
    set_browser_pool(None)
    set_proxy_provider(None)
    yield
    set_browser_pool(None)
    set_proxy_provider(None)


# --- Tests -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_pool_lazy_start_and_acquire(monkeypatch: pytest.MonkeyPatch) -> None:
    holder = _install_fake_playwright(monkeypatch)

    pool = BrowserPool(pool_size=2, headless=True)
    assert pool.started is False

    async with pool.acquire() as ctx:
        assert isinstance(ctx, _FakeContext)
        assert ctx.browser.connected is True
    assert pool.started is True
    # One Chromium launched, two contexts pre-warmed.
    assert len(holder.pw.browsers) == 1
    assert len(holder.pw.browsers[0].contexts) == 2
    await pool.stop()


@pytest.mark.asyncio
async def test_acquire_wipes_context_on_release(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_playwright(monkeypatch)
    pool = BrowserPool(pool_size=1)
    async with pool.acquire() as ctx:
        first = ctx
    async with pool.acquire() as ctx:
        # Same context handed back after wipe.
        assert ctx is first
        assert first.cookies_cleared >= 1
    await pool.stop()


@pytest.mark.asyncio
async def test_acquire_replaces_context_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_playwright(monkeypatch)
    pool = BrowserPool(pool_size=1)
    bad: _FakeContext | None = None
    with pytest.raises(RuntimeError):
        async with pool.acquire() as ctx:
            bad = ctx
            raise RuntimeError("page crashed")
    assert bad is not None and bad.closed is True
    # Pool capacity restored with a fresh context.
    async with pool.acquire() as ctx:
        assert ctx is not bad
        assert ctx.closed is False
    await pool.stop()


@pytest.mark.asyncio
async def test_persistent_id_reuses_context(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_playwright(monkeypatch)
    pool = BrowserPool(pool_size=1)
    async with pool.acquire(persistent_id="dk-virk") as ctx1:
        first = ctx1
        assert first.cookies_cleared == 0
    async with pool.acquire(persistent_id="dk-virk") as ctx2:
        assert ctx2 is first
        # Persistent contexts are NOT wiped between borrows.
        assert ctx2.cookies_cleared == 0
    await pool.stop()


@pytest.mark.asyncio
async def test_persistent_id_rebuilds_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_playwright(monkeypatch)
    pool = BrowserPool(pool_size=1)
    with pytest.raises(ValueError):
        async with pool.acquire(persistent_id="dk-virk") as ctx:
            bad = ctx
            raise ValueError("session expired")
    assert bad.closed is True
    async with pool.acquire(persistent_id="dk-virk") as ctx2:
        assert ctx2 is not bad
    await pool.stop()


@pytest.mark.asyncio
async def test_pool_recovers_when_browser_dies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    holder = _install_fake_playwright(monkeypatch)
    pool = BrowserPool(pool_size=1)
    async with pool.acquire() as ctx:
        assert ctx.browser.connected
    # Simulate Chromium dying.
    holder.pw.browsers[-1].connected = False
    async with pool.acquire() as ctx:
        # New browser launched, new context handed out.
        assert ctx.browser.connected is True
    assert len(holder.pw.browsers) == 2
    await pool.stop()


@pytest.mark.asyncio
async def test_pool_size_limits_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_playwright(monkeypatch)
    pool = BrowserPool(pool_size=2)
    barrier = asyncio.Event()
    seen: list[int] = []

    async def borrow(idx: int) -> None:
        async with pool.acquire() as ctx:
            seen.append(idx)
            await barrier.wait()

    t1 = asyncio.create_task(borrow(1))
    t2 = asyncio.create_task(borrow(2))
    await asyncio.sleep(0.01)
    t3 = asyncio.create_task(borrow(3))
    await asyncio.sleep(0.01)
    # Only the first two borrowers entered the body.
    assert sorted(seen) == [1, 2]
    barrier.set()
    await asyncio.gather(t1, t2, t3)
    assert sorted(seen) == [1, 2, 3]
    await pool.stop()


@pytest.mark.asyncio
async def test_stop_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    holder = _install_fake_playwright(monkeypatch)
    pool = BrowserPool(pool_size=1)
    async with pool.acquire():
        pass
    await pool.stop()
    await pool.stop()
    assert holder.pw.stopped is True


@pytest.mark.asyncio
async def test_singleton_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_playwright(monkeypatch)
    pool = get_browser_pool()
    assert isinstance(pool, BrowserPool)
    async with pool.acquire():
        pass
    await close_browser_pool()
    # After close the global is forgotten — next get_browser_pool() is a
    # fresh, unstarted pool.
    pool2 = get_browser_pool()
    assert pool2 is not pool


@pytest.mark.asyncio
async def test_proxy_passed_to_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    holder = _install_fake_playwright(monkeypatch)
    cfg = ProxyConfig(server="http://proxy.example:22225", username="u", password="p")
    pool = BrowserPool(pool_size=1, proxy=cfg)
    async with pool.acquire():
        pass
    assert holder.pw.launch_kwargs[0]["proxy"] == {
        "server": "http://proxy.example:22225",
        "username": "u",
        "password": "p",
    }
    await pool.stop()


# --- Proxy module ----------------------------------------------------------


@pytest.mark.asyncio
async def test_noop_proxy_returns_none() -> None:
    assert await NoopProxyProvider().get_proxy() is None
    assert await NoopProxyProvider().get_proxy(country="DE") is None


@pytest.mark.asyncio
async def test_env_proxy_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROXY_SERVER", "http://proxy.test:8080")
    monkeypatch.setenv("PROXY_USER", "alice")
    monkeypatch.setenv("PROXY_PASS", "secret")
    monkeypatch.setenv("PROXY_ROTATION", "per_session")
    cfg = await EnvProxyProvider().get_proxy()
    assert cfg is not None
    assert cfg.server == "http://proxy.test:8080"
    assert cfg.username == "alice"
    assert cfg.password == "secret"
    assert cfg.rotation == "per_session"


@pytest.mark.asyncio
async def test_env_proxy_returns_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROXY_SERVER", raising=False)
    assert await EnvProxyProvider().get_proxy() is None


@pytest.mark.asyncio
async def test_get_proxy_provider_autoselects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PROXY_SERVER", raising=False)
    set_proxy_provider(None)
    assert isinstance(get_proxy_provider(), NoopProxyProvider)

    set_proxy_provider(None)
    monkeypatch.setenv("PROXY_SERVER", "http://proxy.test:8080")
    assert isinstance(get_proxy_provider(), EnvProxyProvider)


def test_proxy_config_to_playwright_omits_missing_credentials() -> None:
    cfg = ProxyConfig(server="http://proxy.test:8080")
    rendered = cfg.to_playwright()
    assert rendered == {"server": "http://proxy.test:8080"}


def test_env_int_and_bool_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROWSER_POOL_SIZE", "7")
    monkeypatch.setenv("BROWSER_HEADLESS", "false")
    assert browser_mod._env_int("BROWSER_POOL_SIZE", 5) == 7
    assert browser_mod._env_bool("BROWSER_HEADLESS", True) is False
    monkeypatch.setenv("BROWSER_POOL_SIZE", "not-a-number")
    assert browser_mod._env_int("BROWSER_POOL_SIZE", 5) == 5
