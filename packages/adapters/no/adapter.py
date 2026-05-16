"""Norway adapter — Brønnøysundregistrene (Brreg).

Free open REST API: https://data.brreg.no/enhetsregisteret/api/
No auth, no rate limit documented (we throttle to 60/min anyway).

Identifier: organisasjonsnummer ("organisasjonsnummer"), 9 digits.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters._base.http import build_http_client, get_with_retry
from packages.parsers.pdf import PDFExtractError, extract_from_url
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

_ORG_RE = re.compile(r"^\d{9}$")


class NOAdapter(CountryAdapter):
    country_code = "NO"
    country_name = "Norway"
    identifier_types = [IdentifierType.ORG_NR]
    primary_identifier = IdentifierType.ORG_NR
    requires_api_key = False
    rate_limit_per_minute = 60

    BASE_URL = "https://data.brreg.no/enhetsregisteret/api"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.BASE_URL) as client:
                resp = await get_with_retry(client, "/enheter", params={"navn": "equinor", "size": 1})
                resp.raise_for_status()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code, name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code, name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": False},
            notes="Financials available via Regnskapsregisteret (PDFs) — not yet wired.",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(client, "/enheter", params={"navn": name, "size": limit})
            resp.raise_for_status()
            data = resp.json()
        out: list[CompanyMatch] = []
        for e in (data.get("_embedded", {}) or {}).get("enheter", [])[:limit]:
            org = e.get("organisasjonsnummer")
            if not org:
                continue
            out.append(
                CompanyMatch(
                    id=org,
                    name=e.get("navn", ""),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(type=IdentifierType.ORG_NR, value=org, label="Org.nr"),
                    ],
                    address=_address(e.get("forretningsadresse") or {}),
                    status=("active" if not e.get("slettedato") else "ceased"),
                    source_url=f"https://w2.brreg.no/enhet/sok/detalj.jsp?orgnr={org}",
                )
            )
        return out

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type != IdentifierType.ORG_NR:
            raise InvalidIdentifierError("NO only supports ORG_NR")
        v = value.strip().replace(" ", "")
        if not _ORG_RE.match(v):
            raise InvalidIdentifierError(f"Norwegian org.nr must be 9 digits: {value}")
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(client, f"/enheter/{v}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        nace = data.get("naeringskode1") or {}
        return CompanyDetails(
            id=v,
            name=data.get("navn", ""),
            country="NO",
            legal_form=(data.get("organisasjonsform") or {}).get("kode"),
            status=("active" if not data.get("slettedato") else "ceased"),
            incorporation_date=_parse_date(data.get("registreringsdatoEnhetsregisteret")),
            dissolution_date=_parse_date(data.get("slettedato")),
            registered_address=_address(data.get("forretningsadresse") or {}),
            nace_codes=[nace["kode"]] if nace.get("kode") else [],
            identifiers=[
                RegistryIdentifier(type=IdentifierType.ORG_NR, value=v, label="Org.nr"),
            ],
            raw=data,
            source_url=f"https://w2.brreg.no/enhet/sok/detalj.jsp?orgnr={v}",
        )

    REGNSKAP_BASE = "https://data.brreg.no/regnskapsregisteret/regnskap"

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        """Fetch the structured Regnskapsregisteret JSON filings index.

        Returns annual-report metadata with `document_url` pointing at the
        Brreg PDF for each year. The PDF text is *not* extracted here — see
        `fetch_financials_with_text` for that.
        """
        v = company_id.strip().replace(" ", "")
        if not _ORG_RE.match(v):
            raise InvalidIdentifierError(f"Norwegian org.nr must be 9 digits: {company_id}")

        async with build_http_client(base_url=self.REGNSKAP_BASE) as client:
            resp = await get_with_retry(client, f"/{v}")
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError:
                return []

        entries = data if isinstance(data, list) else [data]
        out: list[FinancialFiling] = []
        for entry in entries:
            year = _filing_year(entry)
            if year is None:
                continue
            period_end = _parse_date(
                (entry.get("regnskapsperiode") or {}).get("tilDato")
            )
            currency = (entry.get("valuta") or "NOK")
            doc_url = _document_url(v, entry)
            out.append(
                FinancialFiling(
                    company_id=v,
                    year=year,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=period_end,
                    currency=currency,
                    structured_data=entry,
                    document_url=doc_url,
                    document_format="pdf" if doc_url else None,
                    source_url=f"https://w2.brreg.no/kunngjoring/hent_en.jsp?orgnr={v}",
                )
            )
        out.sort(key=lambda f: f.year, reverse=True)
        return out[:years]

    async def fetch_financials_with_text(
        self,
        company_id: str,
        years: int = 3,
        *,
        max_pages: int = 50,
        concurrency: int = 3,
    ) -> list[FinancialFiling]:
        """Like `fetch_financials` but also downloads each PDF and stores
        the extracted text in `structured_data["pdf_text_excerpts"]`.

        Failures to extract a single filing do not abort the batch — they
        are logged and the corresponding filing keeps `structured_data`
        unchanged.
        """
        filings = await self.fetch_financials(company_id, years=years)
        if not filings:
            return filings

        sem = asyncio.Semaphore(max(1, concurrency))

        async def _attach(filing: FinancialFiling) -> None:
            if not filing.document_url or filing.document_format != "pdf":
                return
            async with sem:
                try:
                    text = await extract_from_url(
                        filing.document_url, max_pages=max_pages
                    )
                except PDFExtractError as exc:
                    logger.warning(
                        "PDF text extract failed for %s (%s): %s",
                        filing.document_url, filing.year, exc,
                    )
                    return
                except Exception as exc:
                    logger.warning(
                        "PDF download/parse error for %s: %s",
                        filing.document_url, exc,
                    )
                    return
            base = dict(filing.structured_data or {})
            base["pdf_text_excerpts"] = text[:50000]
            filing.structured_data = base

        await asyncio.gather(*(_attach(f) for f in filings))
        return filings


def _filing_year(entry: dict[str, Any]) -> int | None:
    period = entry.get("regnskapsperiode") or {}
    til = period.get("tilDato") or period.get("fraDato")
    if til:
        d = _parse_date(til)
        if d:
            return d.year
    if entry.get("aar"):
        try:
            return int(entry["aar"])
        except (TypeError, ValueError):
            return None
    return None


def _document_url(org_nr: str, entry: dict[str, Any]) -> str | None:
    # Brreg exposes the PDF via the regnskap document endpoint per filing id.
    filing_id = entry.get("id") or entry.get("regnskapId")
    if filing_id:
        return f"https://data.brreg.no/regnskapsregisteret/regnskap/{org_nr}/{filing_id}/dokumenter"
    links = entry.get("_links") or {}
    for key in ("dokumenter", "dokument", "pdf"):
        link = links.get(key)
        if isinstance(link, dict) and link.get("href"):
            return link["href"]
    return None


def _address(a: dict[str, Any]) -> str | None:
    parts: list[str] = []
    if isinstance(a.get("adresse"), list):
        parts.extend(a["adresse"])
    elif a.get("adresse"):
        parts.append(a["adresse"])
    parts.append(str(a.get("postnummer", "")))
    parts.append(a.get("poststed", ""))
    parts = [p for p in parts if p]
    return ", ".join(parts) or None


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None
