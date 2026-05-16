"""Japan adapter — NTA Houjin-Bangou + FSA EDINET.

Two free, official, no-paywall sources are stitched together here:

* NTA Houjin-Bangou (National Tax Agency Corporate Number system) for the
  registry data (name, kana, address, status, change history). Requires a
  free application ID (env `JP_HOJIN_BANGO_APP_ID`).
* EDINET (Financial Services Agency) for filed financials of listed
  companies. No auth needed. Returns XBRL/PDF document URLs only — we do
  not download the payload.

Identifiers:
- COMPANY_NUMBER → 13-digit 法人番号 (Hojin-bangō). Primary.
- OTHER          → EDINET code (E + 5 digits) for listed companies.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timedelta
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
from packages.adapters._base.errors import AdapterError, InvalidIdentifierError
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


# XBRL local-name → normalized structured_data key.
# Used for both JP-GAAP (jpcrp_cor, jppfs_cor) and IFRS taxonomies.
_JP_CONCEPT_MAP: dict[str, tuple[str, str]] = {
    # (section, key)
    # --- Balance sheet ---
    "Assets": ("balance_sheet", "total_assets"),
    "CurrentAssets": ("balance_sheet", "current_assets"),
    "Liabilities": ("balance_sheet", "total_liabilities"),
    "CurrentLiabilities": ("balance_sheet", "current_liabilities"),
    "NetAssets": ("balance_sheet", "total_equity"),
    "Equity": ("balance_sheet", "total_equity"),
    "EquityAttributableToOwnersOfParent": ("balance_sheet", "total_equity"),
    "CashAndDeposits": ("balance_sheet", "cash_and_equivalents"),
    "CashAndCashEquivalents": ("balance_sheet", "cash_and_equivalents"),
    # --- Income statement ---
    "NetSales": ("income_statement", "revenue"),
    "Revenue": ("income_statement", "revenue"),
    "RevenueIFRS": ("income_statement", "revenue"),
    "OperatingIncome": ("income_statement", "operating_profit"),
    "OperatingProfitLoss": ("income_statement", "operating_profit"),
    "OperatingProfitLossIFRS": ("income_statement", "operating_profit"),
    "NetIncomeLoss": ("income_statement", "net_income"),
    "ProfitLoss": ("income_statement", "net_income"),
    "ProfitLossIFRS": ("income_statement", "net_income"),
    "ProfitLossAttributableToOwnersOfParent": ("income_statement", "net_income"),
    # --- Cash flow ---
    "NetCashProvidedByUsedInOperatingActivities": ("cash_flow", "operating_cf"),
    "CashFlowsFromUsedInOperatingActivities": ("cash_flow", "operating_cf"),
    "CashFlowsFromUsedInOperatingActivitiesIFRS": ("cash_flow", "operating_cf"),
}

# Namespaces of interest. We match by local-name so the full namespace
# URI varies (taxonomies are versioned by year).
_JP_NS_PREFIXES = (
    "jpcrp_cor",
    "jppfs_cor",
    "ifrs",
    "ifrs-full",
    "jpigp_cor",
)

_HOJIN_BANGO_RE = re.compile(r"^\d{13}$")
_EDINET_CODE_RE = re.compile(r"^E\d{5}$", re.IGNORECASE)


def _normalize_hojin_bango(value: str) -> str:
    cleaned = re.sub(r"[\s\-]", "", value.strip()).upper()
    if cleaned.startswith("JP"):
        cleaned = cleaned[2:]
    if not _HOJIN_BANGO_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"Japan Hojin-bangō must be exactly 13 digits, got: {value}"
        )
    return cleaned


def _normalize_edinet_code(value: str) -> str:
    cleaned = value.strip().upper().replace(" ", "")
    if not _EDINET_CODE_RE.match(cleaned):
        raise InvalidIdentifierError(
            f"EDINET code must be 'E' + 5 digits, got: {value}"
        )
    return cleaned


def _parse_nta_date(s: str | None) -> date | None:
    """NTA returns ISO YYYY-MM-DD; older records sometimes use Wareki (era).

    We only handle ISO confidently; era-formatted strings (e.g. 平成30年4月1日)
    are returned as None rather than guessed.
    """
    if not s:
        return None
    s = s.strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


class JPAdapter(CountryAdapter):
    country_code = "JP"
    country_name = "Japan"
    identifier_types = [IdentifierType.COMPANY_NUMBER, IdentifierType.OTHER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = True
    api_key_env = "JP_HOJIN_BANGO_APP_ID"
    rate_limit_per_minute = 60

    NTA_BASE = "https://api.houjin-bangou.nta.go.jp/4"
    EDINET_BASE = "https://disclosure.edinet-fsa.go.jp/api/v2"

    # Yuho (annual report) deadlines cluster around late June for Mar-end
    # fiscal years. We probe a handful of common reporting-month-ends per
    # year to keep EDINET load reasonable for the MVP.
    _EDINET_PROBE_MONTH_DAYS: tuple[tuple[int, int], ...] = (
        (6, 30),   # Mar-end FY → Yuho due end-of-June
        (8, 31),   # Jun-end FY
        (11, 30),  # Sep-end FY
        (2, 28),   # Dec-end FY → Yuho due end-of-Feb
    )

    def __init__(self, app_id: str | None = None) -> None:
        self.app_id = app_id or os.getenv(self.api_key_env)

    async def health_check(self) -> AdapterHealth:
        if not self.app_id:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.DEGRADED,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=True,
                api_key_present=False,
                notes=f"Set {self.api_key_env} (free NTA app ID) to enable.",
            )
        try:
            async with build_http_client(base_url=self.NTA_BASE) as client:
                resp = await get_with_retry(
                    client,
                    "/name",
                    params={
                        "id": self.app_id,
                        "name": "トヨタ自動車",
                        "type": "12",
                        "mode": "2",
                    },
                )
                if resp.status_code == 401 or resp.status_code == 403:
                    return AdapterHealth(
                        country_code=self.country_code,
                        name=self.country_name,
                        status=AdapterStatus.ERROR,
                        capabilities={"search": False, "lookup": False, "financials": False},
                        requires_api_key=True,
                        api_key_present=True,
                        notes="NTA rejected app ID.",
                    )
                resp.raise_for_status()
                payload = resp.json()
                if not payload.get("corporations"):
                    notes = "NTA reachable but empty result for probe."
                else:
                    notes = None
        except Exception as exc:
            return AdapterHealth(
                country_code=self.country_code,
                name=self.country_name,
                status=AdapterStatus.ERROR,
                capabilities={"search": False, "lookup": False, "financials": False},
                requires_api_key=True,
                api_key_present=True,
                notes=str(exc)[:200],
            )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=AdapterStatus.OK,
            capabilities={"search": True, "lookup": True, "financials": True},
            requires_api_key=True,
            api_key_present=True,
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=notes or "EDINET financials limited to listed-company Yuho filings.",
        )

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        if not self.app_id:
            raise AdapterError(f"Missing env var {self.api_key_env}")
        async with build_http_client(base_url=self.NTA_BASE) as client:
            resp = await get_with_retry(
                client,
                "/name",
                params={
                    "id": self.app_id,
                    "name": name,
                    "type": "12",
                    "mode": "2",
                },
            )
            resp.raise_for_status()
            payload = resp.json()

        corporations = payload.get("corporations") or []
        return [_corporation_to_match(c) for c in corporations[:limit]]

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        if not self.app_id:
            raise AdapterError(f"Missing env var {self.api_key_env}")
        if id_type == IdentifierType.COMPANY_NUMBER:
            return await self._lookup_by_hojin_bango(value)
        if id_type == IdentifierType.OTHER:
            return await self._lookup_by_edinet_code(value)
        raise InvalidIdentifierError(
            f"Japan adapter only supports COMPANY_NUMBER or OTHER (EDINET), got {id_type}"
        )

    async def _lookup_by_hojin_bango(self, value: str) -> CompanyDetails | None:
        number = _normalize_hojin_bango(value)
        async with build_http_client(base_url=self.NTA_BASE) as client:
            resp = await get_with_retry(
                client,
                "/num",
                params={
                    "id": self.app_id,
                    "number": number,
                    "type": "12",
                },
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            payload = resp.json()

        corporations = payload.get("corporations") or []
        if not corporations:
            return None
        return _corporation_to_details(corporations[0])

    async def _lookup_by_edinet_code(self, value: str) -> CompanyDetails | None:
        code = _normalize_edinet_code(value)
        async with build_http_client(base_url=self.EDINET_BASE) as client:
            for d in _recent_probe_dates(years=1, probes=self._EDINET_PROBE_MONTH_DAYS):
                resp = await get_with_retry(
                    client,
                    "/documents.json",
                    params={"date": d.isoformat(), "type": "2"},
                )
                if resp.status_code != 200:
                    continue
                results = (resp.json() or {}).get("results") or []
                for r in results:
                    if (r.get("edinetCode") or "").upper() == code:
                        return _edinet_doc_to_details(r, code)
                await asyncio.sleep(0.1)
        return None

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        if not self.app_id:
            raise AdapterError(f"Missing env var {self.api_key_env}")

        edinet_code: str | None = None
        filer_name_hint: str | None = None

        if _EDINET_CODE_RE.match(company_id.strip().upper()):
            edinet_code = _normalize_edinet_code(company_id)
        else:
            number = _normalize_hojin_bango(company_id)
            details = await self._lookup_by_hojin_bango(number)
            if details is None:
                return []
            filer_name_hint = details.name

        filings: list[FinancialFiling] = []
        seen_doc_ids: set[str] = set()

        async with build_http_client(base_url=self.EDINET_BASE) as client:
            for d in _recent_probe_dates(years=years, probes=self._EDINET_PROBE_MONTH_DAYS):
                resp = await get_with_retry(
                    client,
                    "/documents.json",
                    params={"date": d.isoformat(), "type": "2"},
                )
                if resp.status_code != 200:
                    continue
                results = (resp.json() or {}).get("results") or []
                for r in results:
                    doc_id = r.get("docID")
                    if not doc_id or doc_id in seen_doc_ids:
                        continue
                    if not _matches_filer(r, edinet_code, filer_name_hint):
                        continue
                    if r.get("docTypeCode") != "120":
                        continue
                    period_end = _parse_nta_date(r.get("periodEnd"))
                    if period_end is None:
                        sub = r.get("submitDateTime") or ""
                        period_end = _parse_nta_date(sub[:10])
                    if period_end is None:
                        continue
                    seen_doc_ids.add(doc_id)
                    structured = await self._fetch_and_parse_edinet_xbrl(doc_id)
                    filings.append(
                        FinancialFiling(
                            company_id=company_id,
                            year=period_end.year,
                            type=FilingType.ANNUAL_REPORT,
                            period_end=period_end,
                            currency="JPY",
                            structured_data=structured,
                            document_url=(
                                f"{self.EDINET_BASE}/documents/{doc_id}?type=1"
                            ),
                            document_format="xbrl",
                            source_url=(
                                f"https://disclosure.edinet-fsa.go.jp/E01EW/"
                                f"download?uji.verb=W1E62071&uji.bean=ee.bean."
                                f"W1E62071.EEW1E62071Bean&TID={doc_id}"
                            ),
                        )
                    )
                await asyncio.sleep(0.1)

        filings.sort(key=lambda f: f.period_end or date.min, reverse=True)
        return filings

    async def _fetch_and_parse_edinet_xbrl(self, doc_id: str) -> dict[str, Any] | None:
        """Download an EDINET XBRL ZIP and parse it into structured_data.

        Returns None (with a warning log) on any failure — the document URL
        on the filing is still useful even if the structured parse fails.
        """
        url = f"{self.EDINET_BASE}/documents/{doc_id}"
        try:
            async with build_http_client(timeout=60.0) as client:
                resp = await client.get(url, params={"type": "1"})
                if resp.status_code != 200:
                    logger.warning(
                        "EDINET XBRL fetch for %s returned HTTP %d",
                        doc_id, resp.status_code,
                    )
                    return None
                content_type = resp.headers.get("content-type", "")
                if "zip" not in content_type and "octet-stream" not in content_type:
                    logger.warning(
                        "EDINET XBRL fetch for %s returned non-zip content-type %r",
                        doc_id, content_type,
                    )
                    return None
                payload = resp.content
        except Exception as exc:
            logger.warning("EDINET XBRL fetch for %s failed: %s", doc_id, exc)
            return None

        try:
            return _parse_edinet_xbrl_zip(payload)
        except Exception as exc:
            logger.warning("EDINET XBRL parse for %s failed: %s", doc_id, exc)
            return None


def _recent_probe_dates(
    *,
    years: int,
    probes: tuple[tuple[int, int], ...],
) -> list[date]:
    """Pick the small set of likely Yuho-filing dates over the last `years`."""
    today = datetime.utcnow().date()
    out: list[date] = []
    for offset in range(0, years + 1):
        target_year = today.year - offset
        for month, day in probes:
            try:
                d = date(target_year, month, day)
            except ValueError:
                continue
            if d <= today:
                out.append(d)
    return sorted(out, reverse=True)


def _matches_filer(
    record: dict[str, Any],
    edinet_code: str | None,
    filer_name_hint: str | None,
) -> bool:
    if edinet_code:
        return (record.get("edinetCode") or "").upper() == edinet_code
    if filer_name_hint:
        filer = (record.get("filerName") or "").strip()
        if not filer:
            return False
        needle = filer_name_hint.strip()
        return needle in filer or filer in needle
    return False


def _corporation_to_match(c: dict[str, Any]) -> CompanyMatch:
    number = c.get("corporateNumber") or c.get("number") or ""
    name = c.get("name") or ""
    return CompanyMatch(
        id=number,
        name=name,
        country="JP",
        identifiers=[
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=number,
                label="法人番号",
            ),
        ],
        address=_join_address(c),
        status=c.get("latest") and "active" or None,
        source_url=(
            f"https://www.houjin-bangou.nta.go.jp/henkorireki-johoto.html?selHouzinNo={number}"
            if number else None
        ),
    )


def _corporation_to_details(c: dict[str, Any]) -> CompanyDetails:
    number = c.get("corporateNumber") or c.get("number") or ""
    name = c.get("name") or ""
    return CompanyDetails(
        id=number,
        name=name,
        country="JP",
        legal_form=c.get("kind"),
        status="active" if c.get("latest") else (c.get("status") or None),
        incorporation_date=_parse_nta_date(c.get("assignmentDate")),
        dissolution_date=_parse_nta_date(c.get("closeDate")),
        registered_address=_join_address(c),
        identifiers=[
            RegistryIdentifier(
                type=IdentifierType.COMPANY_NUMBER,
                value=number,
                label="法人番号",
            ),
        ],
        raw=c,
        source_url=(
            f"https://www.houjin-bangou.nta.go.jp/henkorireki-johoto.html?selHouzinNo={number}"
            if number else None
        ),
    )


def _edinet_doc_to_details(r: dict[str, Any], edinet_code: str) -> CompanyDetails:
    filer = r.get("filerName") or ""
    return CompanyDetails(
        id=edinet_code,
        name=filer,
        country="JP",
        legal_form=None,
        status="active",
        registered_address=None,
        identifiers=[
            RegistryIdentifier(
                type=IdentifierType.OTHER,
                value=edinet_code,
                label="EDINET code",
            ),
        ],
        raw=r,
        source_url=(
            "https://disclosure.edinet-fsa.go.jp/E01EW/BLMainController.jsp"
            f"?uji.verb=W1E62071Disp&uji.bean=ee.bean.W1E62071.EEW1E62071Bean"
            f"&edinetCode={edinet_code}"
        ),
    )


def _join_address(c: dict[str, Any]) -> str | None:
    parts = [
        c.get("prefectureName"),
        c.get("cityName"),
        c.get("streetNumber"),
        c.get("addressOutside"),
    ]
    parts = [p for p in parts if p]
    return "".join(parts) if parts else None


def _parse_edinet_xbrl_zip(payload: bytes) -> dict[str, Any] | None:
    """Pull the instance XBRL out of an EDINET ZIP and reduce it to facts.

    EDINET ZIPs lay the instance document under
    `XBRL/PublicDoc/jpcrp030000-asr-*.xbrl` (or similar). We pick the
    first `.xbrl` file under `PublicDoc/` whose name does not look like a
    schema (`.xsd`) or linkbase (`*lab*.xml`, `*pre*.xml`, etc.).
    """
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        instance_name = _select_xbrl_instance(zf.namelist())
        if instance_name is None:
            return None
        with zf.open(instance_name) as fh:
            xml_bytes = fh.read()

    return _parse_xbrl_instance_bytes(xml_bytes)


def _select_xbrl_instance(names: list[str]) -> str | None:
    candidates = [
        n for n in names
        if n.lower().endswith(".xbrl") and "/PublicDoc/" in n.replace("\\", "/")
    ]
    if not candidates:
        candidates = [n for n in names if n.lower().endswith(".xbrl")]
    if not candidates:
        return None
    # Prefer the shortest path → typically the root instance, not a sub-doc.
    candidates.sort(key=lambda n: (len(n), n))
    return candidates[0]


def _parse_xbrl_instance_bytes(xml_bytes: bytes) -> dict[str, Any] | None:
    """Walk an XBRL instance, keep facts whose prefix we care about."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    # Build a {context_id: (period_end_date, consolidated_bool|None)} map.
    contexts = _index_contexts(root)
    # Pick the dominant period_end across all facts we touch.
    best_period_end: date | None = None
    consolidated: bool | None = None

    balance_sheet: dict[str, float] = {}
    income_statement: dict[str, float] = {}
    cash_flow: dict[str, float] = {}
    raw_concepts: dict[str, float] = {}

    # Track per-bucket best (date, consolidated, value) so we always pick
    # the most recent CurrentYearDuration / CurrentYearInstant non-member
    # ("ConsolidatedMember" preferred) context per concept.
    bucket_best: dict[tuple[str, str], tuple[int, float]] = {}

    for elem in root.iter():
        tag = elem.tag
        if "}" not in tag:
            continue
        ns, local = tag[1:].split("}", 1)
        prefix = _prefix_for_namespace(ns)
        if prefix is None:
            continue
        mapping = _JP_CONCEPT_MAP.get(local)
        if mapping is None:
            continue
        ctx_ref = elem.attrib.get("contextRef")
        text = (elem.text or "").strip()
        if not ctx_ref or not text:
            continue
        try:
            value = float(text)
        except ValueError:
            continue
        ctx = contexts.get(ctx_ref)
        if ctx is None:
            continue
        ctx_period_end, ctx_consolidated, ctx_kind = ctx
        if ctx_kind != "current":
            continue

        section, key = mapping
        # Rank: prefer consolidated contexts, then non-segment contexts.
        rank = 0
        if ctx_consolidated is True:
            rank += 2
        if ctx_consolidated is None:
            rank += 1

        bucket_key = (section, key)
        prior = bucket_best.get(bucket_key)
        if prior is None or rank > prior[0]:
            bucket_best[bucket_key] = (rank, value)
            if section == "balance_sheet":
                balance_sheet[key] = value
            elif section == "income_statement":
                income_statement[key] = value
            elif section == "cash_flow":
                cash_flow[key] = value
            raw_concepts[f"{prefix}:{local}"] = value
            if ctx_period_end is not None and (
                best_period_end is None or ctx_period_end > best_period_end
            ):
                best_period_end = ctx_period_end
            if ctx_consolidated is True:
                consolidated = True
            elif consolidated is None and ctx_consolidated is False:
                consolidated = False

    if not (balance_sheet or income_statement or cash_flow):
        return None

    return {
        "currency": "JPY",
        "period_end": best_period_end.isoformat() if best_period_end else None,
        "consolidated": True if consolidated is None else consolidated,
        "balance_sheet": balance_sheet,
        "income_statement": income_statement,
        "cash_flow": cash_flow,
        "raw_concepts": raw_concepts,
    }


