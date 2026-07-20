"""Switzerland adapter — Zefix (Central Business Names Index).

Free REST API: https://www.zefix.admin.ch/ZefixPublicREST/
- JSON in/out. Since 2026 the PublicREST API requires (free) registration:
  request HTTP Basic credentials by emailing zefix@bj.admin.ch, then set
  ``CH_ZEFIX_USERNAME`` / ``CH_ZEFIX_PASSWORD``.
- Covers every Swiss legal entity in the federal commercial register.
- Identifiers: UID (Unique Identification, format CHE-XXX.XXX.XXX) and the
  optional VAT suffix (e.g. ``CHE-105.927.350 MWST``). The UID and the
  registered VAT number share the same 9-digit core.

Filed annual accounts are not centrally published: only listed issuers post
them on SIX (https://www.six-group.com/). For everyone else there is no free
public balance-sheet source — ``fetch_financials`` returns an empty list and
the SIX hint is surfaced in ``health_check.notes``.
"""
from __future__ import annotations

import os
import re
from datetime import date
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import AdapterError, InvalidIdentifierError
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

_UID_DIGITS_RE = re.compile(r"^\d{9}$")


def _normalize_uid(value: str) -> str:
    """Strip CHE/VAT decoration and return the 9-digit UID core."""
    s = value.strip().upper()
    for tag in (" MWST", " TVA", " IVA", " HR", " HR/MWST"):
        if s.endswith(tag):
            s = s[: -len(tag)]
    s = s.replace("CHE", "").replace("-", "").replace(".", "").replace(" ", "")
    if not _UID_DIGITS_RE.match(s):
        raise InvalidIdentifierError(
            f"Swiss UID must be 9 digits (e.g. CHE-105.927.350): {value}"
        )
    return s


def _format_uid(core: str) -> str:
    return f"CHE-{core[0:3]}.{core[3:6]}.{core[6:9]}"


_REGISTRATION_HINT = (
    "Zefix PublicREST requires free registration since 2026: request HTTP "
    "Basic credentials from zefix@bj.admin.ch (see "
    "https://www.zefix.admin.ch/ZefixPublicREST/swagger-ui/index.html), then "
    "set CH_ZEFIX_USERNAME and CH_ZEFIX_PASSWORD."
)


