"""Poland adapter — resolves ANY Polish business, companies *and* sole traders.

Two registers cover Polish business in full:

- **KRS** (Krajowy Rejestr Sądowy) — companies / spółki. `api-krs.ms.gov.pl`
  serves the full registry extract (`OdpisAktualny`) and filing history
  (`OdpisPelny`) as JSON, key-free.
- **CEIDG** (Centralna Ewidencja i Informacja o Działalności Gospodarczej) —
  sole proprietorships (jednoosobowa działalność gospodarcza / JDG). These
  are *not* in KRS. The authoritative source is the CEIDG v3 REST warehouse
  at `dane.biznes.gov.pl/api/ceidg/v3`, which is the only free source that
  supports free-text **name** search over sole traders. It needs a free JWT
  (env `PL_CEIDG_TOKEN`, see docs/countries/pl.md for the registration
  steps). When configured it powers sole-trader name search and enriches
  sole-trader lookups with the full trade name, PKD codes, and contacts.

Sources stitched here, all free:

- KRS REST `OdpisAktualny/{krs}?rejestr=P|S` — company registry extract.
- CEIDG v3 `firmy?nazwa=` / `firma?nip=|regon=` — sole traders (+ companies)
  by name / identifier. Bearer JWT.
- Biała Lista (white list of VAT payers) `search/nip/{nip}` and
  `search/regon/{regon}` — keyless. Resolves a NIP **or REGON** to the
  matching subject: for a company it yields the KRS; for a sole trader it
  yields real registry identity (legal name, REGON, address, registration
  date, VAT status, bank accounts) with no KRS. This is the always-on,
  key-free identifier path that resolves sole traders even without a CEIDG
  token.
- GLEIF JSON:API — name → KRS for LEI-registered companies (keyless).
- MSiG (Monitor Sądowy i Gospodarczy) — downloadable gazette PDFs for KRS
  financial filings.

Identifiers supported:
    KRS    — 10-digit court registry number (companies only).
    NIP    — 10-digit tax id; same value as the Polish VAT (with a "PL"
             prefix). Every Polish business — company or sole trader — has one.
    REGON  — 9 or 14-digit statistical id. Resolved key-free via Biała Lista.

Financials:

- Companies: `OdpisPelny` records every filing mention (period, submission
  date, entry id); each becomes a `FinancialFiling`, deep-linked to the real
  MSiG gazette PDF.
- Sole traders: JDG file no public financial statements, so `fetch_financials`
  honestly returns `[]` for them — the registry identity is the win.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterError,
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

_CEIDG_TOKEN_ENVS = ("PL_CEIDG_TOKEN", "PL_CEIDG_JWT")

_CEIDG_STATUS_MAP = {
    "AKTYWNY": "active",
    "ZAWIESZONY": "suspended",
    "WYKRESLONY": "ceased",
    "OCZEKUJE_NA_ROZPOCZECIE_DZIALANOSCI": "pending",
    "WYLACZNIE_W_FORMIE_SPOLKI": "active",
}

_SOLE_TRADER_FORM = "Jednoosobowa działalność gospodarcza (sole proprietorship)"
_BIALA_LISTA_PUBLIC = "https://www.podatki.gov.pl/wykaz-podatnikow-vat-wyszukiwarka"


def _ceidg_token() -> str | None:
    for env in _CEIDG_TOKEN_ENVS:
        value = os.getenv(env)
        if value:
            return value.strip()
    return None


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


def _is_valid_nip(value: str) -> bool:
    cleaned = value.strip().replace(" ", "").replace("-", "").upper()
    if cleaned.startswith("PL"):
        cleaned = cleaned[2:]
    if not _NIP_RE.match(cleaned):
        return False
    checksum = sum(int(d) * w for d, w in zip(cleaned[:9], _NIP_WEIGHTS)) % 11
    return checksum != 10 and checksum == int(cleaned[9])


def _normalize_regon(value: str) -> str:
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if cleaned.isdigit() and len(cleaned) == 8:
        cleaned = cleaned.zfill(9)
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
    api_key_env = "PL_CEIDG_TOKEN"
    rate_limit_per_minute = 60

    KRS_BASE_URL = "https://api-krs.ms.gov.pl/api/krs"
    WL_BASE_URL = "https://wl-api.mf.gov.pl/api"
    CEIDG_BASE_URL = "https://dane.biznes.gov.pl/api/ceidg/v3"
    MSIG_BASE_URL = "https://wyszukiwarka-msig.ms.gov.pl/api"
    GLEIF_BASE_URL = "https://api.gleif.org/api/v1"

    # CEIDG throttles hard: a min gap between requests, with a 180 s lockout if
    # violated. We only ever fire a single CEIDG request per public call.
    CEIDG_RATE_LIMIT_PER_MINUTE = 16

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
        ceidg = bool(_ceidg_token())
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=False,
            api_key_present=ceidg,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Companies via KRS REST; sole traders via Biała Lista (NIP/REGON, "
                "key-free) and CEIDG v3 "
                + ("(PL_CEIDG_TOKEN set — sole-trader name search on)"
                   if ceidg else
                   "(no PL_CEIDG_TOKEN — sole-trader NAME search off; "
                   "identifier lookup still works)")
                + "; company name search via GLEIF; KRS filings from OdpisPelny "
                "+ MSiG gazette PDFs."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        """Resolve a business name to matches across both Polish registers.

        Layered, best-source-first:

        1. **CEIDG v3** (`PL_CEIDG_TOKEN`) — sole proprietors *and* companies by
           name. The only free source that indexes JDG by name; skipped
           silently when no token is configured.
        2. **GLEIF** — companies keyed by name whose Polish LEI record carries a
           KRS (`entity.registeredAs` under authority `RA000484`). Key-free.

        Results are de-duplicated by NIP / KRS / LEI and capped at ``limit``.
        """
        matches: list[CompanyMatch] = []
        seen: set[str] = set()

        for source in (self._ceidg_search_by_name, self._gleif_search_by_name):
            if len(matches) >= limit:
                break
            for match in await source(name, limit):
                key = _match_key(match)
                if key in seen:
                    continue
                seen.add(key)
                matches.append(match)
                if len(matches) >= limit:
                    break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.KRS:
            return await self._lookup_krs(_normalize_krs(value))
        if id_type in (IdentifierType.NIP, IdentifierType.VAT):
            return await self._lookup_by_nip(_normalize_nip(value))
        if id_type == IdentifierType.REGON:
            return await self._lookup_by_regon(_normalize_regon(value))
        raise InvalidIdentifierError(
            f"PL supports KRS / NIP / VAT / REGON, got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        cleaned = (company_id or "").strip().replace(" ", "").replace("-", "")
        # Sole proprietors (CEIDG / JDG) file no public financial statements.
        # Their adapter id is their NIP (never zero-padded, unlike a KRS), so a
        # valid non-zero-leading NIP means "sole trader → nothing to fetch".
        if not cleaned.startswith("0") and _is_valid_nip(cleaned):
            return []

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

    # --- Name search sources ------------------------------------------------

    async def _gleif_search_by_name(
        self, name: str, limit: int
    ) -> list[CompanyMatch]:
        """Companies by name via GLEIF (LEI-registered → KRS). Key-free.

        The official KRS web search (`wyszukiwarka-krs.ms.gov.pl`) is fronted by
        Incapsula and only usable through a full browser session, so GLEIF's
        public JSON:API is the request-path name source: every Polish LEI record
        carries its KRS in `entity.registeredAs` under authority `RA000484`.
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

    async def _ceidg_search_by_name(
        self, name: str, limit: int
    ) -> list[CompanyMatch]:
        """Sole proprietors (and companies) by name via CEIDG v3.

        This is the only free source that indexes CEIDG / JDG entries by name.
        Returns `[]` (rather than raising) when no `PL_CEIDG_TOKEN` is set so
        the GLEIF company layer still runs — a missing token degrades
        sole-trader name search, it doesn't break the adapter.
        """
        token = _ceidg_token()
        if not token:
            return []
        page_limit = max(1, min(int(limit), 50))
        params = [("nazwa", name), ("limit", str(page_limit)), ("page", "0")]
        async with build_http_client(
            base_url=self.CEIDG_BASE_URL,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
        ) as client:
            resp = await get_with_retry(client, "/firmy", params=params)
        if resp.status_code == 204:
            return []
        if resp.status_code in (401, 403):
            raise AdapterError(
                "CEIDG v3 rejected PL_CEIDG_TOKEN "
                f"(HTTP {resp.status_code}); token invalid or expired."
            )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        payload = resp.json()
        matches: list[CompanyMatch] = []
        for item in payload.get("firmy") or []:
            match = _ceidg_item_to_match(item)
            if match:
                matches.append(match)
            if len(matches) >= limit:
                break
        return matches

    # --- Identifier lookups -------------------------------------------------

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

    async def _lookup_by_nip(self, nip: str) -> CompanyDetails | None:
        subject = await self._biala_subject(f"/search/nip/{nip}")
        if subject is None:
            # Not a VAT payer (some JDG aren't) — CEIDG is the only fallback.
            return await self._ceidg_details(nip=nip)
        krs = subject.get("krs")
        if krs:
            return await self._lookup_krs(_normalize_krs(krs))
        details = _sole_trader_details_from_biala(subject)
        await self._enrich_sole_trader(details, nip=subject.get("nip") or nip)
        return details

    async def _lookup_by_regon(self, regon: str) -> CompanyDetails | None:
        subject = await self._biala_subject(f"/search/regon/{regon}")
        if subject is None:
            return await self._ceidg_details(regon=regon)
        krs = subject.get("krs")
        if krs:
            return await self._lookup_krs(_normalize_krs(krs))
        details = _sole_trader_details_from_biala(subject)
        await self._enrich_sole_trader(
            details, nip=subject.get("nip"), regon=subject.get("regon") or regon
        )
        return details

    async def _biala_subject(self, path: str) -> dict[str, Any] | None:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        async with build_http_client(base_url=self.WL_BASE_URL) as client:
            resp = await get_with_retry(client, path, params={"date": today})
            if resp.status_code in (400, 404):
                return None
            resp.raise_for_status()
            payload = resp.json()
        return ((payload.get("result") or {}).get("subject")) or None

    # --- CEIDG detail (sole-trader enrichment) ------------------------------

    async def _ceidg_firma(
        self,
        *,
        nip: str | None = None,
        regon: str | None = None,
    ) -> dict[str, Any] | None:
        token = _ceidg_token()
        if not token:
            return None
        params: dict[str, str] = {}
        if nip:
            params["nip"] = nip
        elif regon:
            params["regon"] = regon
        else:
            return None
        async with build_http_client(
            base_url=self.CEIDG_BASE_URL,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
        ) as client:
            resp = await get_with_retry(client, "/firma", params=params)
        if resp.status_code in (204, 404):
            return None
        if resp.status_code in (401, 403):
            raise AdapterError(
                "CEIDG v3 rejected PL_CEIDG_TOKEN "
                f"(HTTP {resp.status_code}); token invalid or expired."
            )
        resp.raise_for_status()
        entries = (resp.json() or {}).get("firma") or []
        if isinstance(entries, dict):
            entries = [entries]
        return entries[0] if entries else None

    async def _ceidg_details(
        self, *, nip: str | None = None, regon: str | None = None
    ) -> CompanyDetails | None:
        """Build a sole-trader record purely from CEIDG (Biała Lista missed)."""
        if not _ceidg_token():
            raise AdapterError(
                "This identifier resolves to a CEIDG sole trader not on the "
                "VAT white list; set PL_CEIDG_TOKEN to look it up. See "
                "docs/countries/pl.md for the free-registration steps."
            )
        firma = await self._ceidg_firma(nip=nip, regon=regon)
        if firma is None:
            return None
        return _ceidg_firma_to_details(firma)

    async def _enrich_sole_trader(
        self,
        details: CompanyDetails,
        *,
        nip: str | None = None,
        regon: str | None = None,
    ) -> None:
        """Overlay the CEIDG trade name, PKD codes, and contacts onto a
        Biała-Lista-derived sole-trader record. No-op without a token."""
        if not _ceidg_token():
            return
        try:
            firma = await self._ceidg_firma(nip=nip, regon=regon)
        except AdapterError as exc:
            logger.warning("CEIDG enrichment skipped: %s", exc)
            return
        if firma is None:
            return
        _merge_ceidg_into_details(details, firma)


