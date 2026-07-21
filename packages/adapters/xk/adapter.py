"""Kosovo adapter — ARBK (Agjencia për Regjistrimin e Bizneseve të Kosovës).

Source: https://arbk.rks-gov.net/ — the Kosovo Business Registration Agency
public portal. In 2024 ARBK replaced the legacy ``page.aspx`` server-rendered
site with a React single-page app backed by a JSON API under
``/api/api/``. This adapter talks to that API directly. No API key and no
user registration are required.

Two API traits shape the implementation:

* **Signed request header.** Every call carries a ``key`` header that the
  SPA derives on the fly: ``GET /api/api/Home/GetDate`` returns the server
  time, which is AES-128-CBC encrypted (key = IV = the ASCII literal
  ``8056483646328769``, PKCS7 padding) and base64-encoded. The server
  rejects a stale or missing header, so the key is recomputed per request.
* **Search is Cloudflare-Turnstile walled.** ``Services/KerkoBiznesin``
  requires a Turnstile token minted in a browser and rejects any forged
  value with 401. It is therefore unusable server-side. Instead the adapter
  pulls the agency's own bulk export ``Services/EksportoBiznesetJson`` — a
  ZIP of the full active+historic register (~269k businesses) keyed by the
  Numri Unik Identifikues (NUI). Search and lookup run against that cached
  dump, so both return real registry data key-free.

Identifier:
- COMPANY_NUMBER → the ARBK business number as printed on the register,
  i.e. the NUI. Modern entities carry a 9-digit NUI (e.g. ``810485145``);
  legacy entities carry an 8-digit number, occasionally with a trailing
  letter. Both shapes are accepted and matched against the export verbatim.
- VAT → Numri Fiskal (NF), 9 digits, optionally EU-prefixed ``XK``. The
  free bulk export does not expose the NF, so VAT lookup cannot be resolved
  from it and returns ``None``.

ARBK does not publish filed annual accounts, and Kosovo has no free
machine-readable financial-statement registry (ARBK stores none; the
Central Bank publishes only its own and sector aggregates; the KKRF/POB
registers auditors, not filings). ``fetch_financials`` returns ``[]``
rather than fabricate data.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re
import unicodedata
import zipfile
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters._base.http import build_http_client, get_with_retry
from packages.shared.models import (
    AdapterHealth,
    AdapterStatus,
    CompanyDetails,
    CompanyMatch,
    FinancialFiling,
    IdentifierType,
    RegistryIdentifier,
)

logger = logging.getLogger(__name__)

_UBI_RE = re.compile(r"^\d{8}[A-Z]$")
_NF_RE = re.compile(r"^\d{9}$")
_COMPANY_NUM_RE = re.compile(r"^\d{8}[A-Z]?$|^\d{9}$")

_STATUS_ACTIVE_TOKENS = (
    "aktiv",
    "i regjistruar",
    "e regjistruar",
    "regjistruar",
    "active",
    "registered",
    "aktivan",
)
_STATUS_INACTIVE_TOKENS = (
    "shuar",
    "pasiv",
    "c'regjistruar",
    "ç'regjistruar",
    "çregjistruar",
    "cregjistruar",
    "pezulluar",
    "i pezulluar",
    "falimentuar",
    "ne likuidim",
    "në likuidim",
    "deregistered",
    "dissolved",
    "liquidated",
    "suspended",
    "bankrupt",
    "inactive",
    "closed",
)


def _normalize_ubi(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if not _UBI_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Kosovo business number must be 8 digits + letter (e.g. 70123456A), got: {value}"
        )
    return cleaned


def _normalize_nf(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("XK") and _NF_RE.match(cleaned[2:]):
        cleaned = cleaned[2:]
    if not _NF_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Kosovo fiscal number must be 9 digits, got: {value}"
        )
    return cleaned


def _normalize_company_number(value: str) -> str:
    cleaned = re.sub(r"[\s\-./]", "", value.strip()).upper()
    if not _COMPANY_NUM_RE.match(cleaned):
        raise InvalidIdentifierError(
            "Kosovo business number must be a 9-digit NUI (e.g. 810485145) or a "
            f"legacy 8-digit number, got: {value}"
        )
    return cleaned


def _parse_xk_date(value: str | None) -> date | None:
    if not value:
        return None
    s = value.strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:10].rstrip("/"), fmt).date()
        except ValueError:
            continue
    return None


def _classify_status(raw: str | None) -> str | None:
    if not raw:
        return None
    low = raw.lower()
    if any(token in low for token in _STATUS_INACTIVE_TOKENS):
        return "inactive"
    if any(token in low for token in _STATUS_ACTIVE_TOKENS):
        return "active"
    return raw.strip() or None


def _parse_capital_amount(raw: str | None) -> float | None:
    if not raw:
        return None
    cleaned = re.sub(r"[^\d.,]", "", raw)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")
    else:
        tail = cleaned.rsplit(".", 1)[-1] if "." in cleaned else ""
        if tail and len(tail) == 3:
            cleaned = cleaned.replace(".", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


_AES_SECRET = b"8056483646328769"


def _compute_key(date_str: str) -> str:
    """Reproduce the SPA's ``key`` header: AES-128-CBC(GetDate) → base64.

    Key and IV are both the 16-byte ASCII literal ``8056483646328769``;
    padding is PKCS7. Mirrors the CryptoJS call in the ARBK front end.
    """
    data = date_str.encode("utf-8")
    pad = 16 - (len(data) % 16)
    data += bytes([pad]) * pad
    encryptor = Cipher(algorithms.AES(_AES_SECRET), modes.CBC(_AES_SECRET)).encryptor()
    ciphertext = encryptor.update(data) + encryptor.finalize()
    return base64.b64encode(ciphertext).decode("ascii")


def _fold(value: str) -> str:
    """Diacritic-insensitive, alphanumeric-only casefold for name matching.

    The bulk export loses non-ASCII letters (they arrive as U+FFFD), so
    folding both query and target to bare ASCII is what makes matching
    survive the source's mangled diacritics.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", stripped.lower())


