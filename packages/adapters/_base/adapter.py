"""Base adapter interface every country plug-in must implement.

Adapters MUST NOT return mock data. If a data source is unimplemented, raise
`AdapterNotImplementedError` — the API surface translates that into a 501 with
status `not_implemented`. This is a non-negotiable rule from the spec.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from datetime import datetime

from packages.adapters._base.errors import AdapterNotImplementedError
from packages.shared.models import (
    AdapterHealth,
    AdapterStatus,
    CompanyDetails,
    CompanyMatch,
    FinancialFiling,
    IdentifierType,
)


class CountryAdapter(ABC):
    """Per-country data source plug-in."""

    country_code: str = ""  # ISO 3166-1 alpha-2 upper
    country_name: str = ""
    identifier_types: list[IdentifierType] = []
    primary_identifier: IdentifierType | None = None
    requires_api_key: bool = False
    api_key_env: str | None = None
    rate_limit_per_minute: int = 60

    @abstractmethod
    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        """Search the registry for companies matching `name`."""

    @abstractmethod
    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        """Fetch the full registry record for a single company by identifier."""

    @abstractmethod
    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        """Fetch all available filed balance sheets / annual reports."""

    async def health_check(self) -> AdapterHealth:
        """Default health check. Subclasses override for live probes."""
        api_key_present = (
            bool(os.getenv(self.api_key_env)) if self.api_key_env else True
        )
        status = AdapterStatus.OK
        notes: str | None = None
        if self.requires_api_key and not api_key_present:
            status = AdapterStatus.DEGRADED
            notes = f"Missing env var {self.api_key_env}"
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name or self.country_code,
            status=status,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=self.requires_api_key,
            api_key_present=api_key_present,
            rate_limit_per_minute=self.rate_limit_per_minute,
            last_checked_at=datetime.utcnow(),
            notes=notes,
        )


class NotImplementedAdapter(CountryAdapter):
    """Default stub for countries we haven't implemented yet.

    Honors the spec rule: never return mock data — raise
    `AdapterNotImplementedError` instead.
    """

    def __init__(
        self,
        country_code: str,
        country_name: str,
        *,
        identifier_types: list[IdentifierType] | None = None,
        notes: str | None = None,
    ) -> None:
        self.country_code = country_code.upper()
        self.country_name = country_name
        self.identifier_types = identifier_types or []
        self._notes = notes or "Adapter not implemented yet."

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(self._notes)

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        raise AdapterNotImplementedError(self._notes)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        raise AdapterNotImplementedError(self._notes)

    async def health_check(self) -> AdapterHealth:
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.NOT_IMPLEMENTED,
            capabilities={"search": False, "lookup": False, "financials": False},
            requires_api_key=False,
            api_key_present=False,
            notes=self._notes,
        )