# --- KRS (company) parsing --------------------------------------------------


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


# --- CEIDG (sole-trader) parsing --------------------------------------------


def _sole_trader_identifiers(
    nip: str | None, regon: str | None
) -> list[RegistryIdentifier]:
    identifiers: list[RegistryIdentifier] = []
    if nip:
        identifiers.append(
            RegistryIdentifier(type=IdentifierType.NIP, value=nip, label="NIP")
        )
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.VAT, value=f"PL{nip}", label="VAT"
            )
        )
    if regon:
        identifiers.append(
            RegistryIdentifier(
                type=IdentifierType.REGON, value=regon, label="REGON"
            )
        )
    return identifiers


def _sole_trader_details_from_biala(subject: dict[str, Any]) -> CompanyDetails:
    """A JDG identity from the VAT white list — key-free registry data.

    Biała Lista returns the taxpayer's legal name (owner name), not the full
    trade name; the full "AKTIV JUSTYNA OSIP"-style trading name comes from
    CEIDG enrichment when a token is set.
    """
    nip = subject.get("nip")
    regon = subject.get("regon")
    registration = _parse_pl_date(subject.get("registrationLegalDate"))
    removal = _parse_pl_date(subject.get("removalDate"))
    address = subject.get("residenceAddress") or subject.get("workingAddress")
    accounts = subject.get("accountNumbers") or []
    return CompanyDetails(
        id=nip or regon or "",
        name=subject.get("name", "") or "",
        country="PL",
        legal_form=_SOLE_TRADER_FORM,
        status=("ceased" if removal else "active"),
        incorporation_date=registration,
        dissolution_date=removal,
        registered_address=address,
        identifiers=_sole_trader_identifiers(nip, regon),
        raw={
            "source": "biala_lista",
            "vat_status": subject.get("statusVat"),
            "bank_accounts": accounts,
            "subject": subject,
        },
        source_url=_BIALA_LISTA_PUBLIC,
    )


