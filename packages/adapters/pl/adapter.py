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

Name search (see docs/countries/pl.md):

- The official KRS web search (`wyszukiwarka-krs.ms.gov.pl`) is behind
  Incapsula and only usable through a browser session. Instead we resolve
  names through GLEIF's public JSON:API: Polish LEI records carry their KRS
  number in `entity.registeredAs` under registration authority `RA000484`
  (Krajowy Rejestr Sądowy), so a name hit yields a KRS this adapter can then
  look up and file against. Coverage is limited to LEI-registered entities.

Financials:

- The registry doesn't expose statement files over a bot-friendly endpoint,
  but `OdpisPelny` records every filing mention (period, submission date,
  entry id). Each becomes a `FinancialFiling`. `document_url` is backfilled
  from MSiG (Monitor Sądowy i Gospodarczy), whose search API is *not* behind
  Incapsula: RDF-signature announcements are the financial filings, and
  `Monitor/Download?id=<id>` serves the real gazette-issue PDF.
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
    GLEIF_BASE_URL = "https://api.gleif.org/api/v1"

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
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Lookup via KRS REST + Biała Lista; name search via GLEIF "
                "(RA000484 → KRS); filings from KRS OdpisPelny mentions, "
                "downloadable gazette PDFs backfilled from MSiG."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        """Resolve a company name to KRS-keyed matches via GLEIF.

        The official KRS web search (`wyszukiwarka-krs.ms.gov.pl`) is fronted
        by Incapsula and only usable through a full browser session, so it is
        not a reliable request-path source. GLEIF's public JSON:API covers the
        Polish register keyed by name, and — because every Polish LEI record
        carries its KRS number in `entity.registeredAs` under registration
        authority `RA000484` (Krajowy Rejestr Sądowy) — a name hit resolves
        straight to a KRS the rest of this adapter can look up and file against.
        """
        params: dict[str, str | int] = {
            "filter[entity.legalName]": name,
            "filter[entity.legalAddress.country]": self.country_code,
            "page[size]": max(1, min(int(limit) * 2, 200)),
            "page[number]": 1,
        }
        async with build_http_client(
            base_url=self.GLEIF_BASE_URL,
            headers={"Accept": "application/vnd.api+json"},
        ) as client:
            resp = await get_with_retry(client, "/lei-records", params=params)
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            payload = resp.json()

        matches: list[CompanyMatch] = []
        for record in payload.get("data") or []:
            match = _gleif_record_to_match(record)
            if match:
                matches.append(match)
            if len(matches) >= limit:
                break
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


_KRS_REGISTRATION_AUTHORITY = "RA000484"


def _gleif_record_to_match(record: dict[str, Any]) -> CompanyMatch | None:
    lei = record.get("id")
    entity = ((record.get("attributes") or {}).get("entity")) or {}
    name = ((entity.get("legalName") or {}).get("name")) or ""
    if not name:
        return None
    address = entity.get("legalAddress") or {}
    status_raw = (entity.get("status") or "").upper()
    status = "active" if status_raw == "ACTIVE" else ("ceased" if status_raw == "INACTIVE" else None)

    registered_at = ((entity.get("registeredAt") or {}).get("id")) or ""
    registered_as = str(entity.get("registeredAs") or "").strip()
    krs: str | None = None
    if registered_at == _KRS_REGISTRATION_AUTHORITY and registered_as.isdigit():
        krs = registered_as.zfill(10)
        if len(krs) != 10:
            krs = None

    identifiers: list[RegistryIdentifier] = []
    if krs:
        identifiers.append(RegistryIdentifier(type=IdentifierType.KRS, value=krs, label="KRS"))
    if lei:
        identifiers.append(RegistryIdentifier(type=IdentifierType.LEI, value=str(lei), label="LEI"))
    if not identifiers:
        return None

    match_id = krs or str(lei)
    source_url = (
        f"https://wyszukiwarka-krs.ms.gov.pl/podmiot/{krs}"
        if krs
        else f"https://search.gleif.org/#/record/{lei}"
    )
    return CompanyMatch(
        id=match_id,
        name=name,
        country="PL",
        identifiers=identifiers,
        address=_format_gleif_address(address),
        status=status,
        source_url=source_url,
    )


