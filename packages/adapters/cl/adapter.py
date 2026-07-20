"""Chile adapter — SII (Servicio de Impuestos Internos) + CMF (listed only).

Sources:
- SII RUT verifier: https://zeus.sii.cl/cvc_cgi/stc/getstc — HTML form, free.
  In practice the public endpoint requires a CAPTCHA token; when that
  guard fires we raise `BlockedByRegistryError` rather than fabricate
  data. Direct GETs occasionally succeed for cached high-volume RUTs
  (large enterprises), so we still try and parse what comes back.
- CMF (Comisión para el Mercado Financiero) entity portal:
  https://www.cmfchile.cl/institucional/mercados/entidad.php?rut={RUT_NODV}
  — free per-entity discovery page for supervised (listed/banking/
  insurance) entities. We surface this as a `FinancialFiling`
  `document_url` so the UI can drill into annual reports; structured
  line items would require parsing the multi-page filings index and
  is left for Phase 2.

Identifier: **RUT** (Rol Único Tributario) — 7-9 numeric digits plus a
Mod-11 check digit ("0"-"9" or "K"), displayed as `XX.XXX.XXX-X`. The
RUT doubles as the corporate tax ID, so we expose it as the primary
`VAT` identifier and also accept `COMPANY_NUMBER` as an alias.

Name search is not freely available — SII has no search-by-name API and
the only directory (datos.gob.cl tax bundles) is a 5+ GB monthly dump
that is out of scope for live querying. `search_by_name` therefore
raises `AdapterNotImplementedError`.
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime
from typing import Any

import httpx

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import (
    AdapterNotImplementedError,
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

_DIGITS_RE = re.compile(r"\D+")
_RUT_RE = re.compile(r"^(\d{7,9})([0-9K])$")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _normalize_rut(value: str) -> tuple[str, str]:
    """Strip "CL"/dots/dashes/spaces, return (digits, check_char).

    Validates Mod-11 checksum and raises `InvalidIdentifierError` on
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
        # Insert thousands separators from the right.
        body = digits[: n - 6] + "." + digits[n - 6 : n - 3] + "." + digits[n - 3 :]
        body = body.lstrip(".")
    else:
        body = digits
    return f"{body}-{check}"


def _strip_html(text: str) -> str:
    no_tags = _TAG_RE.sub(" ", text)
    decoded = html.unescape(no_tags)
    return _WS_RE.sub(" ", decoded).strip()


class CLAdapter(CountryAdapter):
    country_code = "CL"
    country_name = "Chile"
    identifier_types = [IdentifierType.VAT, IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.VAT
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    SII_BASE = "https://zeus.sii.cl"
    SII_PATH = "/cvc_cgi/stc/getstc"
    CMF_ENTIDAD_URL = (
        "https://www.cmfchile.cl/institucional/mercados/entidad.php"
    )

    async def health_check(self) -> AdapterHealth:
        # Probe SII with a known well-formed RUT (Empresas COPEC) and report
        # whether the CAPTCHA wall is in force right now.
        try:
            async with self._sii_client() as client:
                resp = await get_with_retry(
                    client,
                    self.SII_PATH,
                    params=self._sii_params("90690000", "9"),
                )
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                notes=str(exc)[:200],
            )
        body = resp.text or ""
        if _is_captcha_response(body):
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.BLOCKED,
                capabilities={"search": False, "lookup": False, "financials": True},
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=(
                    "SII RUT verifier requires CAPTCHA; direct HTTP lookup "
                    "blocked. CMF discovery URL still available for listed "
                    "entities."
                ),
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": False, "lookup": True, "financials": True},
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Name search unavailable (SII has no free name API). "
                "Financials limited to CMF-supervised entities (URL only)."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        raise AdapterNotImplementedError(
            "Chilean SII does not expose a free name search; only the monthly "
            "datos.gob.cl tax dump lists companies by name and that is "
            "out-of-band. Use direct RUT lookup."
        )

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type not in (IdentifierType.VAT, IdentifierType.COMPANY_NUMBER):
            raise InvalidIdentifierError(
                f"CL only supports VAT/COMPANY_NUMBER (RUT), got {id_type}"
            )
        digits, check = _normalize_rut(value)
        rut_display = _format_rut(digits, check)

        try:
            async with self._sii_client() as client:
                resp = await get_with_retry(
                    client,
                    self.SII_PATH,
                    params=self._sii_params(digits, check),
                )
        except httpx.HTTPError as exc:
            raise BlockedByRegistryError(
                f"SII transport error for RUT {rut_display}: {exc}"
            ) from exc

        if resp.status_code == 404:
            return None
        if resp.status_code >= 500:
            raise BlockedByRegistryError(
                f"SII returned HTTP {resp.status_code} for RUT {rut_display}"
            )
        body = resp.text or ""
        if _is_captcha_response(body):
            raise BlockedByRegistryError(
                "SII RUT verifier requires CAPTCHA. Direct HTTP lookup blocked; "
                "a browser/captcha-solving pipeline is required."
            )

        parsed = _parse_sii_response(body)
        if parsed is None:
            return None
        name, status_value, activities = parsed

        identifiers = [
            RegistryIdentifier(
                type=IdentifierType.VAT, value=rut_display, label="RUT"
            ),
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=rut_display,
                label="RUT",
            ),
        ]

        return CompanyDetails(
            id=rut_display,
            name=name,
            country="CL",
            status=status_value,
            registered_address=None,
            nace_codes=[code for code, _ in activities],
            identifiers=identifiers,
            raw={
                "rut": rut_display,
                "activities": [
                    {"code": code, "description": desc}
                    for code, desc in activities
                ],
                "source": "sii.zeus.cvc_cgi/stc/getstc",
            },
            source_url=(
                f"{self.SII_BASE}{self.SII_PATH}"
                f"?RUT={digits}&DV={check}&PRG=STC&OPC=NOR"
            ),
        )

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        digits, check = _normalize_rut(company_id)
        rut_display = _format_rut(digits, check)
        cmf_url = (
            f"{self.CMF_ENTIDAD_URL}?mercado=V&rut={digits}&grupo="
            "&tipoentidad=RGC&row=&vig=VI&control=svs&pestania=1"
        )
        current_year = datetime.utcnow().year
        # CMF only supervises listed/banking/insurance entities; for everyone
        # else the URL will load an empty result. We can't reliably tell from
        # outside without making the call, and a failed request shouldn't
        # poison the lookup. Surface a discovery pointer for the most recent
        # `years` cycles and let downstream decide whether to drill in.
        filings: list[FinancialFiling] = []
        for offset in range(years):
            yr = current_year - 1 - offset
            filings.append(
                FinancialFiling(
                    company_id=rut_display,
                    year=yr,
                    type=FilingType.ANNUAL_REPORT,
                    period_end=date(yr, 12, 31),
                    currency="CLP",
                    structured_data=None,
                    document_url=None,
                    document_format=None,
                    source_url=cmf_url,
                )
            )
        return filings

    def _sii_client(self) -> httpx.AsyncClient:
        # SII is picky about Accept headers; mimic a normal browser without
        # claiming to be one.
        return build_http_client(
            base_url=self.SII_BASE,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "es-CL,es;q=0.9,en;q=0.7",
            },
            timeout=25.0,
        )

    @staticmethod
    def _sii_params(digits: str, check: str) -> dict[str, str]:
        return {
            "RUT": digits,
            "DV": check,
            "PRG": "STC",
            "OPC": "NOR",
        }


