"""Proxy interface for adapter HTTP / browser traffic.

The MVP runs without proxies. This module defines the contract so paid
providers (Bright Data, Oxylabs, Smartproxy, etc.) can be slotted in
later behind a single `ProxyProvider.get_proxy()` call. The browser pool
and (future) httpx clients ask for a `ProxyConfig` per request or per
session; if the provider returns `None`, the caller proceeds direct.

Non-negotiable: no provider implementation here makes a paid API call.
Real provider plug-ins live outside this file.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, Field

RotationMode = Literal["per_request", "per_session"]


class ProxyConfig(BaseModel):
    """Resolved proxy connection details ready to feed Playwright/httpx."""

    server: str = Field(
        description=(
            "Proxy server URL including scheme + port, e.g. "
            "'http://proxy.example.com:22225' or 'socks5://10.0.0.1:1080'."
        ),
    )
    username: str | None = None
    password: str | None = None
    rotation: RotationMode = "per_request"

    def to_playwright(self) -> dict[str, str]:
        """Render as a Playwright `proxy=` kwarg dict."""
        out: dict[str, str] = {"server": self.server}
        if self.username is not None:
            out["username"] = self.username
        if self.password is not None:
            out["password"] = self.password
        return out


class ProxyProvider(ABC):
    """Strategy for resolving a `ProxyConfig` per call site."""

    @abstractmethod
    async def get_proxy(
        self, *, country: str | None = None
    ) -> ProxyConfig | None:
        """Return a proxy to use, or `None` for a direct connection."""


class NoopProxyProvider(ProxyProvider):
    """Default provider — every adapter goes direct."""

    async def get_proxy(
        self, *, country: str | None = None
    ) -> ProxyConfig | None:
        return None


class EnvProxyProvider(ProxyProvider):
    """Read a single static proxy out of environment variables.

    Inspects `PROXY_SERVER`, `PROXY_USER`, `PROXY_PASS`, and
    `PROXY_ROTATION` (defaults to `per_request`). Returns `None` if
    `PROXY_SERVER` is unset.
    """

    async def get_proxy(
        self, *, country: str | None = None
    ) -> ProxyConfig | None:
        server = os.getenv("PROXY_SERVER")
        if not server:
            return None
        rotation = os.getenv("PROXY_ROTATION", "per_request")
        if rotation not in ("per_request", "per_session"):
            rotation = "per_request"
        return ProxyConfig(
            server=server,
            username=os.getenv("PROXY_USER"),
            password=os.getenv("PROXY_PASS"),
            rotation=rotation,  # type: ignore[arg-type]
        )


_provider_singleton: ProxyProvider | None = None


def get_proxy_provider() -> ProxyProvider:
    """Return the process-wide proxy provider.

    Auto-selects `EnvProxyProvider` when `PROXY_SERVER` is set, otherwise
    `NoopProxyProvider`. Override with `set_proxy_provider()` in tests or
    when wiring a paid backend.
    """
    global _provider_singleton
    if _provider_singleton is not None:
        return _provider_singleton
    if os.getenv("PROXY_SERVER"):
        _provider_singleton = EnvProxyProvider()
    else:
        _provider_singleton = NoopProxyProvider()
    return _provider_singleton


def set_proxy_provider(provider: ProxyProvider | None) -> None:
    """Swap the singleton. `None` resets to the auto-detected default."""
    global _provider_singleton
    _provider_singleton = provider