def _format_gleif_address(address: dict[str, Any]) -> str | None:
    parts: list[str] = []
    lines = address.get("addressLines")
    if isinstance(lines, list):
        parts.extend(str(line) for line in lines if line)
    for key in ("postalCode", "city", "country"):
        val = address.get(key)
        if val:
            parts.append(str(val))
    cleaned = [p.strip() for p in parts if p and str(p).strip()]
    return ", ".join(cleaned) if cleaned else None


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
        ("wzmiankaOZlozeniuSkonsolidowanegoRocznegoSprawozdaniaFinansowego", FilingType.ANNUAL_REPORT, "Consolidated financial statement"),
        ("wzmiankaOZlozeniuSkonsolidowanegoSprawozdaniaFinansowego", FilingType.ANNUAL_REPORT, "Consolidated financial statement"),
        ("wzmiankaOZlozeniuOpiniiBieglegoRewidentaSprawozdaniaZBadania", FilingType.AUDIT_REPORT, "Auditor opinion"),
        ("wzmiankaOZlozeniuOpiniiBieglegoRewidenta", FilingType.AUDIT_REPORT, "Auditor opinion"),
        ("wzmiankaOZlozeniuUchwalyPostanowieniaOZatwierdzeniuRocznegoSprawozdaniaFinansowego", FilingType.DIRECTORS_REPORT, "Approval resolution"),
        ("wzmiankaOZlozeniuUchwalyZatwierdzajacejRocznySf", FilingType.DIRECTORS_REPORT, "Approval resolution"),
        ("wzmiankaOZlozeniuSprawozdaniaZDzialalnosci", FilingType.DIRECTORS_REPORT, "Management report"),
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
_MSIG_DOWNLOAD_URL = "https://wyszukiwarka-msig.ms.gov.pl/api/Monitor/Download"
_RDF_SIGNATURE_RE = re.compile(r"RDF/", re.IGNORECASE)


async def _enrich_with_msig(filings: list[FinancialFiling], krs: str) -> None:
    """Attach a real downloadable gazette PDF to each filing via MSiG.

    Financial-statement filings (the RDF stream — Repozytorium Dokumentów
    Finansowych) are announced in Monitor Sądowy i Gospodarczy, and MSiG's
    search API is *not* behind Incapsula. Every RDF announcement carries a
    `signatureKRS` shaped `[RDF/<id>/<yy>/<seq>]`, which lets us pick out the
    financial filings from ordinary court entries straight off the search
    list — no per-record detail crawl. `Monitor/Download?id=<id>` then serves
    the actual gazette-issue PDF (`application/pdf`) containing that company's
    published statement, so `document_url` genuinely downloads.
    """
    if not filings:
        return
    import httpx
    from datetime import date as _date

    today = _date.today()
    earliest_year = min(f.year for f in filings)
    earliest = f"{earliest_year}-1-1"
    latest = f"{today.year}-{today.month}-{today.day}"

    rdf_entries: list[dict[str, Any]] = []
    seen_ids: set[Any] = set()
    timeout = httpx.Timeout(15.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, headers={"Accept": "application/json"}) as client:
        for page_num in range(1, 13):
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
            for item in items:
                signature = item.get("signatureKRS") or ""
                if not _RDF_SIGNATURE_RE.search(signature):
                    continue
                item_id = item.get("id")
                if item_id is None or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                pub = item.get("dateOfPublication") or ""
                year_match = re.match(r"(\d{4})", pub)
                rdf_entries.append(
                    {
                        "id": item_id,
                        "monitor": item.get("monitorNumber") or "",
                        "signature": signature.strip("[]"),
                        "pub_year": int(year_match.group(1)) if year_match else None,
                    }
                )
            if page_num >= int(data.get("countPages") or 1):
                break

    if not rdf_entries:
        return

    for filing in filings:
        match = _best_rdf_match(filing.year, rdf_entries)
        if match is None:
            continue
        filing.document_url = f"{_MSIG_DOWNLOAD_URL}?id={match['id']}"
        filing.document_format = "pdf"
        existing = filing.structured_data or {}
        existing.update(
            {
                "msig_number": match["monitor"],
                "msig_signature": match["signature"],
                "msig_published_year": match["pub_year"],
                "msig_id": match["id"],
            }
        )
        filing.structured_data = existing


def _best_rdf_match(filing_year: int, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Polish annual statements are published the year after the fiscal year,
    so an RDF announcement in `filing_year + 1` is the canonical match."""
    exact = [e for e in entries if e.get("pub_year") == filing_year + 1]
    if exact:
        return exact[0]
    eligible = [e for e in entries if (e.get("pub_year") or 0) > filing_year]
    if not eligible:
        return None
    eligible.sort(key=lambda e: abs((e.get("pub_year") or 0) - (filing_year + 1)))
    return eligible[0]