def _is_captcha_response(body: str) -> bool:
    lowered = body.lower()
    return (
        "captcha" in lowered
        or "reingrese" in lowered
        or "history.go(-1)" in lowered
    )


def _parse_sii_response(body: str) -> tuple[str, str | None, list[tuple[str, str]]] | None:
    """Best-effort scrape of the SII stc response page.

    The page is a small HTML form-result with labelled fields like
    "Razón Social", "Contribuyente presenta las siguientes
    Actividades Económicas vigentes", etc. Layout has changed several
    times — match leniently and never fabricate values.
    """
    if not body or "<" not in body:
        return None

    text = _strip_html(body)
    if not text:
        return None

    # SII labels (defensive against accented vs. non-accented variants).
    name = _extract_label(
        text,
        labels=(
            "Razón Social",
            "Razon Social",
            "Nombre o Razón Social",
            "Nombre o Razon Social",
            "Contribuyente",
        ),
    )
    if not name:
        return None

    status_value = _extract_label(
        text,
        labels=(
            "Inicio de Actividades",
            "Estado del Contribuyente",
            "Situación",
        ),
    )

    activities = _extract_activities(text)
    return name, status_value, activities


def _extract_label(text: str, *, labels: tuple[str, ...]) -> str | None:
    """Find the first occurrence of any label and return the value after it.

    Values run until the next label or end of segment; we cap at 200 chars.
    """
    for label in labels:
        idx = text.lower().find(label.lower())
        if idx < 0:
            continue
        rest = text[idx + len(label) :].lstrip(" :-\t")
        if not rest:
            continue
        # Cut at the next obvious label boundary.
        cut = re.split(
            r"\s{2,}|(?=Actividades?\s+Económic|Inicio de Actividades|"
            r"Situaci[oó]n|Estado del Contribuyente|Tipo de Contribuyente)",
            rest,
            maxsplit=1,
        )
        candidate = (cut[0] if cut else rest).strip(" :,-")
        if candidate:
            return candidate[:200]
    return None


def _extract_activities(text: str) -> list[tuple[str, str]]:
    """Extract (CIIU code, description) pairs from the SII activities block.

    SII publishes one or more economic-activity rows; each row contains a
    6-digit CIIU code adjacent to the human description. We scan for the
    code pattern and capture a short window of preceding/following text.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in re.finditer(r"(?<!\d)(\d{6})(?!\d)", text):
        code = m.group(1)
        if code in seen:
            continue
        seen.add(code)
        start = max(0, m.start() - 120)
        end = min(len(text), m.end() + 60)
        snippet = text[start:end].strip()
        snippet = snippet.replace(code, "").strip(" -|,:")
        if snippet:
            out.append((code, snippet[:160]))
        else:
            out.append((code, ""))
        if len(out) >= 10:
            break
    return out
