"""Singapore adapter — ACRA open data (data.gov.sg) + SGX financial reports.

Two free, no-auth sources are stitched together:

* **data.gov.sg datastore** — ACRA "Information on Corporate Entities". The
  registry is published as a combined roll-up ("Entities Registered with
  ACRA", ~2.1M rows) plus 27 richer per-first-letter slices (A–Z + "Others").
  Search and UEN lookup hit the combined resource; a UEN lookup then routes to
  the matching letter slice to enrich the record with incorporation date,
  SSIC activity, legal form and the full registered address. No financials.
* **SGX (Singapore Exchange)** — `api.sgx.com/financialreports/v1.0` lists
  every financial report filed by SGX-listed issuers (annual reports,
  financial statements) with a `links.sgx.com` announcement URL. We page the
  feed (sorted newest-first), match the issuer by name, then resolve each
  announcement page to its real filed PDF. Unlisted Singapore companies have
  **no free financial source** — ACRA BizFile+ "Business Profile" downloads
  are paid (S$5.50/doc) and excluded from the MVP.

Identifier: **UEN** (Unique Entity Number), 9 or 10 alphanumeric chars.
Common formats (https://www.uen.gov.sg/ueninternet/faces/pages/aboutUEN.jspx):
  - `nnnnnnnnX`        — businesses registered before 2009 (9 chars)
  - `yyyynnnnnX`       — local companies (10 chars, year-prefixed)
  - `TyyPQnnnnX`       — entities issued by other agencies (10 chars).
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterError,
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

logger = logging.getLogger(__name__)

_UEN_RE = re.compile(r"^[A-Z0-9]{9,10}$")

# ACRA datasets removed the missing-value convention "na"; treat it as null.
_NULLISH = {"", "na", "n.a.", "null", "none", "-"}


def _normalize_uen(value: str) -> str:
    cleaned = re.sub(r"\s+", "", value.strip()).upper()
    if not _UEN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Singapore UEN must be 9-10 alphanumeric characters: {value}"
        )
    return cleaned


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if s.lower() in _NULLISH:
        return None
    return s


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().rstrip(".")).upper()


class SGAdapter(CountryAdapter):
    country_code = "SG"
    country_name = "Singapore"
    identifier_types = [IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 60

    DATASTORE = "https://data.gov.sg/api/action/datastore_search"
    # "Entities Registered with ACRA" — combined roll-up covering every UEN.
    COMBINED_RESOURCE_ID = "d_3f960c10fed6145404ca7b821f263b87"
    # Per-first-letter slices with the full attribute set (SSIC, address, …).
    LETTER_RESOURCES: dict[str, str] = {
        "A": "d_8575e84912df3c28995b8e6e0e05205a",
        "B": "d_3a3807c023c61ddfba947dc069eb53f2",
        "C": "d_c0650f23e94c42e7a20921f4c5b75c24",
        "D": "d_acbc938ec77af18f94cecc4a7c9ec720",
        "E": "d_124a9bd407c7a25f8335b93b86e50fdd",
        "F": "d_4526d47d6714d3b052eed4a30b8b1ed6",
        "G": "d_b58303c68e9cf0d2ae93b73ffdbfbfa1",
        "H": "d_fa2ed456cf2b8597bb7e064b08fc3c7c",
        "I": "d_85518d970b8178975850457f60f1e738",
        "J": "d_478f45a9c541cbe679ca55d1cd2b970b",
        "K": "d_5573b0db0575db32190a2ad27919a7aa",
        "L": "d_a2141adf93ec2a3c2ec2837b78d6d46e",
        "M": "d_9af9317c646a1c881bb5591c91817cc6",
        "N": "d_67e99e6eabc4aad9b5d48663b579746a",
        "O": "d_5c4ef48b025fdfbc80056401f06e3df9",
        "P": "d_181005ca270b45408b4cdfc954980ca2",
        "Q": "d_4130f1d9d365d9f1633536e959f62bb7",
        "R": "d_2b8c54b2a490d2fa36b925289e5d9572",
        "S": "d_df7d2d661c0c11a7c367c9ee4bf896c1",
        "T": "d_72f37e5c5d192951ddc5513c2b134482",
        "U": "d_0cc5f52a1f298b916f317800251057f3",
        "V": "d_e97e8e7fc55b85a38babf66b0fa46b73",
        "W": "d_af2042c77ffaf0db5d75561ce9ef5688",
        "X": "d_1cd970d8351b42be4a308d628a6dd9d3",
        "Y": "d_31af23fdb79119ed185c256f03cb5773",
        "Z": "d_4e3db8955fdcda6f9944097bef3d2724",
        "OTHERS": "d_300ddc8da4e8f7bdc1bfc62d0d99e2e7",
    }

    SGX_FINANCIAL_REPORTS = "https://api.sgx.com/financialreports/v1.0"
    SGX_LINKS_BASE = "https://links.sgx.com"
    SGX_REPORT_FIELDS = "id,companyName,documentDate,securityName,title,url"
    SGX_PAGE_SIZE = 2000
    SGX_MAX_PAGES = 8

    BIZFILE_PROFILE_URL = "https://www.bizfile.gov.sg/ngbportal/CitizenSearch/{uen}"

    async def health_check(self) -> AdapterHealth:
        try:
            payload = await self._datastore(
                self.COMBINED_RESOURCE_ID, params={"limit": "1"}
            )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        if not payload.get("success"):
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes="data.gov.sg returned success=false on probe.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Registry via ACRA open data (data.gov.sg). Financials "
                "best-effort: SGX filed reports for listed issuers only; "
                "unlisted firms have no free source (BizFile+ profiles are paid)."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        rows = await self._datastore_records(
            self.COMBINED_RESOURCE_ID,
            params={"q": f'{{"entity_name":"{query}"}}', "limit": str(_bounded(limit))},
        )
        return [_row_to_match(r) for r in rows if _row_uen(r)]

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.COMPANY_NUMBER:
            raise InvalidIdentifierError(
                f"Singapore only supports COMPANY_NUMBER (UEN), got {id_type}"
            )
        uen = _normalize_uen(value)
        rows = await self._datastore_records(
            self.COMBINED_RESOURCE_ID,
            params={"filters": f'{{"uen":"{uen}"}}', "limit": "5"},
        )
        base = _first_uen_match(rows, uen)
        if base is None:
            return None

        enriched = await self._lookup_letter_record(
            uen=uen, name=_row_entity_name(base)
        )
        return _row_to_details(enriched or base)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        uen = _normalize_uen(company_id)
        details = await self.lookup_by_identifier(IdentifierType.COMPANY_NUMBER, uen)
        if details is None or not details.name:
            return []

        needle = _normalize_name(details.name)
        cutoff_year = datetime.utcnow().year - years
        matches = await self._collect_sgx_reports(needle=needle, cutoff_year=cutoff_year)
        if not matches:
            return []

        filings: list[FinancialFiling] = []
        async with build_http_client() as client:
            for row in matches:
                filing = await self._report_to_filing(client, uen=uen, row=row)
                if filing is not None:
                    filings.append(filing)
        filings.sort(key=lambda f: (f.year, f.period_end or date.min), reverse=True)
        return filings

    async def _lookup_letter_record(
        self, *, uen: str, name: str
    ) -> dict[str, Any] | None:
        resource_id = self.LETTER_RESOURCES.get(_letter_bucket(name))
        if not resource_id:
            return None
        try:
            rows = await self._datastore_records(
                resource_id,
                params={"filters": f'{{"uen":"{uen}"}}', "limit": "5"},
            )
        except AdapterError:
            return None
        return _first_uen_match(rows, uen)

    async def _collect_sgx_reports(
        self, *, needle: str, cutoff_year: int
    ) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        async with build_http_client() as client:
            for page in range(self.SGX_MAX_PAGES):
                resp = await get_with_retry(
                    client,
                    self.SGX_FINANCIAL_REPORTS,
                    params={
                        "pagestart": str(page),
                        "pagesize": str(self.SGX_PAGE_SIZE),
                        "params": self.SGX_REPORT_FIELDS,
                    },
                )
                if resp.status_code != 200:
                    break
                try:
                    rows = resp.json().get("data") or []
                except ValueError:
                    break
                if not rows:
                    break

                page_min_year = None
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    year = _report_year(row)
                    if year is not None:
                        page_min_year = year if page_min_year is None else min(page_min_year, year)
                    if year is None or year < cutoff_year:
                        continue
                    if _is_financial_title(row.get("title")) and _report_matches(row, needle):
                        matches.append(row)

                if page_min_year is not None and page_min_year < cutoff_year:
                    break
                if len(rows) < self.SGX_PAGE_SIZE:
                    break
        return matches

    async def _report_to_filing(
        self, client: Any, *, uen: str, row: dict[str, Any]
    ) -> FinancialFiling | None:
        year = _report_year(row)
        if year is None:
            return None
        announcement_url = _clean(row.get("url"))
        document_url = None
        if announcement_url:
            document_url = await self._resolve_pdf(client, announcement_url)
        return FinancialFiling(
            company_id=uen,
            year=year,
            type=_filing_type(str(row.get("title") or "")),
            period_end=None,
            currency=None,
            structured_data=None,
            document_url=document_url,
            document_format="pdf" if document_url else None,
            source_url=announcement_url,
        )

    async def _resolve_pdf(self, client: Any, announcement_url: str) -> str | None:
        try:
            resp = await get_with_retry(client, announcement_url)
            if resp.status_code != 200:
                return None
            html = resp.text
        except Exception as exc:
            logger.debug("SGX announcement fetch failed for %s: %s", announcement_url, exc)
            return None
        match = re.search(r'href="([^"]+\.pdf)"', html, re.IGNORECASE)
        if not match:
            return None
        href = match.group(1)
        if href.startswith("http"):
            return href
        return self.SGX_LINKS_BASE + ("" if href.startswith("/") else "/") + href

    async def _datastore(
        self, resource_id: str, *, params: dict[str, str]
    ) -> dict[str, Any]:
        query = {"resource_id": resource_id, **params}
        async with build_http_client() as client:
            resp = await get_with_retry(client, self.DATASTORE, params=query)
            if resp.status_code == 404:
                raise AdapterError(
                    f"data.gov.sg resource {resource_id} not found — the ACRA "
                    "datasets may have been republished under new UUIDs."
                )
            resp.raise_for_status()
            try:
                return resp.json()
            except ValueError:
                return {}

    async def _datastore_records(
        self, resource_id: str, *, params: dict[str, str]
    ) -> list[dict[str, Any]]:
        payload = await self._datastore(resource_id, params=params)
        if not isinstance(payload, dict) or not payload.get("success"):
            return []
        records = (payload.get("result") or {}).get("records") or []
        return [r for r in records if isinstance(r, dict)]


def _bounded(limit: int) -> int:
    return max(1, min(limit, 100))


def _letter_bucket(name: str) -> str:
    for ch in name.strip().upper():
        if ch.isalpha():
            return ch
        break
    return "OTHERS"


def _row_uen(row: dict[str, Any]) -> str | None:
    return _clean(row.get("uen") or row.get("UEN"))


def _row_entity_name(row: dict[str, Any]) -> str:
    return _clean(row.get("entity_name") or row.get("company_name")) or ""


def _row_status(row: dict[str, Any]) -> str | None:
    return _clean(
        row.get("entity_status_description")
        or row.get("uen_status_desc")
        or row.get("uen_status_description")
        or row.get("status")
    )


def _row_legal_form(row: dict[str, Any]) -> str | None:
    return _clean(
        row.get("company_type_description")
        or row.get("entity_type_description")
        or row.get("entity_type_desc")
    )


def _row_address(row: dict[str, Any]) -> str | None:
    parts = [
        row.get("block"),
        row.get("street_name") or row.get("reg_street_name"),
        row.get("level_no"),
        row.get("unit_no"),
        row.get("building_name"),
        row.get("postal_code") or row.get("reg_postal_code"),
    ]
    cleaned = [c for c in (_clean(p) for p in parts) if c]
    joined = " ".join(cleaned)
    return joined or None


def _row_to_match(row: dict[str, Any]) -> CompanyMatch:
    uen = _row_uen(row) or ""
    return CompanyMatch(
        id=uen,
        name=_row_entity_name(row),
        country="SG",
        identifiers=[
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=uen, label="UEN"
            ),
        ],
        address=_row_address(row),
        status=_row_status(row),
        source_url=SGAdapter.BIZFILE_PROFILE_URL.format(uen=uen) if uen else None,
    )


def _row_to_details(row: dict[str, Any]) -> CompanyDetails:
    uen = _row_uen(row) or ""
    inc = _parse_iso_date(
        row.get("registration_incorporation_date") or row.get("uen_issue_date")
    )
    ssic = _clean(row.get("primary_ssic_code"))
    return CompanyDetails(
        id=uen,
        name=_row_entity_name(row),
        country="SG",
        legal_form=_row_legal_form(row),
        status=_row_status(row),
        incorporation_date=inc,
        dissolution_date=None,
        registered_address=_row_address(row),
        capital_amount=None,
        capital_currency="SGD",
        sic_codes=[ssic] if ssic else [],
        identifiers=[
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=uen, label="UEN"
            ),
        ],
        raw=row,
        source_url=SGAdapter.BIZFILE_PROFILE_URL.format(uen=uen) if uen else None,
    )


def _first_uen_match(rows: list[dict[str, Any]], uen: str) -> dict[str, Any] | None:
    for r in rows:
        if (_row_uen(r) or "") == uen:
            return r
    return None


def _report_matches(row: dict[str, Any], needle: str) -> bool:
    for key in ("companyName", "securityName"):
        candidate = _clean(row.get(key))
        if not candidate:
            continue
        norm = _normalize_name(candidate)
        if norm == needle or needle in norm or norm in needle:
            return True
    return False


_FINANCIAL_TITLE_KEYWORDS = (
    "annual report",
    "financial statement",
    "full year",
    "half year",
    "quarter",
    "results",
    "balance sheet",
    "profit and loss",
    "income statement",
    "cash flow",
    "audit",
)


def _is_financial_title(title: Any) -> bool:
    t = (_clean(title) or "").lower()
    return any(kw in t for kw in _FINANCIAL_TITLE_KEYWORDS)


def _filing_type(title: str) -> FilingType:
    t = title.lower()
    if "audit" in t:
        return FilingType.AUDIT_REPORT
    if "director" in t:
        return FilingType.DIRECTORS_REPORT
    if "balance sheet" in t:
        return FilingType.BALANCE_SHEET
    if "cash flow" in t:
        return FilingType.CASH_FLOW
    if "profit" in t or "income statement" in t:
        return FilingType.PROFIT_AND_LOSS
    return FilingType.ANNUAL_REPORT


def _report_year(row: dict[str, Any]) -> int | None:
    ts = row.get("documentDate")
    if ts is None:
        return None
    try:
        return datetime.utcfromtimestamp(int(ts) / 1000).year
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _parse_iso_date(value: Any) -> date | None:
    s = _clean(value)
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        if len(s) >= 10 and s[2] == "/" and s[5] == "/":
            try:
                return date(int(s[6:10]), int(s[3:5]), int(s[0:2]))
            except ValueError:
                return None
        return None
