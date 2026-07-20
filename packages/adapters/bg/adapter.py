"""Bulgaria adapter — Търговски регистър (Trade Register & NPLE Register).

The Bulgarian Registry Agency exposes free public JSON endpoints on
``portal.registryagency.bg/CR/api``:

- ``GET /Deeds/Summary?name={name}&selectedSearchFilter=1`` — legal-entity
  name search; returns ``[{ident, name, companyFullName, isPhysical}]``.
- ``GET /Deeds/{eik}`` — full canonical extract for a company keyed by its
  EIK / UIC (Edinen Identifikatsionen Kod, 9 or 13 digits). The payload
  embeds the "Announced Acts" section (``CR_GL_ANNOUNCED_ACTS_L``) which
  lists every filed document, including the annual financial reports
  ("Годишен финансов отчет") with per-document ``DocumentAccess/{token}``
  links.
- ``GET /Documents/{token}`` — streams the actual filed PDF for a given
  ``DocumentAccess`` token (``application/pdf``, no auth). This is the real
  downloadable document; the ``/CR/DocumentAccess/{token}`` route is only
  the JS viewer shell.

VAT validation is delegated to VIES — Bulgarian VAT is literally
``BG`` + EIK, so the same identifier resolves both ways.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import InvalidIdentifierError
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

_EIK_RE = re.compile(r"^\d{9}(\d{4})?$")
_HEALTH_PROBE_EIK = "831902088"  # Sopharma AD — stable public-company EIK

# Bulgarian Trade Register legal-form codes (subset; the API only ever returns
# numeric IDs and the SPA looks them up via /api/nomenclatures). We map only
# the very common ones; unknown values fall through to the raw integer string.
_LEGAL_FORM_NAMES: dict[int, str] = {
    1: "ET (Едноличен търговец)",
    2: "СД (Събирателно дружество)",
    3: "КД (Командитно дружество)",
    4: "ООД (Дружество с ограничена отговорност)",
    5: "АД (Акционерно дружество)",
    6: "КДА (Командитно дружество с акции)",
    7: "ЕООД (Еднолично ООД)",
    8: "ЕАД (Еднолично АД)",
    9: "Кооперация",
    10: "Клон на чуждестранен търговец",
    13: "СНЦ (Сдружение с нестопанска цел)",
    14: "Фондация",
}

# VIES SOAP plumbing — duplicated from packages.adapters.lu intentionally:
# every EU adapter that needs VAT verification has a tiny self-contained
# SOAP call rather than a shared client, because the upstream service is
# rate-limited per-caller and behaviour differs per member state.
_VIES_URL = "https://ec.europa.eu/taxation_customs/vies/services/checkVatService"
_VIES_ENVELOPE = """<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns:urn="urn:ec.europa.eu:taxud:vies:services:checkVat:types">
  <soapenv:Header/>
  <soapenv:Body>
    <urn:checkVat>
      <urn:countryCode>{cc}</urn:countryCode>
      <urn:vatNumber>{vat}</urn:vatNumber>
    </urn:checkVat>
  </soapenv:Body>