def _dget(record: dict[str, Any], *fragments: str) -> Any:
    """Fetch a dump field by an ASCII fragment of its (possibly mangled) key."""
    for key, val in record.items():
        low = key.lower()
        if all(frag.lower() in low for frag in fragments):
            return val
    return None


def _nace_code(description: str | None) -> str | None:
    if not description:
        return None
    match = re.match(r"\s*(\d{3,5})", description)
    return match.group(1) if match else None


def _slim(record: dict[str, Any]) -> dict[str, Any]:
    number = str(_dget(record, "nr", "biznesit") or "").strip()
    name = str(_dget(record, "emri", "biznesit") or "").strip()
    nace_desc = _dget(record, "nace")
    return {
        "number": number,
        "name": name,
        "name_fold": _fold(name),
        "legal_form": (_dget(record, "lloji", "biznesit") or None),
        "sector": (_dget(record, "sektori") or None),
        "city": (_dget(record, "qyteti") or None),
        "status_raw": (_dget(record, "statusi", "biznesit") or None),
        "nace_description": nace_desc or None,
        "nace_code": _nace_code(nace_desc),
        "employees": _dget(record, "nr", "tor"),
        "size": (_dget(record, "madh") or None),
        "reg_year": _dget(record, "years"),
        "reg_month": (_dget(record, "months") or None),
    }


_DUMP_TTL = timedelta(hours=12)
_dump_records: list[dict[str, Any]] | None = None
_dump_index: dict[str, dict[str, Any]] | None = None
_dump_ts: datetime | None = None
_dump_lock = asyncio.Lock()