class CHAdapter(CountryAdapter):
    country_code = "CH"
    country_name = "Switzerland"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = True
    api_key_env = "CH_ZEFIX_USERNAME"
    rate_limit_per_minute = 60

    BASE_URL = "https://www.zefix.admin.ch/ZefixPublicREST"

    def _basic_auth(self) -> tuple[str, str]:
        username = os.getenv("CH_ZEFIX_USERNAME")
        password = os.getenv("CH_ZEFIX_PASSWORD")
        if not username or not password:
            raise AdapterError(f"Missing Zefix credentials. {_REGISTRATION_HINT}")
        return (username, password)

    async def health_check(self) -> AdapterHealth:
        if not (os.getenv("CH_ZEFIX_USERNAME") and os.getenv("CH_ZEFIX_PASSWORD")):
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=True,
                api_key_present=False,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=_REGISTRATION_HINT,
            )
        try:
            async with build_http_client(
                base_url=self.BASE_URL, auth=self._basic_auth()
            ) as client:
                resp = await client.post(
                    "/api/v1/company/search",
                    json={"name": "Nestle", "languageKey": "en"},
                    headers={"Accept": "application/json"},
                )
                if resp.status_code == 401:
                    raise AdapterError(
                        f"Zefix rejected the credentials (401). {_REGISTRATION_HINT}"
                    )
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=True,
                api_key_present=True,
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": False},
            requires_api_key=True,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes="Filed accounts only public for SIX-listed issuers; non-listed returns [].",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        async with build_http_client(
            base_url=self.BASE_URL, auth=self._basic_auth()
        ) as client:
            resp = await client.post(
                "/api/v1/company/search",
                json={"name": name, "languageKey": "en"},
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 401:
                raise AdapterError(
                    f"Zefix rejected the credentials (401). {_REGISTRATION_HINT}"
                )
            resp.raise_for_status()
            data = resp.json()

        items = _result_list(data)
        out: list[CompanyMatch] = []
        for item in items[:limit]:
            uid_core = _extract_uid_core(item)
            if not uid_core:
                continue
            out.append(
                CompanyMatch(
                    id=uid_core,
                    name=item.get("name") or "",
                    country=self.country_code,
                    identifiers=_identifiers_for(uid_core),
                    address=_address(item.get("address") or {}),
                    status=_status(item),
                    source_url=f"https://www.zefix.ch/en/search/entity/list/firm/{_format_uid(uid_core)}",
                )
            )
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"CH only supports VAT (UID) and COMPANY_NUMBER, got {id_type}"
            )
        core = _normalize_uid(value)
        formatted = _format_uid(core)
        async with build_http_client(
            base_url=self.BASE_URL, auth=self._basic_auth()
        ) as client:
            resp = await get_with_retry(
                client,
                f"/api/v1/company/uid/{formatted}",
                headers={"Accept": "application/json"},
            )
            if resp.status_code == 404:
                return None
            if resp.status_code == 401:
                raise AdapterError(
                    f"Zefix rejected the credentials (401). {_REGISTRATION_HINT}"
                )
            resp.raise_for_status()
            payload = resp.json()

        record = _first_record(payload)
        if not record:
            return None

        return CompanyDetails(
            id=core,
            name=record.get("name", ""),
            country="CH",
            legal_form=_legal_form(record),
            status=_status(record),
            incorporation_date=_parse_date(record.get("sogcDate"))
            or _parse_date(record.get("chRegisterEntryDate")),
            dissolution_date=_parse_date(record.get("deleteDate")),
            registered_address=_address(record.get("address") or {}),
            capital_amount=_capital_amount(record),
            capital_currency=_capital_currency(record),
            nace_codes=_nace_codes(record),
            identifiers=_identifiers_for(core),
            raw=record,
            source_url=f"https://www.zefix.ch/en/search/entity/list/firm/{formatted}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # Zefix does not publish balance sheets. SIX Swiss Exchange publishes
        # annual reports for listed issuers only and there is no machine-readable
        # filings index — wiring that requires per-issuer scraping (deferred).
        return []


def _result_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("list", "results", "companies", "_embedded"):
            v = data.get(key)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                inner = v.get("companies") or v.get("list")
                if isinstance(inner, list):
                    return inner
    return []


def _first_record(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, list):
        return payload[0] if payload else None
    if isinstance(payload, dict):
        for key in ("company", "data"):
            v = payload.get(key)
            if isinstance(v, dict):
                return v
            if isinstance(v, list) and v:
                return v[0]
        return payload
    return None


def _extract_uid_core(item: dict[str, Any]) -> str | None:
    raw = item.get("uid") or item.get("uidFormatted") or ""
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    return digits if len(digits) == 9 else None


def _identifiers_for(core: str) -> list[RegistryIdentifier]:
    formatted = _format_uid(core)
    return [
        RegistryIdentifier(
            type=IdentifierType.COMPANY_NUMBER, value=formatted, label="UID"
        ),
        RegistryIdentifier(
            type=IdentifierType.VAT, value=f"{formatted} MWST", label="MWST / TVA / IVA"
        ),
    ]


def _address(a: dict[str, Any]) -> str | None:
    parts = [
        a.get("street"),
        a.get("houseNumber"),
        a.get("addressLine1"),
        a.get("addressLine2"),
        a.get("swissZipCode") or a.get("zipCode") or a.get("swissZipCodeAddOn"),
        a.get("town") or a.get("city"),
        a.get("country"),
    ]
    parts = [str(p).strip() for p in parts if p]
    return ", ".join(parts) or None


def _status(item: dict[str, Any]) -> str | None:
    if item.get("deleteDate"):
        return "ceased"
    s = item.get("status")
    if isinstance(s, str):
        return s.lower()
    if item.get("canBeDeleted") is False:
        return "active"
    return "active"


def _legal_form(record: dict[str, Any]) -> str | None:
    lf = record.get("legalForm")
    if isinstance(lf, dict):
        names = lf.get("name") or {}
        if isinstance(names, dict):
            return names.get("en") or names.get("de") or names.get("fr") or names.get("it")
        if isinstance(names, str):
            return names
        return lf.get("shortName") or lf.get("id")
    if isinstance(lf, str):
        return lf
    return None


def _capital_amount(record: dict[str, Any]) -> float | None:
    cap = record.get("capitalNominal") or record.get("capital")
    if isinstance(cap, dict):
        cap = cap.get("amount")
    try:
        return float(cap) if cap is not None else None
    except (TypeError, ValueError):
        return None


def _capital_currency(record: dict[str, Any]) -> str | None:
    cur = record.get("capitalCurrency")
    if isinstance(cur, str) and cur:
        return cur
    cap = record.get("capitalNominal") or record.get("capital")
    if isinstance(cap, dict):
        return cap.get("currency") or "CHF"
    return "CHF"


def _nace_codes(record: dict[str, Any]) -> list[str]:
    purpose = record.get("purpose") or {}
    codes: list[str] = []
    if isinstance(purpose, dict):
        for v in purpose.values():
            if isinstance(v, str):
                codes.extend(re.findall(r"\b\d{2,4}\b", v))
    return list(dict.fromkeys(codes))[:5]


def _parse_date(s: Any) -> date | None:
    if not s or not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None