</soapenv:Envelope>"""
_VIES_NS = {
    "soap": "http://schemas.xmlsoap.org/soap/envelope/",
    "vies": "urn:ec.europa.eu:taxud:vies:services:checkVat:types",
}


def _normalize_eik(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "").replace("-", "")
    if cleaned.startswith("BG"):
        cleaned = cleaned[2:]
    if not _EIK_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Bulgarian EIK / UIC must be 9 or 13 digits: {value}"
        )
    return cleaned


class BGAdapter(CountryAdapter):
    country_code = "BG"
    country_name = "Bulgaria"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    PORTAL_BASE = "https://portal.registryagency.bg"

    async def health_check(self) -> AdapterHealth:
        try:
            async with build_http_client(base_url=self.PORTAL_BASE, timeout=25.0) as client:
                resp = await get_with_retry(client, f"/CR/api/Deeds/{_HEALTH_PROBE_EIK}")
                resp.raise_for_status()
                # The portal happily returns its SPA HTML shell with 200 for
                # unknown paths, so verify the response actually parses as the
                # expected JSON shape.
                data = resp.json()
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"Trade Register probe failed: {str(exc)[:160]}",
            )
        if not isinstance(data, dict) or "uic" not in data:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": False, "lookup": False, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes="Trade Register reachable but Deeds JSON shape unexpected.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Name search + lookup + downloadable annual financial reports "
                "via portal.registryagency.bg CR API."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = name.strip()
        if not query:
            return []
        params = {
            "page": 1,
            "pageSize": max(1, min(limit, 100)),
            "count": 0,
            "name": query,
            "selectedSearchFilter": 1,
            "includeHistory": "true",
        }
        async with build_http_client(base_url=self.PORTAL_BASE, timeout=30.0) as client:
            resp = await get_with_retry(client, "/CR/api/Deeds/Summary", params=params)
            resp.raise_for_status()
            try:
                rows = resp.json()
            except ValueError:
                return []
        if not isinstance(rows, list):
            return []
        matches: list[CompanyMatch] = []
        for row in rows:
            if not isinstance(row, dict) or row.get("isPhysical"):
                continue
            eik = str(row.get("ident") or "").strip()
            if not _EIK_RE.match(eik):
                continue
            display = (row.get("companyFullName") or row.get("name") or "").strip()
            matches.append(
                CompanyMatch(
                    id=eik,
                    name=display or eik,
                    country="BG",
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER,
                            value=eik,
                            label="EIK / UIC",
                        )
                    ],
                    source_url=(
                        f"{self.PORTAL_BASE}/CR/en/Reports/ActiveCondition?uic={eik}"
                    ),
                )
            )
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.COMPANY_NUMBER, IdentifierType.VAT):
            raise InvalidIdentifierError(
                f"BG supports COMPANY_NUMBER (EIK) or VAT, got {id_type}"
            )
        eik = _normalize_eik(value)
        deed = await self._fetch_deed(eik)
        if deed is None:
            return None

        vies = await self._vies_check(eik)

        identifiers = [
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER, value=eik, label="EIK / UIC"
            ),
        ]
        if vies and vies.get("valid"):
            identifiers.append(
                RegistryIdentifier(
                    type=IdentifierType.VAT, value=f"BG{eik}", label="VAT"
                )
            )

        company_name = (deed.get("fullName") or deed.get("companyName") or "").strip()
        legal_form_id = deed.get("legalForm")
        legal_form = (
            _LEGAL_FORM_NAMES.get(int(legal_form_id))
            if isinstance(legal_form_id, int)
            else None
        )
        address = _extract_registered_address(deed)
        capital, currency = _extract_capital(deed)
        directors = _extract_directors(deed)
        status_label = _deed_status_label(deed.get("deedStatus"))

        return CompanyDetails(
            id=eik,
            name=company_name or (vies.get("name", "").strip() if vies else "") or eik,
            country="BG",
            legal_form=legal_form,
            status=status_label,
            registered_address=address or (vies.get("address") if vies else None),
            capital_amount=capital,
            capital_currency=currency or ("BGN" if capital is not None else None),
            identifiers=identifiers,
            directors=directors,
            raw={"deed": deed, "vies": vies} if vies else {"deed": deed},
            source_url=f"https://portal.registryagency.bg/CR/Reports/VerificationPersonOrg?uic={eik}",
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        eik = _normalize_eik(company_id)
        deed = await self._fetch_deed(eik)
        if deed is None:
            return []
        cutoff_year = datetime.utcnow().year - years
        source_url = f"{self.PORTAL_BASE}/CR/en/Reports/ActiveCondition?uic={eik}"
        seen: set[tuple[int, FilingType]] = set()
        filings: list[FinancialFiling] = []
        for entry in _iter_annual_filings(deed):
            year = entry["year"]
            if year < cutoff_year:
                continue
            key = (year, entry["type"])
            if key in seen:
                continue
            seen.add(key)
            filings.append(
                FinancialFiling(
                    company_id=eik,
                    year=year,
                    type=entry["type"],
                    currency="BGN",
                    structured_data=None,
                    document_url=f"{self.PORTAL_BASE}/CR/api/Documents/{entry['doc_token']}",
                    document_format="pdf",
                    source_url=source_url,
                )
            )
        filings.sort(key=lambda f: (f.year, f.type.value), reverse=True)
        return filings

    async def _fetch_deed(self, eik: str) -> dict[str, Any] | None:
        async with build_http_client(base_url=self.PORTAL_BASE, timeout=30.0) as client:
            resp = await get_with_retry(client, f"/CR/api/Deeds/{eik}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            try:
                data = resp.json()
            except ValueError:
                return None
        if not isinstance(data, dict) or "uic" not in data:
            return None
        return data

    async def _vies_check(self, eik: str) -> dict[str, Any] | None:
        # VIES only supports 9-digit BG VAT; 13-digit EIKs (sole traders) are
        # not VAT-registered the same way, so we skip the call.
        if len(eik) != 9:
            return None
        envelope = _VIES_ENVELOPE.format(cc="BG", vat=eik)
        headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""}
        try:
            async with build_http_client(timeout=30.0, headers=headers) as client:
                resp = await client.post(_VIES_URL, content=envelope)
                if resp.status_code != 200:
                    return None
        except httpx.HTTPError:
            return None
        return _parse_vies_response(resp.text)


def _deed_status_label(code: Any) -> str | None:
    if code == 2:
        return "active"
    if code == 3:
        return "ceased"
    if code == 1:
        return "pending"
    return None


_CAPITAL_RE = re.compile(r"([\d\s][\d\s.,]*)\s*(€|BGN|лв|евро|EUR)", re.IGNORECASE)

# Each Announced-Acts field packs several document blocks into one HTML
# string: one ``<p class='field-text'>`` per filed document, each carrying a
# category heading, a ``DocumentAccess/{token}`` download link and a
# "Дата на обявяване" publication date. The reporting year is stated inline
# as "за YYYY г." or "Година: YYYYг.".
_ACT_BLOCK_RE = re.compile(
    r"<p[^>]*class=['\"]field-text['\"][^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL
)
_ACT_DOC_RE = re.compile(r"href=['\"]DocumentAccess/([^'\"]+)['\"]", re.IGNORECASE)
_REPORT_YEAR_RE = re.compile(r"(?:за|Година\s*:?)\s*((?:19|20)\d{2})\s*г")


def _iter_sections(deed: dict[str, Any], name_code: str) -> list[dict[str, Any]]:
    return [s for s in deed.get("sections") or [] if s.get("nameCode") == name_code]


def _iter_fields(
    deed: dict[str, Any], section_name_code: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for section in _iter_sections(deed, section_name_code):
        for sub_deed in section.get("subDeeds") or []:
            for group in sub_deed.get("groups") or []:
                for field in group.get("fields") or []:
                    out.append(field)
    return out


def _classify_act(text: str) -> FilingType | None:
    low = text.lower()
    if "одиторски" in low or "проверител" in low:
        return FilingType.AUDIT_REPORT
    if "доклад за дейността" in low:
        return FilingType.DIRECTORS_REPORT
    if "финансов отчет" in low:
        return FilingType.ANNUAL_REPORT
    return None


def _iter_annual_filings(deed: dict[str, Any]) -> list[dict[str, Any]]:
    """Yield ``{year, type, doc_token}`` for each downloadable annual filing.

    Only blocks that name both a downloadable document and an explicit
    reporting year are emitted — the reporting year is never inferred, so no
    document is mislabelled.
    """
    out: list[dict[str, Any]] = []
    for field in _iter_fields(deed, "CR_GL_ANNOUNCED_ACTS_L"):
        for block in _ACT_BLOCK_RE.findall(field.get("htmlData") or ""):
            doc = _ACT_DOC_RE.search(block)
            if not doc:
                continue
            text = _strip_html(block)
            kind = _classify_act(text)
            year_match = _REPORT_YEAR_RE.search(text)
            if kind is None or year_match is None:
                continue
            out.append(
                {
                    "year": int(year_match.group(1)),
                    "type": kind,
                    "doc_token": doc.group(1),
                }
            )
    return out


def _extract_registered_address(deed: dict[str, Any]) -> str | None:
    """Pull the registered seat ('Седалище и адрес на управление') from the
    general-status section. It lives in ``CR_F_5_L`` (fallback ``CR_F_5a_L``)
    encoded as an HTML snippet, so we strip tags and collapse whitespace.
    """
    by_code = {f.get("nameCode"): f for f in _iter_fields(deed, "CR_GL_GENERAL_STATUS_L")}
    for code in ("CR_F_5_L", "CR_F_5a_L"):
        field = by_code.get(code)
        if field is None:
            continue
        text = _strip_html(field.get("htmlData") or "")
        if text:
            return text
    return None


def _extract_capital(deed: dict[str, Any]) -> tuple[float | None, str | None]:
    """Registered capital lives in ``CR_F_31_L`` (subscribed) with
    ``CR_F_32_L`` (paid-in) as fallback, e.g. ``274970377.53 €``."""
    by_code = {f.get("nameCode"): f for f in _iter_fields(deed, "CR_GL_GENERAL_STATUS_L")}
    for code in ("CR_F_31_L", "CR_F_32_L"):
        field = by_code.get(code)
        if field is None:
            continue
        m = _CAPITAL_RE.search(_strip_html(field.get("htmlData") or ""))
        if not m:
            continue
        raw_amount = m.group(1).replace(" ", "").replace(",", ".")
        try:
            amount = float(raw_amount)
        except ValueError:
            continue
        token = m.group(2).lower()
        currency = "EUR" if token in ("€", "eur") or token.startswith("евро") else "BGN"
        return amount, currency
    return None, None


def _extract_directors(deed: dict[str, Any]) -> list[Any]:
    # The Bulgarian register names representatives under their own field rather
    # than a structured directors list. Surfacing them as ``Director`` rows
    # would require parsing free-text Cyrillic, which is brittle and risks
    # fabricating roles. Leave empty — the raw deed is still attached.
    return []


def _strip_html(html: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_vies_response(xml_text: str) -> dict[str, Any] | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    body = root.find("soap:Body", _VIES_NS)
    if body is None:
        return None
    fault = body.find("soap:Fault", _VIES_NS)
    if fault is not None:
        return {"valid": False, "fault": (fault.findtext("faultstring") or "").strip()}
    resp = body.find("vies:checkVatResponse", _VIES_NS)
    if resp is None:
        return None
    valid = (
        resp.findtext("vies:valid", default="false", namespaces=_VIES_NS) or ""
    ).lower() == "true"
    name = resp.findtext("vies:name", default="", namespaces=_VIES_NS) or ""
    address = resp.findtext("vies:address", default="", namespaces=_VIES_NS) or ""
    return {"valid": valid, "name": name, "address": address}