def _prefix_for_namespace(ns: str) -> str | None:
    """Map an XBRL namespace URI to a short prefix we care about."""
    low = ns.lower()
    if "jpcrp" in low:
        return "jpcrp_cor"
    if "jppfs" in low:
        return "jppfs_cor"
    if "jpigp" in low:
        return "jpigp_cor"
    if "xbrl.ifrs.org" in low or "/ifrs-full" in low or low.endswith("/ifrs"):
        return "ifrs"
    if low.endswith("/ifrs-full"):
        return "ifrs-full"
    return None


def _index_contexts(
    root: ET.Element,
) -> dict[str, tuple[date | None, bool | None, str]]:
    """Return {contextRef: (period_end, consolidated?, kind)}.

    `kind` is "current" for CurrentYear* contexts (the reporting period),
    "prior" for Prior*, "other" otherwise — we only keep facts in current
    contexts for structured_data.
    """
    out: dict[str, tuple[date | None, bool | None, str]] = {}
    for ctx in root.iter():
        tag = ctx.tag
        if "}" not in tag:
            continue
        _, local = tag[1:].split("}", 1)
        if local != "context":
            continue
        ctx_id = ctx.attrib.get("id") or ""
        period_end = _context_period_end(ctx)
        consolidated = _context_consolidated_flag(ctx)
        kind = _context_kind_from_id(ctx_id)
        out[ctx_id] = (period_end, consolidated, kind)
    return out


def _context_period_end(ctx: ET.Element) -> date | None:
    for el in ctx.iter():
        if "}" not in el.tag:
            continue
        _, local = el.tag[1:].split("}", 1)
        if local in ("endDate", "instant"):
            return _parse_nta_date((el.text or "").strip())
    return None


def _context_consolidated_flag(ctx: ET.Element) -> bool | None:
    """True if ConsolidatedMember in segment, False if NonConsolidated, else None."""
    for el in ctx.iter():
        if "}" not in el.tag:
            continue
        _, local = el.tag[1:].split("}", 1)
        if local != "explicitMember":
            continue
        text = (el.text or "")
        if "ConsolidatedMember" in text and "Non" not in text:
            return True
        if "NonConsolidatedMember" in text:
            return False
    return None


def _context_kind_from_id(ctx_id: str) -> str:
    if ctx_id.startswith("CurrentYear"):
        return "current"
    if ctx_id.startswith("Prior"):
        return "prior"
    return "other"
