"""Austria adapter — Firmenbuch / VIES VAT.

The Austrian Firmenbuch (Justizonline) requires citizen-card / ID-Austria
login for structured extracts, and ``Handelsregister``-equivalent paid
endpoints are out of scope for the free-tier MVP. The community mirror
``offeneregister.at`` referenced in the country research is currently not
resolvable (DNS dead) so it cannot be relied on as a live data source.

What this adapter can do without paid access or eID:

- Validate Austrian VAT (UID) numbers through the EU VIES SOAP service.
  Austria, like Germany / Spain / Cyprus, does not return name + address
  via VIES (privacy policy), so the response is only a validity signal.
- Confirm health by probing VIES.

What this adapter cannot do free of charge today:

- Search Firmenbuch by company name — no public JSON endpoint.
- Resolve a Firmenbuchnummer (FN) to a full registry record — requires
  ID-Austria authentication or a paid Compass / KSV provider.
- Pull filed annual accounts — Firmenbuch documents are €1–€10 each
  behind a session; Wiener Börse hosts listed-company annual reports as
  PDFs but only via brittle TYPO3 issuer pages with no stable filings
  feed. ``fetch_financials`` returns an empty list to honour the contract
  (consistent with the project rule against returning mock data).

Per the spec: never invent data. Operations we cannot perform raise
``AdapterNotImplementedError`` so callers see a 501.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters._base.http import build_http_client
from packages.shared.models import (
    AdapterHealth,
    AdapterStatus,
    CompanyDetails,
    CompanyMatch,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

# Austrian Firmenbuchnummer: digits (1–6) + optional single check letter,
# preceded by an optional court prefix ("FN"). Stored canonical form is
# "<digits><letter>" (no spaces, lower-case letter), e.g. "81476a".
_FN_RE = re.compile(r"^(\d{1,6})([a-z])?$")

# Austrian VAT (UID) — "U" + 8 digits. Canonical form omits the "AT"
# country prefix because VIES wants country code separately.
_UID_RE = re.compile(r"^U\d{8}$")

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


def _normalize_fn(value: str) -> str:
    """Normalize a Firmenbuchnummer to ``<digits><letter?>`` lower-case.

    Accepts forms like ``"FN 81476 a"``, ``"81476a"``, ``"81476 A"``.
    """
    cleaned = value.strip().lower().replace("\xa0", " ")
    if cleaned.startswith("fn"):
        cleaned = cleaned[2:].strip()
    cleaned = cleaned.replace(" ", "").replace("-", "")
    if not _FN_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Austrian Firmenbuchnummer must be digits + optional check letter: {value}"
        )
    return cleaned


def _normalize_uid(value: str) -> str:
    """Normalize an Austrian VAT (UID) to ``U########`` (no "AT" prefix)."""
    cleaned = value.strip().upper().replace(" ", "").replace(".", "").replace("-", "")
    if cleaned.startswith("ATU"):
        cleaned = cleaned[2:]
    elif cleaned.startswith("AT"):
        cleaned = cleaned[2:]
    if cleaned.isdigit() and len(cleaned) == 8:
        cleaned = "U" + cleaned
    if not _UID_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Austrian VAT (UID) must be 'U' + 8 digits, got: {value}"
        )
    return cleaned