def _ceidg_firma_to_details(firma: dict[str, Any]) -> CompanyDetails:
    wlasciciel = firma.get("wlasciciel") or {}
    nip = wlasciciel.get("nip")
    regon = wlasciciel.get("regon")
    entry_id = firma.get("id")
    return CompanyDetails(
        id=nip or regon or str(entry_id or ""),
        name=firma.get("nazwa", "") or "",
        country="PL",
        legal_form=_SOLE_TRADER_FORM,
        status=_CEIDG_STATUS_MAP.get(str(firma.get("status") or "").upper()),
        incorporation_date=_parse_iso_date(firma.get("dataRozpoczecia")),
        dissolution_date=_parse_iso_date(
            firma.get("dataZakonczenia") or firma.get("dataWykreslenia")
        ),
        registered_address=_format_ceidg_address(firma.get("adresDzialalnosci")),
        nace_codes=_extract_ceidg_pkd(firma),
        identifiers=_sole_trader_identifiers(nip, regon),
        website=(firma.get("www") or None),
        email=(firma.get("email") or None),
        phone=(firma.get("telefon") or None),
        raw={"source": "ceidg_v3", "firma": firma},
        source_url=_ceidg_public_detail_url(entry_id),
    )


def _merge_ceidg_into_details(
    details: CompanyDetails, firma: dict[str, Any]
) -> None:
    if firma.get("nazwa"):
        details.name = firma["nazwa"]
    if not details.legal_form:
        details.legal_form = _SOLE_TRADER_FORM
    status = _CEIDG_STATUS_MAP.get(str(firma.get("status") or "").upper())
    if status:
        details.status = status
    started = _parse_iso_date(firma.get("dataRozpoczecia"))
    if started:
        details.incorporation_date = started
    ended = _parse_iso_date(
        firma.get("dataZakonczenia") or firma.get("dataWykreslenia")
    )
    if ended:
        details.dissolution_date = ended
    pkd = _extract_ceidg_pkd(firma)
    if pkd:
        details.nace_codes = pkd
    ceidg_address = _format_ceidg_address(firma.get("adresDzialalnosci"))
    if ceidg_address:
        details.registered_address = ceidg_address
    details.website = firma.get("www") or details.website
    details.email = firma.get("email") or details.email
    details.phone = firma.get("telefon") or details.phone
    entry_id = firma.get("id")
    if entry_id:
        details.source_url = _ceidg_public_detail_url(entry_id)
    raw = dict(details.raw or {})
    raw["ceidg_firma"] = firma
    details.raw = raw


