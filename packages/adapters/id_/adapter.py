"""Indonesia adapter — AHU Online + OSS + IDX (best-effort).

Three free, no-auth public sources are stitched together here:

* AHU Online (Direktorat Jenderal Administrasi Hukum Umum,
  https://ahu.go.id) — the Ministry of Law's public legal-entity portal.
  The public web pages allow searching companies by name and by NIB. The
  site is SPA-heavy and the underlying JSON is undocumented; we probe it
  best-effort and fall back to ``AdapterNotImplementedError`` if the
  endpoints reject or block us.
* OSS (Online Single Submission, https://oss.go.id) — BKPM's licensing
  portal that issues the NIB (Nomor Induk Berusaha). Public lookups are
  partial; we synthesize the canonical landing URL for a known NIB so the
  downstream UI can deep-link, but we do not invent payload data.
* IDX (Indonesia Stock Exchange, https://www.idx.co.id) — annual reports
  for listed issuers, freely available per-ticker. We emit the canonical
  report URL when the per-symbol landing page actually returns 200.
  Unlisted firms return ``[]``.

Identifiers:
  * **NPWP** (Nomor Pokok Wajib Pajak) — the 15-digit Indonesian tax ID
    issued by the Directorate General of Taxes. Canonical display form is
    ``XX.XXX.XXX.X-XXX.XXX`` but the digits are the source of truth.
    Mapped to ``IdentifierType.VAT``.
  * **NIB** (Nomor Induk Berusaha) — the 13-digit business identification
    number issued by OSS / BKPM. Mapped to ``IdentifierType.COMPANY_NUMBER``.

Free official Indonesian sources do not expose unlisted-company financials
— that data sits behind paid OJK / commercial registry products which the
MVP does not consume.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters._base.http import build_http_client, get_with_retry
from packages.shared.models import (
    AdapterHealth,
    AdapterStatus,
    CompanyDetails,
    CompanyMatch,
    Director,
    FilingType,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

_NPWP_RE = re.compile(r"^\d{15}$")
_NIB_RE = re.compile(r"^\d{13}$")


def _normalize_npwp(value: str) -> str:
    """Strip dots, dashes, spaces; require exactly 15 digits.

    Accepts both raw 15-digit strings and the formatted
    ``XX.XXX.XXX.X-XXX.XXX`` display form.
    """
    if value is None:
        raise InvalidIdentifierError("Indonesia NPWP cannot be empty")
    cleaned = re.sub(r"[\s\-.]", "", str(value).strip())
    if cleaned.upper().startswith("ID"):
        cleaned = cleaned[2:]
    if not _NPWP_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Indonesia NPWP must be exactly 15 digits, got: {value}"
        )
    return cleaned


def _format_npwp(npwp: str) -> str:
    """Return the canonical ``XX.XXX.XXX.X-XXX.XXX`` display form."""
    return f"{npwp[0:2]}.{npwp[2:5]}.{npwp[5:8]}.{npwp[8:9]}-{npwp[9:12]}.{npwp[12:15]}"


def _normalize_nib(value: str) -> str:
    """Strip whitespace and require exactly 13 digits."""
    if value is None:
        raise InvalidIdentifierError("Indonesia NIB cannot be empty")
    cleaned = re.sub(r"[\s\-.]", "", str(value).strip())
    if not _NIB_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Indonesia NIB must be exactly 13 digits, got: {value}"
        )
    return cleaned


def _parse_id_date(s: Any) -> date | None:
    """Accept ISO ``YYYY-MM-DD`` and Indonesian ``DD/MM/YYYY`` / ``DD-MM-YYYY``.

    Anything else returns ``None`` — we never guess.
    """
    if not s:
        return None
    raw = str(s).strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        pass
    m = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$", raw)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            return None
    return None


def _coerce_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(str(v).replace(",", "").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def _pick(r: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        v = r.get(k)
        if v not in (None, ""):
            return v
    return None


class IDAdapter(CountryAdapter):
    country_code = "ID"
    country_name = "Indonesia"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    rate_limit_per_minute = 30

    AHU_BASE = "https://ahu.go.id"
    OSS_BASE = "https://oss.go.id"
    IDX_BASE = "https://www.idx.co.id"

    def _ahu_headers(self) -> dict[str, str]:
        # AHU's SPA shell rejects bare requests; mimic a browser-style
        # Accept stack so its frontend resources answer normally.
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "id;q=0.9, en;q=0.8",
            "Referer": f"{self.AHU_BASE}/",
        }

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(
                base_url=self.AHU_BASE, headers=self._ahu_headers(), timeout=15.0
            ) as client:
                resp = await get_with_retry(client, "/")
                if resp.status_code >= 500:
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.ERROR,
                        capabilities={"search": False, "lookup": False, "financials": False},
                        notes=f"ahu.go.id HTTP {resp.status_code}",
                    )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.DEGRADED,
            capabilities={"search": False, "lookup": False, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "AHU portal reachable but its public name/NIB search has no "
                "stable JSON API — search and lookup raise 501. Financials "
                "best-effort via IDX for listed issuers only."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        # AHU's public name search runs entirely client-side over a
        # tokenized SPA backend — no documented JSON endpoint that we are
        # allowed to consume. Rather than fake the result, surface 501.
        raise AdapterNotImplementedError(
            "Indonesia AHU does not expose a stable free JSON search endpoint. "
            "See docs/countries/id.md."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            npwp = _normalize_npwp(value)
            raise AdapterNotImplementedError(
                "Indonesia DJP/AHU do not expose a free per-NPWP lookup endpoint; "
                f"NPWP {_format_npwp(npwp)} cannot be resolved without a paid "
                "commercial registry. See docs/countries/id.md."
            )
        if id_type == IdentifierType.COMPANY_NUMBER:
            nib = _normalize_nib(value)
            raise AdapterNotImplementedError(
                "Indonesia OSS does not expose a free per-NIB JSON lookup endpoint; "
                f"NIB {nib} cannot be resolved without authenticated OSS access. "
                "See docs/countries/id.md."
            )
        raise InvalidIdentifierError(
            f"Indonesia supports VAT (NPWP) or COMPANY_NUMBER (NIB), got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # ``company_id`` for ID is the raw NPWP. Without a free
        # NPWP→ticker mapping there is no way to derive the IDX symbol —
        # we accept an explicit ``IDX:`` prefix as an opt-in hint.
        cleaned = str(company_id or "").strip()
        symbol: str | None = None
        if cleaned.upper().startswith("IDX:"):
            candidate = cleaned[4:].strip().upper()
            if re.match(r"^[A-Z]{2,5}$", candidate):
                symbol = candidate
        else:
            # Still validate the underlying identifier shape so callers
            # using a bare NPWP/NIB get a typed error rather than a 200.
            digits = re.sub(r"[\s\-.]", "", cleaned)
            if not (_NPWP_RE.match(digits) or _NIB_RE.match(digits)):
                raise InvalidIdentifierError(
                    "Indonesia company_id must be a 15-digit NPWP, 13-digit NIB, "
                    f"or an explicit 'IDX:{{symbol}}' hint; got: {company_id}"
                )

        if not symbol:
            return []

        filings: list[FinancialFiling] = []
        current_year = datetime.utcnow().year
        async with build_http_client(timeout=15.0) as client:
            landing = (
                f"{self.IDX_BASE}/en-us/listed-companies/company-profiles/"
                f"?kodeEmiten={symbol}"
            )
            try:
                probe = await client.get(landing)
            except (httpx.TransportError, httpx.TimeoutException):
                return []
            if probe.status_code != 200:
                return []
            # IDX's per-symbol financial report index lives under the same
            # SPA shell. We emit one filing per year over the requested
            # window and let downstream PDF ingestion pull the actual
            # statements — we never claim numeric data here.
            for year in range(current_year - years, current_year):
                filings.append(
                    FinancialFiling(
                        company_id=cleaned,
                        year=year,
                        type=FilingType.ANNUAL_REPORT,
                        period_end=date(year, 12, 31),
                        currency="IDR",
                        document_url=(
                            f"{self.IDX_BASE}/en-us/listed-companies/"
                            f"financial-statements-and-annual-report/"
                            f"?kodeEmiten={symbol}&year={year}"
                        ),
                        document_format="html",
                        source_url=landing,
                    )
                )
        return filings
