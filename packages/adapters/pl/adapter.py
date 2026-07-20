"""Poland adapter — KRS (Ministry of Justice) + Biała Lista (Ministry of Finance).

Free, no auth, two stitched sources:

- KRS REST `https://api-krs.ms.gov.pl/api/krs/OdpisAktualny/{krs}?rejestr=P|S`
  returns the full registry extract for a company (name, address, capital,
  NIP/REGON, NACE/PKD, governing bodies). Personal-data fields (PESEL,
  surnames of board members) are masked by the registry itself.

- Biała Lista (white list of VAT payers)
  `https://wl-api.mf.gov.pl/api/search/nip/{nip}?date=YYYY-MM-DD` resolves a
  NIP / VAT number to the matching KRS, plus VAT status and bank accounts.

Identifiers supported:
    KRS    — 10-digit court registry number (primary).
    NIP    — 10-digit tax id; same value as the Polish VAT number with a "PL"
             prefix. Treated as both NIP and VAT here.
    REGON  — 9 or 14-digit statistical id; GUS BIR API would be the canonical
             resolver but requires a free key with manual approval, so we only
             accept REGON values that we can also pull out of the KRS payload.

Limitations (see docs/countries/pl.md):

- Name search is not exposed by the KRS REST API. The public web search
  (`wyszukiwarka-krs.ms.gov.pl`) sits behind a bot-detection layer and a
  session form, so it cannot be hit reliably with httpx. We raise
  `AdapterNotImplementedError` for `search_by_name` rather than ship a
  brittle scrape.
- Financial filings (sprawozdania finansowe) are published on
  `ekrs.ms.gov.pl/rdf/pd/` but the host enforces Incapsula JS challenges
  that block plain HTTP clients. `fetch_financials` returns `[]` and the
  CompanyDetails carries the public RDF URL so the UI can deep-link out.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)

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

_KRS_RE = re.compile(r"^\d{10}$")
_NIP_RE = re.compile(r"^\d{10}$")
_REGON_RE = re.compile(r"^\d{9}(?:\d{5})?$")
_NIP_WEIGHTS = (6, 5, 7, 2, 3, 4, 5, 6, 7)


def _normalize_krs(value: str) -> str:
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if cleaned.isdigit():
        cleaned = cleaned.zfill(10)
    if not _KRS_RE.match(cleaned):
        raise InvalidIdentifierError(f"KRS must be 10 digits: {value}")
    return cleaned


def _normalize_nip(value: str) -> str:
    cleaned = value.strip().replace(" ", "").replace("-", "").upper()
    if cleaned.startswith("PL"):
        cleaned = cleaned[2:]
    if not _NIP_RE.match(cleaned):
        raise InvalidIdentifierError(f"NIP must be 10 digits: {value}")
    checksum = sum(int(d) * w for d, w in zip(cleaned[:9], _NIP_WEIGHTS)) % 11
    if checksum == 10 or checksum != int(cleaned[9]):
        raise InvalidIdentifierError(f"NIP checksum failed: {value}")
    return cleaned


def _normalize_regon(value: str) -> str:
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if not _REGON_RE.match(cleaned):
        raise InvalidIdentifierError(f"REGON must be 9 or 14 digits: {value}")
    return cleaned


class PLAdapter(CountryAdapter):
    country_code = "PL"
    country_name = "Poland"
    identifier_types = [
        IdentifierType.KRS,
        IdentifierType.NIP,
        IdentifierType.VAT,
        IdentifierType.REGON,
    ]
    primary_identifier = IdentifierType.KRS
    requires_api_key = False
    rate_limit_per_minute = 60

    KRS_BASE_URL = "https://api-krs.ms.gov.pl/api/krs"
    WL_BASE_URL = "https://wl-api.mf.gov.pl/api"
    MSIG_BASE_URL = "https://wyszukiwarka-msig.ms.gov.pl/api"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.KRS_BASE_URL) as client:
                resp = await get_with_retry(
                    client,
                    "/OdpisAktualny/0000028860",
                    params={"rejestr": "P", "format": "json"},
                )
                resp.raise_for_status()
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
            status=AdapterStatus.OK,
            capabilities={"search": False, "lookup": True, "financials": False},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Name search not exposed by KRS REST (web search behind bot "
                "wall); filings on ekrs.ms.gov.pl behind Incapsula — both "
                "tracked in docs/countries/pl.md."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        from packages.adapters._base.browser import get_browser_pool

        pool = get_browser_pool()
        async with pool.acquire() as ctx:
            page = await ctx.new_page()
            try:
                await page.goto(
                    "https://wyszukiwarka-krs.ms.gov.pl/",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                await page.get_by_role("textbox", name="Nazwa / Firma").fill(name)
                await page.get_by_role("button", name="Wyszukaj").first.click()
                # Wait for either "Brak danych" (no results) or rows containing a 10-digit KRS.
                await page.wait_for_function(
                    """() => {
                        const txt = document.body.innerText;
                        if (txt.includes('Brak danych')) return true;
                        return /\\b0\\d{9}\\b/.test(txt);
                    }""",
                    timeout=25000,
                )
                rows_data = await page.evaluate(
                    """() => {
                        const out = [];
                        for (const tr of document.querySelectorAll('table tbody tr')) {
                            const cells = {};
                            for (const td of tr.querySelectorAll('td')) {
                                const title = td.querySelector('.ds-column-title');
                                const value = td.querySelector('.ds-column-value');
                                if (title && value) {
                                    cells[title.innerText.trim()] = value.innerText.trim();
                                }
                            }
                            if (cells['Numer KRS'] && cells['Nazwa / Firma']) {
                                out.push({
                                    krs: cells['Numer KRS'],
                                    name: cells['Nazwa / Firma'],
                                    city: cells['Miejscowość'] || null,
                                });
                            }
                        }
                        return out;
                    }"""
                )
            finally:
                await page.close()

        matches: list[CompanyMatch] = []
        for row in rows_data[:limit]:
            krs = (row.get("krs") or "").strip().zfill(10)
            if not krs.isdigit() or len(krs) != 10:
                continue
            matches.append(
                CompanyMatch(
                    id=krs,
                    name=row["name"].strip(),
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.KRS, value=krs, label="KRS number"
                        )
                    ],
                    address=row.get("city") or None,
                    status=None,
                    source_url=f"https://wyszukiwarka-krs.ms.gov.pl/podmiot/{krs}",
                )
            )
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.KRS:
            krs = _normalize_krs(value)
            return await self._lookup_krs(krs)
        if id_type in (IdentifierType.NIP, IdentifierType.VAT):
            nip = _normalize_nip(value)
            krs = await self._krs_from_nip(nip)
            if not krs:
                return None
            return await self._lookup_krs(krs)
        if id_type == IdentifierType.REGON:
            # GUS BIR API needs a free-but-manually-approved key; without it
            # we cannot resolve REGON → KRS authoritatively. Surface this
            # rather than guess, so the caller can fall back to NIP/KRS.
            raise AdapterNotImplementedError(
                "REGON lookup requires GUS BIR API key (not configured in MVP). "
                "Use KRS or NIP instead."
            )
        raise InvalidIdentifierError(
            f"PL supports KRS / NIP / VAT / REGON, got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        krs = _normalize_krs(company_id)
        async with build_http_client(base_url=self.KRS_BASE_URL) as client:
            resp = await get_with_retry(
                client,
                f"/OdpisPelny/{krs}",
                params={"rejestr": "P", "format": "json"},
            )
            if resp.status_code == 404:
                resp = await get_with_retry(
                    client,
                    f"/OdpisPelny/{krs}",
                    params={"rejestr": "S", "format": "json"},
                )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            payload = resp.json()
        filings = _extract_filings(krs, payload, years=years)
        try:
            await _enrich_with_msig(filings, krs)
        except Exception as exc:
            logger.warning("MSiG enrichment failed for KRS %s: %s", krs, exc)
        return filings

    async def _lookup_krs(self, krs: str) -> CompanyDetails | None:
        async with build_http_client(base_url=self.KRS_BASE_URL) as client:
            resp = await get_with_retry(
                client,
                f"/OdpisAktualny/{krs}",
                params={"rejestr": "P", "format": "json"},
            )
            if resp.status_code == 404:
                # Fall back to the associations / non-profit register.
                resp = await get_with_retry(
                    client,
                    f"/OdpisAktualny/{krs}",
                    params={"rejestr": "S", "format": "json"},
                )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
        return _details_from_odpis(krs, data)

    async def _krs_from_nip(self, nip: str) -> str | None:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        async with build_http_client(base_url=self.WL_BASE_URL) as client:
            resp = await get_with_retry(
                client,
                f"/search/nip/{nip}",
                params={"date": today},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            payload = resp.json()
        subject = ((payload.get("result") or {}).get("subject")) or {}
        krs = subject.get("krs")
        if not krs:
            return None
        return _normalize_krs(krs)


def _details_from_odpis(krs: str, payload: dict[str, Any]) -> CompanyDetails:
    odpis = payload.get("odpis") or {}
    naglowek = odpis.get("naglowekA") or {}
    dane = odpis.get("dane") or {}
    dzial1 = dane.get("dzial1") or {}
    dzial2 = dane.get("dzial2") or {}
    dzial3 = dane.get("dzial3") or {}
    dzial6 = dane.get("dzial6") or {}

    podmiot = (
        dzial1.get("danePodmiotu")
        or dzial1.get("danePodmiotuZagranicznego")
        or {}
    )
    identyfikatory = podmiot.get("identyfikatory") or {}
    siedziba_blok = (
        dzial1.get("siedzibaIAdres")
        or dzial1.get("siedzibaIAdresPodmiotuZagranicznego")
        or dzial1.get("siedzibaIAdresOddzialu")
        or {}
    )
    kapital = dzial1.get("kapital") or {}
    przedmiot = dzial3.get("przedmiotDzialalnosci") or {}

    identifiers: list[RegistryIdentifier] = [
        RegistryIdentifier(type=IdentifierType.KRS, value=krs, label="KRS"),
    ]
    nip_value = identyfikatory.get("nip")
    if nip_value:
        identifiers.append(
            RegistryIdentifier(type=IdentifierType.NIP, value=nip_value, label="NIP")
        )
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.VAT, value=f"PL{nip_value}", label="VAT"
            )
        )
    regon_value = identyfikatory.get("regon")
    if regon_value:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.REGON, value=regon_value, label="REGON"
            )
        )

    incorporation = _parse_pl_date(naglowek.get("dataRejestracjiWKRS"))
    dissolution = _extract_dissolution(dzial6)
    capital_amount, capital_currency = _extract_capital(kapital)
    nace_codes = _extract_nace(przedmiot)
    directors = _extract_directors(dzial2)
    rejestr = naglowek.get("rejestr")
    return CompanyDetails(
        id=krs,
        name=podmiot.get("nazwa", "") or "",
        country="PL",
        legal_form=podmiot.get("formaPrawna"),
        status=("ceased" if dissolution else "active"),
        incorporation_date=incorporation,
        dissolution_date=dissolution,
        registered_address=_format_address(siedziba_blok),
        capital_amount=capital_amount,
        capital_currency=capital_currency,
        nace_codes=nace_codes,
        identifiers=identifiers,
        directors=directors,
        website=(siedziba_blok.get("adresStronyInternetowej") or None),
        email=(siedziba_blok.get("adresPocztyElektronicznej") or None),
        raw=payload,
        source_url=(
            "https://wyszukiwarka-krs.ms.gov.pl/podmiot/"
            f"wynikiWyszukiwania?przedmiot=&numerKrsAdvancedSearch={krs}"
            f"&typ={'P' if rejestr == 'RejP' else 'S'}"
        ),
    )


_YEAR_RE = re.compile(r"(\d{4})\s*R")


def _extract_filings(krs: str, payload: dict[str, Any], *, years: int = 5) -> list[FinancialFiling]:
    """Parse `dzial3.wzmiankiOZlozonychDokumentach` from OdpisPelny.

    The Polish registry doesn't expose the actual statement files through a
    bot-friendly endpoint, but it does record — in `OdpisPelny` — every
    filing mention with period, submission date, and entry id. We turn each
    mention into a `FinancialFiling` and deep-link the document portal so
    the user can pull the raw PDF manually.
    """
    odpis = payload.get("odpis") or {}
    dzial3 = (odpis.get("dane") or {}).get("dzial3") or {}
    wzmianki = dzial3.get("wzmiankiOZlozonychDokumentach") or {}

    filings: dict[tuple[int | None, str], FinancialFiling] = {}
    rdf_deep_link = f"https://ekrs.ms.gov.pl/rdf/pd/search_df?nr_krs={krs}"

    KINDS: list[tuple[str, FilingType, str]] = [
        ("wzmiankaOZlozeniuRocznegoSprawozdaniaFinansowego", FilingType.ANNUAL_REPORT, "Annual financial statement"),
        ("wzmiankaOZlozeniuOpinii", FilingType.AUDIT_REPORT, "Auditor opinion"),
        ("wzmiankaOZlozeniuOpiniiBieglegoRewidenta", FilingType.AUDIT_REPORT, "Auditor opinion"),
        ("wzmiankaOZlozeniuUchwalyZatwierdzajacejRocznySf", FilingType.DIRECTORS_REPORT, "Approval resolution"),
        ("wzmiankaOZlozeniuSprawozdaniaZDzialalnosci", FilingType.DIRECTORS_REPORT, "Management report"),
        ("wzmiankaOZlozeniuSkonsolidowanegoSprawozdaniaFinansowego", FilingType.ANNUAL_REPORT, "Consolidated financial statement"),
    ]

    for key, filing_type, label in KINDS:
        entries = wzmianki.get(key) or []
        if not isinstance(entries, list):
            continue
        for entry in entries:
            positions = entry.get("pozycja") if isinstance(entry, dict) else None
            if not isinstance(positions, list):
                continue
            for pos in positions:
                if not isinstance(pos, dict):
                    continue
                period = pos.get("zaOkresOdDo") or pos.get("za_okres_od_do")
                submitted = _parse_pl_date(pos.get("dataZlozenia"))
                year: int | None = None
                if isinstance(period, str):
                    matches = _YEAR_RE.findall(period)
                    if matches:
                        try:
                            year = max(int(m) for m in matches)
                        except ValueError:
                            year = None
                if year is None and submitted is not None:
                    year = submitted.year - 1
                if year is None:
                    continue
                bucket = (year, label)
                if bucket in filings:
                    continue
                filings[bucket] = FinancialFiling(
                    company_id=krs,
                    year=year,
                    type=filing_type,
                    period_end=None,
                    currency="PLN",
                    structured_data={
                        "period": period,
                        "submitted_on": submitted.isoformat() if submitted else None,
                        "entry_number": pos.get("nrWpisuWprow"),
                        "label": label,
                        "registry_source": "KRS OdpisPelny mention",
                    },
                    document_url=None,
                    document_format="pdf",
                    source_url=rdf_deep_link,
                )

    rows = sorted(filings.values(), key=lambda f: (f.year, f.type), reverse=True)
    if years and years > 0:
        unique_years = sorted({f.year for f in rows}, reverse=True)[:years]
        rows = [f for f in rows if f.year in unique_years]
    return rows


def _parse_pl_date(value: str | None) -> date | None:
    if not value:
        return None
    # KRS dates are dotted "DD.MM.YYYY"; Biała Lista returns ISO "YYYY-MM-DD".
    try:
        if "." in value:
            return datetime.strptime(value[:10], "%d.%m.%Y").date()
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _extract_dissolution(dzial6: dict[str, Any]) -> date | None:
    wykr = (dzial6.get("informacjeOWykresleniu") or {}).get("dataWykresleniaZRejestru")
    return _parse_pl_date(wykr)


def _extract_capital(kapital: dict[str, Any]) -> tuple[float | None, str | None]:
    zakladowy = kapital.get("wysokoscKapitaluZakladowego") or {}
    raw = zakladowy.get("wartosc")
    waluta = zakladowy.get("waluta")
    if raw is None:
        return None, waluta
    try:
        amount = float(str(raw).replace(" ", "").replace(",", "."))
    except ValueError:
        return None, waluta
    return amount, waluta or "PLN"


def _extract_nace(przedmiot: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for block_key in ("przedmiotPrzewazajacejDzialalnosci", "przedmiotPozostalejDzialalnosci"):
        for item in (przedmiot.get(block_key) or []):
            dzial = item.get("kodDzial")
            klasa = item.get("kodKlasa")
            podklasa = item.get("kodPodklasa")
            if not dzial:
                continue
            code = str(dzial)
            if klasa:
                code = f"{code}.{klasa}"
            if podklasa:
                code = f"{code}.{podklasa}"
            if code not in codes:
                codes.append(code)
    return codes


def _extract_directors(dzial2: dict[str, Any]) -> list[Director]:
    out: list[Director] = []
    reprezentacja = dzial2.get("reprezentacja") or {}
    for member in (reprezentacja.get("sklad") or []):
        name = _format_person_name(member)
        if not name:
            continue
        out.append(Director(name=name, role=member.get("funkcjaWOrganie")))
    for organ in (dzial2.get("organNadzoru") or []):
        organ_name = organ.get("nazwa")
        for member in (organ.get("sklad") or []):
            name = _format_person_name(member)
            if not name:
                continue
            out.append(Director(name=name, role=organ_name))
    return out


def _format_person_name(member: dict[str, Any]) -> str | None:
    nazwisko = member.get("nazwisko") or {}
    imiona = member.get("imiona") or {}
    parts = [
        imiona.get("imie"),
        imiona.get("imieDrugie"),
        nazwisko.get("nazwiskoICzlon"),
        nazwisko.get("nazwiskoIICzlon"),
    ]
    joined = " ".join(p.strip() for p in parts if p and str(p).strip())
    return joined or None


def _format_address(siedziba_blok: dict[str, Any]) -> str | None:
    adres = siedziba_blok.get("adres") or {}
    parts = [
        adres.get("ulica"),
        adres.get("nrDomu"),
        adres.get("nrLokalu"),
        adres.get("kodPocztowy"),
        adres.get("miejscowosc"),
        adres.get("kraj"),
    ]
    joined = ", ".join(str(p).strip() for p in parts if p and str(p).strip())
    return joined or None


_MSIG_SEARCH_URL = "https://wyszukiwarka-msig.ms.gov.pl/api/Monitor/Search"
_MSIG_DETALIS_URL = "https://wyszukiwarka-msig.ms.gov.pl/api/Monitor/Detalis"
_MSIG_DOWNLOAD_URL = "https://wyszukiwarka-msig.ms.gov.pl/api/Monitor/Download"
_FINANCIAL_KEYWORDS = (
    "sprawozdani",
    "bilans",
    "rachunek zysk",
    "wzmianka",
    "wzmianki",
    "rdf/",
    "wpisy w dziale 3",
    "dz. 3.",
    "rub. 2. wzmianki",
)


async def _enrich_with_msig(filings: list[FinancialFiling], krs: str) -> None:
    """Backfill `document_url` on each filing using MSiG search.

    MSiG (Monitor Sądowy i Gospodarczy) publishes mandatory KRS announcements
    as PDFs that are downloadable WITHOUT going through the Incapsula-protected
    RDF portal. We search MSiG for the company, identify announcements that
    relate to financial-statement filings, and attach the gazette-issue PDF
    URL + the page within it where the company's record appears.
    """
    if not filings:
        return
    import httpx
    from datetime import date as _date

    today = _date.today()
    earliest_year = min(f.year for f in filings)
    earliest = f"{earliest_year - 1}-1-1"
    latest = f"{today.year}-{today.month}-{today.day}"

    candidates: list[dict[str, Any]] = []
    timeout = httpx.Timeout(15.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, headers={"Accept": "application/json"}) as client:
        for page_num in range(1, 11):  # cap to 10 pages so we don't hammer
            params = {
                "entityName": "",
                "krs": krs,
                "nip": "",
                "textInPosition": "",
                "textInBody": "",
                "signatureType": "B",
                "signatureOfCase": "",
                "signatureKRS": "",
                "court": "",
                "from": earliest,
                "to": latest,
                "page": str(page_num),
            }
            r = await client.get(_MSIG_SEARCH_URL, params=params)
            if r.status_code != 200:
                break
            try:
                data = r.json()
            except ValueError:
                break
            items = data.get("list") or []
            if not items:
                break
            candidates.extend(items)
            if page_num >= int(data.get("countPages") or 1):
                break

        # Fetch details for each candidate and keep those with financial-filing
        # keywords. The full gazette PDF is the same for many candidates from
        # the same monitor issue — we dedupe by monitor number.
        seen_monitors: dict[str, dict[str, Any]] = {}
        for cand in candidates[:60]:
            try:
                detail_r = await client.get(_MSIG_DETALIS_URL, params={"Id": cand["id"]})
                if detail_r.status_code != 200:
                    continue
                detail = detail_r.json()
            except (httpx.HTTPError, ValueError):
                continue
            body = (detail.get("textInBody") or "").lower()
            position = (detail.get("textInPosition") or "").lower()
            full = body + " " + position
            if not any(kw in full for kw in _FINANCIAL_KEYWORDS):
                continue
            monitor = detail.get("monitorNumber") or ""
            if not monitor:
                continue
            pub = detail.get("dateOfPublication") or ""
            year_match = re.search(r"(\d{4})", pub)
            pub_year = int(year_match.group(1)) if year_match else None
            # Extract fiscal-period end year from the body text. Polish entries
            # write the period as "okres OD 01.08.2023 DO 31.07.2024" — the DO
            # date's year is the fiscal year.
            period_end_year: int | None = None
            period_match = re.search(
                r"OD\s+\d{2}[.\s]?\d{2}[.\s]?\d{4}\s+DO\s+\d{2}[.\s]?\d{2}[.\s]?(\d{4})",
                detail.get("textInBody") or "",
                re.IGNORECASE,
            )
            if period_match:
                period_end_year = int(period_match.group(1))
            entry = {
                "monitor": monitor,
                "page": detail.get("page"),
                "id": cand["id"],
                "pub_year": pub_year,
                "period_end_year": period_end_year,
                "text": detail.get("textInBody") or "",
            }
            key = f"{monitor}-{period_end_year}" if period_end_year else monitor
            if key not in seen_monitors or (entry["pub_year"] or 0) > (seen_monitors[key]["pub_year"] or 0):
                seen_monitors[key] = entry

    if not seen_monitors:
        return

    monitor_entries = sorted(
        seen_monitors.values(),
        key=lambda e: (e["pub_year"] or 0),
        reverse=True,
    )

    # Index by filing year — match a filing to the earliest monitor entry that
    # mentions a statement for that fiscal year.
    for filing in filings:
        match = _best_msig_match(filing.year, monitor_entries)
        if match is None:
            continue
        # Slice endpoint extracts just the company's pages from the full
        # MSiG gazette; full PDF is kept under `source_url` for context.
        filing.document_url = f"/api/pl/msig/slice/{match['id']}?krs={krs}"
        filing.source_url = f"{_MSIG_DOWNLOAD_URL}?id={match['id']}"
        filing.document_format = "pdf"
        existing = filing.structured_data or {}
        existing.update(
            {
                "msig_number": match["monitor"],
                "msig_page": match["page"],
                "msig_published_year": match["pub_year"],
                "msig_excerpt": (match["text"] or "")[:280],
                "msig_id": match["id"],
            }
        )
        filing.structured_data = existing


def _best_msig_match(filing_year: int, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    # First try exact fiscal-period-year match — MSiG entries with the same
    # period-end year as the filing's fiscal year are the definitive match.
    exact = [e for e in entries if e.get("period_end_year") == filing_year]
    if exact:
        exact.sort(key=lambda e: e.get("pub_year") or 0, reverse=True)
        return exact[0]
    # Fall back to publication-year proximity (filings are registered shortly
    # after the fiscal year closes).
    eligible = [e for e in entries if (e["pub_year"] or 0) >= filing_year - 1]
    if not eligible:
        return entries[0] if entries else None
    eligible.sort(key=lambda e: abs((e["pub_year"] or 0) - filing_year))
    return eligible[0]
