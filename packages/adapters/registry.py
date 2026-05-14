"""Country adapter registry.

Returns the right CountryAdapter for an ISO 3166-1 alpha-2 country code. Real
adapters live in `packages.adapters.{cc}`; everything else falls through to
NotImplementedAdapter so the API surface stays consistent.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Callable

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._stubs import build_stub_registry


def _build_real_adapters() -> dict[str, CountryAdapter]:
    # Lazy import here so each adapter's __init__ doesn't run at module load
    # for countries we don't need.
    from packages.adapters.cz import CZAdapter
    from packages.adapters.ee import EEAdapter
    from packages.adapters.fi import FIAdapter
    from packages.adapters.fr import FRAdapter
    from packages.adapters.nl import NLAdapter
    from packages.adapters.no import NOAdapter
    from packages.adapters.uk import UKAdapter
    from packages.adapters.us import USAdapter

    return {
        "GB": UKAdapter(),
        "UK": UKAdapter(),  # alias
        "US": USAdapter(),
        "FR": FRAdapter(),
        "NL": NLAdapter(),
        "CZ": CZAdapter(),
        "EE": EEAdapter(),
        "NO": NOAdapter(),
        "FI": FIAdapter(),
    }


@lru_cache(maxsize=1)
def get_adapter_registry() -> dict[str, CountryAdapter]:
    """Return the full registry: real adapters override stubs."""
    registry: dict[str, CountryAdapter] = {}
    for cc, stub in build_stub_registry().items():
        registry[cc.upper()] = stub
    for cc, real in _build_real_adapters().items():
        registry[cc.upper()] = real
    return registry


def get_adapter(country_code: str) -> CountryAdapter | None:
    return get_adapter_registry().get(country_code.upper())


def reset_registry() -> None:
    """Test helper — drop the cache."""
    get_adapter_registry.cache_clear()
