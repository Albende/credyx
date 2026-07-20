"""Chile adapter — GLEIF (registry) + SEC EDGAR (financials).

The two official Chilean registries are unusable for a free, key-free,
programmatic MVP:

- **SII** (Servicio de Impuestos Internos) RUT verifier at
  ``zeus.sii.cl/cvc_cgi/stc/getstc`` answers direct GETs with
  ``alert('Por favor reingrese Captcha'); history.go(-1);`` — a hard
  CAPTCHA wall with no free API.
- **CMF** (Comisión para el Mercado Financiero) publishes listed-company
  IFRS filings but geoblocks non-Chilean egress; its ``api.cmfchile.cl``
  and ``www.cmfchile.cl`` hosts are unreachable from outside CL and the
  financial-statement API additionally requires a registered ``apikey``.

So the live paths use two free, key-free, globally reachable sources:

- **Registry** — GLEIF (``api.gleif.org``). Every Chilean legal entity with
  an LEI carries its **RUT** in ``entity.registeredAs`` (the SII/CMF
  registration authority id). This gives real name search and real
  RUT → company lookup. Coverage is limited to LEI-registered entities
  (listed companies, banks, insurers, funds, large corporates).
- **Financials** — SEC EDGAR. Chilean blue-chips cross-listed in the US
  (Banco de Chile/BCH, SQM, Enel Chile, etc.) file audited IFRS annual
  reports as **Form 20-F**. We resolve the RUT to a legal name via GLEIF,
  match the filer in EDGAR's full-text index, and surface each 20-F as a
  `FinancialFiling` with a document URL that genuinely downloads. Chilean
  issuers with no US listing have no free filing feed and return ``[]``.

Identifier: **RUT** (Rol Único Tributario) — 7-9 numeric digits plus a
Mod-11 check digit ("0"-"9" or "K"), displayed ``XX.XXX.XXX-X``. The RUT
doubles as the corporate tax ID, exposed as the primary `VAT` identifier
with `COMPANY_NUMBER` as an alias.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    BlockedByRegistryError,
    InvalidIdentifierError,
)
from packages.adapters._base.http import build_http_client, get_with_retry
from packages.shared.models import (
    AdapterHealth,
    AdapterStatus,
    CompanyDetails,
    CompanyMatch,
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_RUT_RE = re.compile(r"^(\d{7,9})([0-9K])$")


def _normalize_rut(value: str) -> tuple[str, str]:
    """Strip "CL"/dots/dashes/spaces, return (digits, check_char).

    Validates the Mod-11 checksum and raises `InvalidIdentifierError` on
    bad input. The check char is uppercase "K" or a decimal digit.
    """
    raw = (value or "").strip().upper()
    if raw.startswith("CL"):
        raw = raw[2:]
    cleaned = raw.replace(".", "").replace("-", "").replace(" ", "")
    m = _RUT_RE.match(cleaned)
    if not m:
        raise InvalidIdentifierError(
            f"Chilean RUT must be 7-9 digits + check char (0-9 or K): {value}"
        )
    digits, check = m.group(1), m.group(2)
    expected = _rut_check_digit(digits)
    if expected != check:
        raise InvalidIdentifierError(
            f"RUT check digit invalid for {value}: expected {expected}, got {check}"
        )
    return digits, check


def _rut_check_digit(digits: str) -> str:
    """Compute the Mod-11 check char for a RUT body (digits only)."""
    weights = [2, 3, 4, 5, 6, 7]
    total = 0
    for i, ch in enumerate(reversed(digits)):
        total += int(ch) * weights[i % len(weights)]
    rem = 11 - (total % 11)
    if rem == 11:
        return "0"
    if rem == 10:
        return "K"
    return str(rem)


def _format_rut(digits: str, check: str) -> str:
    n = len(digits)
    if n <= 6:
        body = digits
    elif n <= 9:
        body = digits[: n - 6] + "." + digits[n - 6 : n - 3] + "." + digits[n - 3 :]
        body = body.lstrip(".")
    else:
        body = digits
    return f"{body}-{check}"


class CLAdapter(CountryAdapter):
    country_code = "CL"
    country_name = "Chile"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    GLEIF_BASE = "https://api.gleif.org/api/v1"
    EDGAR_FTS = "https://efts.sec.gov/LATEST/search-index"
    EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions"
    EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"

    async def health_check(self) -> AdapterHealth:
        try:
            async with self._gleif_client() as client:
                resp = await get_with_retry(
                    client,
                    "/lei-records",
                    params={
                        "filter[entity.legalAddress.country]": "CL",
                        "page[size]": 1,
                    },
                )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        ok = resp.status_code == 200
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK if ok else AdapterStatus.DEGRADED,
            capabilities={"search": ok, "lookup": ok, "financials": ok},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Registry via GLEIF (RUT in entity.registeredAs). Financials "
                "via SEC EDGAR 20-F for US-cross-listed Chilean issuers. "
                "SII is CAPTCHA-walled and CMF geoblocks non-CL egress."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        records = await self._gleif_query(
            {
                "filter[entity.legalName]": name,
                "filter[entity.legalAddress.country]": "CL",
                "page[size]": max(1, min(int(limit), 50)),
            }
        )
        matches: list[CompanyMatch] = []
        for record in records:
            entity = _entity(record)
            legal_name = _dig(entity, "legalName", "name")
            if not legal_name:
                continue
            lei = record.get("id") or _dig(record, "attributes", "lei")
            rut = _rut_from_entity(entity)
            matches.append(
                CompanyMatch(
                    id=rut or str(lei),
                    name=legal_name,
                    country="CL",
                    identifiers=_identifiers(rut, lei),
                    address=_format_address(entity.get("legalAddress")),
                    status=_status(entity),
                    source_url=(
                        f"https://search.gleif.org/#/record/{lei}" if lei else None
                    ),
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"CL only supports VAT/COMPANY_NUMBER (RUT), got {id_type}"
            )
        digits, check = _normalize_rut(value)
        rut_display = _format_rut(digits, check)
        rut_key = f"{digits}-{check}"

        records = await self._gleif_query(
            {
                "filter[entity.registeredAs]": rut_key,
                "page[size]": 5,
            }
        )
        record = _first_cl_record(records)
        if record is None:
            return None
        entity = _entity(record)
        legal_name = _dig(entity, "legalName", "name")
        if not legal_name:
            return None
        lei = record.get("id") or _dig(record, "attributes", "lei")
        legal_form = _dig(entity, "legalForm", "id")

        return CompanyDetails(
            id=rut_display,
            name=legal_name,
            country="CL",
            legal_form=str(legal_form) if legal_form else None,
            status=_status(entity),
            registered_address=_format_address(entity.get("legalAddress")),
            identifiers=_identifiers(rut_display, lei),
            raw={
                "rut": rut_display,
                "lei": lei,
                "registeredAt": entity.get("registeredAt"),
                "source": "gleif.api.v1.lei-records",
            },
            source_url=(
                f"https://search.gleif.org/#/record/{lei}" if lei else None
            ),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        digits, check = _normalize_rut(company_id)
        rut_display = _format_rut(digits, check)

        details = await self.lookup_by_identifier(IdentifierType.VAT, rut_display)
        if details is None:
            return []

        cik = await self._edgar_cik_for_name(details.name)
        if cik is None:
            return []
        submissions = await self._edgar_submissions(cik)
        if submissions is None or not _is_chilean_filer(submissions):
            return []

        return _filings_from_submissions(submissions, cik, rut_display, years)

    def _gleif_client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.GLEIF_BASE,
            headers={"Accept": "application/vnd.api+json"},
            timeout=25.0,
        )

    async def _gleif_query(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            async with self._gleif_client() as client:
                resp = await get_with_retry(client, "/lei-records", params=params)
        except httpx.HTTPError as exc:
            raise BlockedByRegistryError(f"GLEIF transport error: {exc}") from exc
        if resp.status_code == 404:
            return []
        if resp.status_code >= 500:
            raise BlockedByRegistryError(f"GLEIF returned HTTP {resp.status_code}")
        return resp.json().get("data") or []

    async def _edgar_cik_for_name(self, name: str) -> str | None:
        """Resolve a Chilean legal name to its EDGAR CIK via the 20-F full-text
        index, picking the filer that appears in the most matching documents."""
        params = {"q": f'"{name}"', "forms": "20-F"}
        async with build_http_client(
            headers={"Accept": "application/json"}, timeout=25.0
        ) as client:
            resp = await get_with_retry(client, self.EDGAR_FTS, params=params)
        if resp.status_code != 200:
            return None
        hits = _dig(resp.json(), "hits", "hits") or []
        counter: Counter[str] = Counter()
        for hit in hits:
            for cik in (_dig(hit, "_source", "ciks") or []):
                counter[str(cik)] += 1
        if not counter:
            return None
        return counter.most_common(1)[0][0]

    async def _edgar_submissions(self, cik: str) -> dict[str, Any] | None:
        cik_padded = str(cik).zfill(10)
        async with build_http_client(
            headers={"Accept": "application/json"}, timeout=25.0
        ) as client:
            resp = await get_with_retry(
                client, f"{self.EDGAR_SUBMISSIONS}/CIK{cik_padded}.json"
            )
        if resp.status_code != 200:
            return None
        return resp.json()


def _entity(record: dict[str, Any]) -> dict[str, Any]:
    return _dig(record, "attributes", "entity") or {}


def _dig(obj: Any, *keys: str) -> Any:
    cur: Any = obj
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
        if cur is None:
            return None
    return cur


def _status(entity: dict[str, Any]) -> str | None:
    raw = (entity.get("status") or "").upper()
    if raw == "ACTIVE":
        return "active"
    return raw.lower() or None


def _rut_from_entity(entity: dict[str, Any]) -> str | None:
    registered_as = entity.get("registeredAs")
    if not registered_as:
        return None
    try:
        digits, check = _normalize_rut(str(registered_as))
    except InvalidIdentifierError:
        return None
    return _format_rut(digits, check)


def _identifiers(rut: str | None, lei: Any) -> list[RegistryIdentifier]:
    out: list[RegistryIdentifier] = []
    if rut:
        out.append(RegistryIdentifier(type=IdentifierType.VAT, value=rut, label="RUT"))
        out.append(
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=rut, label="RUT"
            )
        )
    if lei:
        out.append(RegistryIdentifier(type=IdentifierType.LEI, value=str(lei)))
    return out


def _format_address(address: dict[str, Any] | None) -> str | None:
    if not isinstance(address, dict):
        return None
    parts: list[str] = []
    lines = address.get("addressLines")
    if isinstance(lines, list):
        parts.extend(str(line) for line in lines if line)
    elif isinstance(lines, str) and lines:
        parts.append(lines)
    for key in ("city", "region", "postalCode", "country"):
        val = address.get(key)
        if val:
            parts.append(str(val))
    cleaned = [p.strip() for p in parts if p and str(p).strip()]
    return ", ".join(cleaned) if cleaned else None


def _first_cl_record(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    for record in records:
        if _dig(record, "attributes", "entity", "legalAddress", "country") == "CL":
            return record
    return records[0] if records else None


def _is_chilean_filer(submissions: dict[str, Any]) -> bool:
    for kind in ("business", "mailing"):
        country = _dig(submissions, "addresses", kind, "stateOrCountry")
        if country == "F3":  # EDGAR country code for Chile
            return True
    return False


def _filings_from_submissions(
    submissions: dict[str, Any],
    cik: str,
    rut_display: str,
    years: int,
) -> list[FinancialFiling]:
    recent = _dig(submissions, "filings", "recent") or {}
    forms = recent.get("form") or []
    filing_dates = recent.get("filingDate") or []
    report_dates = recent.get("reportDate") or []
    accessions = recent.get("accessionNumber") or []
    primary_docs = recent.get("primaryDocument") or []

    cik_int = str(int(cik))
    filings: list[FinancialFiling] = []
    for i, form in enumerate(forms):
        if form != "20-F":
            continue
        period_end = _parse_date(report_dates[i]) if i < len(report_dates) else None
        filing_date = _parse_date(filing_dates[i]) if i < len(filing_dates) else None
        year = (period_end or filing_date or date(1900, 1, 1)).year
        if year < 1901:
            continue
        accession = accessions[i] if i < len(accessions) else ""
        acc_nodash = accession.replace("-", "")
        primary = primary_docs[i] if i < len(primary_docs) else ""
        base = f"{CLAdapter.EDGAR_ARCHIVES}/{cik_int}/{acc_nodash}"
        filings.append(
            FinancialFiling(
                company_id=rut_display,
                year=year,
                type=FilingType.ANNUAL_REPORT,
                period_end=period_end,
                currency="CLP",
                structured_data=None,
                document_url=f"{base}/{primary}" if primary else None,
                document_format="html" if primary.endswith((".htm", ".html")) else None,
                source_url=f"{base}/{accession}-index.htm" if accession else base,
            )
        )
        if len(filings) >= max(1, years):
            break
    return filings


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