class XKAdapter(CountryAdapter):
    country_code = "XK"
    country_name = "Kosovo"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.VAT]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    api_key_env = None
    rate_limit_per_minute = 30

    BASE_URL = "https://arbk.rks-gov.net"
    DATE_PATH = "/api/api/Home/GetDate"
    EXPORT_PATH = "/api/api/Services/EksportoBiznesetJson"
    DETAIL_PATH = "/api/api/Services/TeDhenatBiznesit"

    def _client(self) -> httpx.AsyncClient:
        return build_http_client(
            base_url=self.BASE_URL,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "sq;q=0.9,en;q=0.8",
                "Origin": self.BASE_URL,
                "Referer": f"{self.BASE_URL}/",
            },
            timeout=90.0,
        )

    async def _signed_key(self, client: httpx.AsyncClient) -> str:
        resp = await get_with_retry(client, self.DATE_PATH)
        resp.raise_for_status()
        server_date = resp.text.strip().strip('"')
        return _compute_key(server_date)

    async def _load_dump(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        global _dump_records, _dump_index, _dump_ts
        now = datetime.utcnow()
        if (
            not force_refresh
            and _dump_records is not None
            and _dump_ts is not None
            and now - _dump_ts < _DUMP_TTL
        ):
            return _dump_records

        async with _dump_lock:
            now = datetime.utcnow()
            if (
                not force_refresh
                and _dump_records is not None
                and _dump_ts is not None
                and now - _dump_ts < _DUMP_TTL
            ):
                return _dump_records

            async with self._client() as client:
                key = await self._signed_key(client)
                resp = await get_with_retry(
                    client,
                    self.EXPORT_PATH,
                    params={"Gjuha": "1"},
                    headers={"key": key},
                )
                resp.raise_for_status()
                payload = resp.content

            archive = zipfile.ZipFile(io.BytesIO(payload))
            json_name = next(
                n for n in archive.namelist() if n.lower().endswith(".json")
            )
            raw_records = json.loads(archive.read(json_name).decode("utf-8"))

            records = [_slim(r) for r in raw_records]
            records = [r for r in records if r["number"] and r["name"]]
            _dump_records = records
            _dump_index = {r["number"].upper(): r for r in records}
            _dump_ts = datetime.utcnow()
            logger.info("XK ARBK export loaded: %d businesses", len(records))
            return records

    def _match_from_slim(self, slim: dict[str, Any]) -> CompanyMatch:
        return CompanyMatch(
            id=slim["number"],
            name=slim["name"],
            country=self.country_code,
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=slim["number"],
                    label="Numri Unik Identifikues (NUI)",
                )
            ],
            address=slim.get("city"),
            status=_classify_status(slim.get("status_raw")),
            source_url=f"{self.BASE_URL}/",
        )

    def _details_from_slim(self, slim: dict[str, Any]) -> CompanyDetails:
        return CompanyDetails(
            id=slim["number"],
            name=slim["name"],
            country=self.country_code,
            legal_form=slim.get("legal_form"),
            status=_classify_status(slim.get("status_raw")),
            registered_address=slim.get("city"),
            capital_currency="EUR",
            nace_codes=[slim["nace_code"]] if slim.get("nace_code") else [],
            identifiers=[
                RegistryIdentifier(
                    type=IdentifierType.COMPANY_NUMBER,
                    value=slim["number"],
                    label="Numri Unik Identifikues (NUI)",
                )
            ],
            raw={
                "source": "arbk.rks-gov.net EksportoBiznesetJson",
                "number": slim["number"],
                "sector": slim.get("sector"),
                "nace_description": slim.get("nace_description"),
                "employees": slim.get("employees"),
                "size_band": slim.get("size"),
                "registration_year": slim.get("reg_year"),
                "registration_month": slim.get("reg_month"),
                "status_raw": slim.get("status_raw"),
            },
            source_url=f"{self.BASE_URL}/",
        )

    async def health_check(self) -> AdapterHealth:
        capabilities = {"search": False, "lookup": False, "financials": False}
        try:
            async with self._client() as client:
                key = await self._signed_key(client)
                resp = await get_with_retry(
                    client,
                    self.DETAIL_PATH,
                    params={"nRegjistriId": "1", "Gjuha": "1"},
                    headers={"key": key},
                )
                resp.raise_for_status()
                alive = isinstance(resp.json(), list)
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities=capabilities,
                requires_api_key=False,
                api_key_present=True,
                rate_limit_per_minute=self.rate_limit_per_minute,
                notes=str(exc)[:200],
            )

        capabilities.update({"search": True, "lookup": True})
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK if alive else AdapterStatus.DEGRADED,
            capabilities=capabilities,
            requires_api_key=False,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "Search + lookup live via arbk.rks-gov.net /api/api bulk export. "
                "Financial statements are not published in machine-readable form."
            ),
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        query = _fold(name)
        if not query:
            return []
        records = await self._load_dump()

        exact: list[dict[str, Any]] = []
        prefix: list[dict[str, Any]] = []
        contains: list[dict[str, Any]] = []
        for slim in records:
            folded = slim["name_fold"]
            if not folded:
                continue
            if folded == query:
                exact.append(slim)
            elif folded.startswith(query):
                prefix.append(slim)
            elif query in folded:
                contains.append(slim)
            if len(exact) >= limit:
                break

        ranked = (exact + prefix + contains)[:limit]
        return [self._match_from_slim(s) for s in ranked]

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if id_type == IdentifierType.COMPANY_NUMBER:
            ident = _normalize_company_number(value)
        elif id_type == IdentifierType.VAT:
            _normalize_nf(value)
            logger.info(
                "XK VAT (fiscal number) lookup is not resolvable from the free "
                "ARBK bulk export, which is keyed by NUI only."
            )
            return None
        else:
            raise InvalidIdentifierError(
                "Kosovo adapter only supports COMPANY_NUMBER (NUI) or VAT (NF), "
                f"got {id_type}"
            )

        await self._load_dump()
        slim = _dump_index.get(ident) if _dump_index else None
        if slim is None:
            return None
        return self._details_from_slim(slim)

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        return []