def _ceidg_item_to_match(item: dict[str, Any]) -> CompanyMatch | None:
    name = item.get("nazwa") or ""
    if not name:
        return None
    wlasciciel = item.get("wlasciciel") or {}
    nip = wlasciciel.get("nip")
    regon = wlasciciel.get("regon")
    entry_id = item.get("id")
    identifiers = _sole_trader_identifiers(nip, regon)
    return CompanyMatch(
        id=nip or regon or str(entry_id or name),
        name=name,
        country="PL",
        identifiers=identifiers,
        address=_format_ceidg_address(item.get("adresDzialalnosci")),
        status=_CEIDG_STATUS_MAP.get(str(item.get("status") or "").upper()),
        source_url=_ceidg_public_detail_url(entry_id),
    )


def _ceidg_public_detail_url(entry_id: Any) -> str:
    if entry_id:
        return (
            "https://aplikacja.ceidg.gov.pl/CEIDG/CEIDG.Public.UI/"
            f"SearchDetails.aspx?Id={entry_id}"
        )
    return "https://aplikacja.ceidg.gov.pl/CEIDG/CEIDG.Public.UI/Search.aspx"


def _extract_ceidg_pkd(firma: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    glowny = firma.get("pkdGlowny") or {}
    for entry in [glowny, *(firma.get("pkd") or [])]:
        if not isinstance(entry, dict):
            continue
        code = _format_pkd(entry.get("kod") or entry.get("symbol"))
        if code and code not in codes:
            codes.append(code)
    return codes


def _format_pkd(raw: Any) -> str | None:
    if not raw:
        return None
    cleaned = str(raw).strip().upper().replace(".", "")
    match = re.match(r"^(\d{2})(\d{2})([A-Z])?$", cleaned)
    if not match:
        return cleaned or None
    dzial, klasa, litera = match.groups()
    code = f"{dzial}.{klasa}"
    if litera:
        code = f"{code}.{litera}"
    return code


def _format_ceidg_address(adr: dict[str, Any] | None) -> str | None:
    if not adr:
        return None
    street = " ".join(
        str(p).strip() for p in (adr.get("ulica"), adr.get("budynek")) if p
    )
    lokal = adr.get("lokal")
    if lokal:
        street = f"{street}/{lokal}" if street else str(lokal)
    city = " ".join(
        str(p).strip() for p in (adr.get("kod"), adr.get("miasto")) if p
    )
    parts = [p for p in (street, city, adr.get("kraj")) if p and str(p).strip()]
    return ", ".join(str(p).strip() for p in parts) or None


# --- GLEIF (company name → KRS) ---------------------------------------------


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


def _match_key(match: CompanyMatch) -> str:
    priority = (
        IdentifierType.NIP,
        IdentifierType.KRS,
        IdentifierType.REGON,
        IdentifierType.LEI,
    )
    by_type = {i.type: i.value for i in match.identifiers}
    for id_type in priority:
        if id_type in by_type:
            return f"{id_type.value}:{by_type[id_type]}"
    return f"id:{match.id}"


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


# --- KRS filings + MSiG -----------------------------------------------------


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


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
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