class ATAdapter(CountryAdapter):
    country_code = "AT"
    country_name = "Austria"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    async def health_check(self) -> AdapterHealth:
        notes_base = (
            "Free Austrian sources are restricted: Firmenbuch needs ID-Austria, "
            "OffeneRegister.at mirror is offline. Adapter validates AT VAT (UID) "
            "via VIES; FN lookup and name search raise not_implemented."
        )
        vies_status = await self._probe_vies()
        if vies_status is None:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": False, "lookup": True, "financials": False},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=f"{notes_base} VIES probe failed.",
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": False, "lookup": True, "financials": False},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=notes_base,
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Austrian Firmenbuch has no free JSON name-search endpoint; "
            "Justizonline requires ID-Austria and Compass/KSV is paid. "
            "Look up by VAT (ATU########) instead."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.VAT:
            uid = _normalize_uid(value)
            vies = await self._vies_check(uid)
            if vies is None:
                return None
            # VIES for AT does not return company name / address (privacy
            # policy mirrors DE / ES / CY). The validity flag is still a real
            # signal so we surface a CompanyDetails record only when the VAT
            # validated — otherwise the caller cannot distinguish "unknown"
            # from "invalid" and we'd risk attaching no name to a stranger.
            if not vies.get("valid"):
                return None
            name = (vies.get("name") or "").strip()
            address = (vies.get("address") or "").strip()
            return CompanyDetails(
                id=uid,
                name=name or f"AT{uid}",
                country=self.country_code,
                registered_address=address or None,
                identifiers=[
                    RegistryIdentifier(
                        type=IdentifierType.VAT,
                        value=f"AT{uid}",
                        label="UID",
                    ),
                ],
                raw={"vies": vies},
                source_url="https://ec.europa.eu/taxation_customs/vies/",
            )
        if id_type == IdentifierType.COMPANY_NUMBER:
            # Validate the FN format so callers get a clean error instead of
            # silently routing to "not implemented" on garbage input.
            _normalize_fn(value)
            raise AdapterNotImplementedError(
                "Austrian Firmenbuchnummer lookup requires ID-Austria login or "
                "a paid provider (Compass / KSV / Creditsafe). Free MVP cannot "
                "resolve FN to a structured registry record."
            )
        raise InvalidIdentifierError(
            f"AT supports VAT (UID) or COMPANY_NUMBER (FN), got {id_type}"
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        # Austrian filed accounts (Jahresabschluss) live behind a paid
        # Firmenbuch session at €1–€10 per document. Wiener Börse hosts
        # listed-issuer annual reports as PDFs but there is no stable
        # machine-readable feed of those URLs — only TYPO3-rendered issuer
        # pages whose markup changes without warning. Per the project rule
        # against scraping brittle SPA/CMS pages, we surface an empty list
        # rather than fabricating filings or shipping a flaky scraper.
        del company_id, years
        return []

    async def _probe_vies(self) -> bool | None:
        """Return True if VIES responded with a parseable SOAP envelope."""
        # OMV's published UID is a stable AT identifier for liveness probing —
        # we don't care whether it validates today, only that VIES answered.
        result = await self._vies_check("U12832407")
        return True if result is not None else None

    async def _vies_check(self, uid: str) -> dict[str, object] | None:
        envelope = _VIES_ENVELOPE.format(cc="AT", vat=uid)
        headers = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": ""}
        try:
            async with build_http_client(timeout=30.0, headers=headers) as client:
                resp = await client.post(_VIES_URL, content=envelope)
                if resp.status_code != 200:
                    return None
                return _parse_vies_response(resp.text)
        except httpx.HTTPError:
            return None


def _parse_vies_response(xml_text: str) -> dict[str, object] | None:
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
    ).strip().lower() == "true"
    name = (resp.findtext("vies:name", default="", namespaces=_VIES_NS) or "").strip()
    address = (
        resp.findtext("vies:address", default="", namespaces=_VIES_NS) or ""
    ).strip()
    request_date = (
        resp.findtext("vies:requestDate", default="", namespaces=_VIES_NS) or ""
    ).strip()
    # VIES uses "---" for redacted name/address in privacy-restricted
    # member states (AT, DE, ES, CY). Normalise to empty strings so callers
    # don't surface placeholder text.
    if name == "---":
        name = ""
    if address == "---":
        address = ""
    return {
        "valid": valid,
        "name": name,
        "address": address,
        "request_date": request_date,
        "checked_at": datetime.utcnow().isoformat(),
    }
