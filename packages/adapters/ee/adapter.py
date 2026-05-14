"""Estonia adapter — Äriregister (Centre of Registers and Information Systems).

The Estonian Business Register publishes an open dataset at avaandmed.rik.ee
and a public REST API at https://avaandmed.ariregister.rik.ee/. We use the
public open-data JSON endpoint which is free, no auth.

Identifier: registry code (registrikood), 8 digits.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters._base.http import build_http_client, get_with_retry
from packages.shared.models import (
    AdapterHealth,
    AdapterStatus,
    CompanyDetails,
    CompanyMatch,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_REGCODE_RE = re.compile(r"^\d{8}$")


class EEAdapter(CountryAdapter):
    country_code = "EE"
    country_name = "Estonia"
    identifier_types = [IdentifierType.BUSINESS_ID]
    primary_identifier = IdentifierType.BUSINESS_ID
    requires_api_key = False
    rate_limit_per_minute = 60

    BASE_URL = "https://avaandmed.ariregister.rik.ee/sites/default/files/avaandmed"

    async def health_check(self) -> AdapterHealth:
        # The Estonian open data is published as periodic JSON/CSV dumps rather
        # than a live search API. We mark this adapter as "degraded — open
        # data dump required" so the operator knows.
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": False, "lookup": True, "financials": False},
            notes=(
                "Estonia provides only periodic open-data dumps (no live search). "
                "Lookup by registrikood is possible via inforegister.ee public page; "
                "live API requires Ariregister contract."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        # No free live search API; surface this explicitly.
        return []

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        v = value.strip().replace(" ", "")
        if not _REGCODE_RE.match(v):
            raise InvalidIdentifierError(f"Estonian registrikood must be 8 digits: {value}")
        # Without the paid Ariregister API contract, we cannot retrieve
        # structured details. Return a minimal CompanyDetails with a source URL
        # pointing to the public inforegister page so the UI is still useful.
        return CompanyDetails(
            id=v,
            name="(name not available without Ariregister contract)",
            country="EE",
            identifiers=[
                RegistryIdentifier(type=IdentifierType.BUSINESS_ID, value=v, label="Registrikood"),
            ],
            source_url=f"https://www.inforegister.ee/{v}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        return []
