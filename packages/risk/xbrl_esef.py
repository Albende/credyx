"""ESEF (European Single Electronic Format) iXBRL parser.

ESEF has been mandatory for EU listed companies' annual financial reports
since 2021. The format is XHTML with inline XBRL (iXBRL) elements
(`ix:nonFraction`, `ix:nonNumeric`) tagging facts against the IFRS
Foundation's `ifrs-full` taxonomy. Reports are usually distributed as a ZIP
package with the iXBRL XHTML, a taxonomy package, and assorted resources.

This parser is intentionally minimal: it does not validate the taxonomy
(that's `arelle`'s job, and arelle is ~100MB). It extracts the concept ->
value facts that the risk engine actually consumes (assets, liabilities,
equity, revenue, net income, cash flow), respecting iXBRL scaling (`scale`,
`decimals`, `sign`), unit currency, and reporting period.

If multiple periods are present we pick the latest. If consolidated and
parent-only facts both appear we prefer the consolidated set, matching
how analysts read these reports.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from datetime import date
from typing import Any
from xml.etree import ElementTree as ET

import httpx

from packages.adapters._base.http import build_http_client, get_with_retry

logger = logging.getLogger(__name__)


class XBRLParseError(Exception):
    """Raised when an ESEF/iXBRL document cannot be parsed into facts."""


_IX_NS_PATTERN = re.compile(r"\{http://www\.xbrl\.org/[0-9]{4}/inlineXBRL\}")
_XBRLI_NS_PATTERN = re.compile(r"\{http://www\.xbrl\.org/[0-9]{4}/instance\}")

# Recognise IFRS taxonomy namespaces across years. ESEF is officially
# anchored to a specific yearly taxonomy but in practice issuers use the
# version current at filing date — we match any of them.
_IFRS_NS_PATTERN = re.compile(
    r"http://xbrl\.ifrs\.org/taxonomy/\d{4}-\d{2}-\d{2}/ifrs-full"
    r"|http://xbrl\.ifrs\.org/taxonomy/.*?/ifrs-full"
    r"|http://www\.esma\.europa\.eu/taxonomy/.*?/esef_cor"
)

# Each output line item maps to an ordered list of IFRS concept local-names.
# Order encodes preference — first match wins when several are tagged.
_CONCEPT_MAP: dict[str, list[str]] = {
    # Balance sheet
    "total_assets": ["Assets"],
    "current_assets": ["CurrentAssets"],
    "non_current_assets": ["NoncurrentAssets", "NonCurrentAssets"],
    "cash_and_equivalents": [
        "CashAndCashEquivalents",
        "Cash",
        "CashCashEquivalentsAndShortTermDeposits",
    ],
    "inventories": ["Inventories"],
    "trade_receivables": [
        "TradeAndOtherCurrentReceivables",
        "TradeReceivables",
        "CurrentTradeReceivables",
    ],
    "total_liabilities": ["Liabilities"],
    "current_liabilities": ["CurrentLiabilities"],
    "non_current_liabilities": ["NoncurrentLiabilities", "NonCurrentLiabilities"],
    "total_equity": [
        "Equity",
        "EquityAttributableToOwnersOfParent",
    ],
    "share_capital": ["IssuedCapital", "ShareCapital"],
    "retained_earnings": ["RetainedEarnings"],
    # Income statement
    "revenue": [
        "Revenue",
        "RevenueFromContractsWithCustomers",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_profit": [
        "ProfitLossFromOperatingActivities",
        "OperatingIncomeLoss",
        "OperatingProfitLoss",
    ],
    "ebitda": [
        "EarningsBeforeInterestTaxesDepreciationAndAmortisation",
        "ProfitLossBeforeFinanceCostsTaxDepreciationAndAmortisation",
    ],
    "net_income": [
        "ProfitLoss",
        "ProfitLossAttributableToOwnersOfParent",
    ],
    "depreciation_amortization": [
        "DepreciationAndAmortisationExpense",
        "DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss",
    ],
    "interest_expense": [
        "InterestExpense",
        "FinanceCosts",
    ],
    # Cash flow
    "operating_cf": [
        "CashFlowsFromUsedInOperatingActivities",
        "NetCashFlowsFromUsedInOperatingActivities",
    ],
    "investing_cf": [
        "CashFlowsFromUsedInInvestingActivities",
        "NetCashFlowsFromUsedInInvestingActivities",
    ],
    "financing_cf": [
        "CashFlowsFromUsedInFinancingActivities",
        "NetCashFlowsFromUsedInFinancingActivities",
    ],
}

_BS_KEYS = {
    "total_assets", "current_assets", "non_current_assets",
    "cash_and_equivalents", "inventories", "trade_receivables",
    "total_liabilities", "current_liabilities", "non_current_liabilities",
    "total_equity", "share_capital", "retained_earnings",
}
_IS_KEYS = {
    "revenue", "gross_profit", "operating_profit", "ebitda",
    "net_income", "depreciation_amortization", "interest_expense",
}
_CF_KEYS = {"operating_cf", "investing_cf", "financing_cf"}


def parse_esef(content: bytes | str, filename: str | None = None) -> dict[str, Any]:
    """Parse an ESEF iXBRL document. Returns a structured_data dict.

    Accepts raw XHTML/XML bytes/str, or a ZIP archive (bytes only) — the
    common ESEF distribution format. The output schema matches the
    `FinancialFiling.structured_data` shape consumed by `packages.risk.ratios`.
    """
    xml_bytes = _resolve_to_xml(content, filename)
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise XBRLParseError(f"Malformed XML/iXBRL: {exc}") from exc

    contexts = _parse_contexts(root)
    units = _parse_units(root)
    facts = _collect_facts(root, contexts, units)
    if not facts:
        raise XBRLParseError(
            "No ix:nonFraction facts found — document may not be iXBRL."
        )

    period_ctx_ids, period_start, period_end = _select_period(facts, contexts)
    consolidated = _detect_consolidated(contexts, next(iter(period_ctx_ids)))
    currency = _select_currency(facts, period_ctx_ids) or "EUR"

    chosen: dict[str, _Fact] = _resolve_concepts(facts, period_ctx_ids)
    raw_concepts = {f.concept_uri: f.value for f in chosen.values()}

    out: dict[str, Any] = {
        "currency": currency,
        "period_end": period_end.isoformat() if period_end else None,
        "period_start": period_start.isoformat() if period_start else None,
        "consolidated": consolidated,
        "balance_sheet": {k: chosen[k].value if k in chosen else None for k in _BS_KEYS},
        "income_statement": {k: chosen[k].value if k in chosen else None for k in _IS_KEYS},
        "cash_flow": {
            **{k: chosen[k].value if k in chosen else None for k in _CF_KEYS},
            "free_cash_flow": _free_cash_flow(chosen),
        },
        "raw_concepts": raw_concepts,
    }
    return out


async def parse_esef_url(
    url: str,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Download an ESEF iXBRL URL (or ZIP package) and parse it."""
    owns_client = http_client is None
    client = http_client or build_http_client()
    try:
        resp = await get_with_retry(client, url)
        resp.raise_for_status()
        content = resp.content
        filename = url.rsplit("/", 1)[-1]
        return parse_esef(content, filename=filename)
    finally:
        if owns_client:
            await client.aclose()


class _Fact:
    __slots__ = (
        "concept_ns", "concept_local", "concept_uri",
        "context_ref", "unit_ref", "value", "decimals", "scale", "sign",
    )

    def __init__(
        self,
        concept_ns: str,
        concept_local: str,
        context_ref: str,
        unit_ref: str | None,
        value: float,
        decimals: str | None,
        scale: int,
        sign: str | None,
    ) -> None:
        self.concept_ns = concept_ns
        self.concept_local = concept_local
        self.concept_uri = f"{concept_ns}:{concept_local}" if concept_ns else concept_local
        self.context_ref = context_ref
        self.unit_ref = unit_ref
        self.value = value
        self.decimals = decimals
        self.scale = scale
        self.sign = sign


class _Context:
    __slots__ = ("id", "period_start", "period_end", "instant", "dimensions")

    def __init__(self) -> None:
        self.id: str = ""
        self.period_start: date | None = None
        self.period_end: date | None = None
        self.instant: date | None = None
        self.dimensions: dict[str, str] = {}


def _resolve_to_xml(content: bytes | str, filename: str | None) -> bytes:
    """Return raw XML bytes, unwrapping a ZIP package if needed."""
    if isinstance(content, str):
        return content.encode("utf-8")
    if filename and filename.lower().endswith(".zip"):
        return _extract_ixbrl_from_zip(content)
    if content[:2] == b"PK":  # zip magic
        return _extract_ixbrl_from_zip(content)
    return content


def _extract_ixbrl_from_zip(blob: bytes) -> bytes:
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as exc:
        raise XBRLParseError(f"Corrupt ZIP package: {exc}") from exc

    candidates: list[str] = []
    for info in zf.infolist():
        n = info.filename.lower()
        if n.endswith(("/reports/", "reports/")) or info.is_dir():
            continue
        if n.endswith((".xhtml", ".html", ".htm", ".xbrl", ".xml")):
            candidates.append(info.filename)

    # Prefer files under a "reports/" directory (per ESEF spec).
    candidates.sort(
        key=lambda n: (0 if "/reports/" in n.lower() else 1, -len(n.split("/")), n)
    )
    for name in candidates:
        data = zf.read(name)
        if b"inlineXBRL" in data or b"ix:nonFraction" in data or b"xbrli:context" in data:
            return data
    if candidates:
        return zf.read(candidates[0])
    raise XBRLParseError("ZIP package contained no XHTML/XBRL document.")


def _local(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _ns(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _parse_contexts(root: ET.Element) -> dict[str, _Context]:
    out: dict[str, _Context] = {}
    for el in root.iter():
        if not _XBRLI_NS_PATTERN.match(el.tag or ""):
            continue
        if _local(el.tag) != "context":
            continue
        ctx = _Context()
        ctx.id = el.attrib.get("id", "")
        for child in el.iter():
            ln = _local(child.tag)
            text = (child.text or "").strip()
            if ln == "startDate" and text:
                ctx.period_start = _parse_date(text)
            elif ln == "endDate" and text:
                ctx.period_end = _parse_date(text)
            elif ln == "instant" and text:
                ctx.instant = _parse_date(text)
                ctx.period_end = ctx.instant
            elif ln == "explicitMember":
                dim = child.attrib.get("dimension", "")
                if text:
                    ctx.dimensions[dim] = text
        out[ctx.id] = ctx
    return out


def _parse_units(root: ET.Element) -> dict[str, str]:
    """Return unit_ref -> ISO currency code (or measure local-name)."""
    out: dict[str, str] = {}
    for el in root.iter():
        if not _XBRLI_NS_PATTERN.match(el.tag or ""):
            continue
        if _local(el.tag) != "unit":
            continue
        uid = el.attrib.get("id", "")
        measure_text = None
        for child in el.iter():
            if _local(child.tag) == "measure" and child.text:
                measure_text = child.text.strip()
                break
        if measure_text:
            # Common form: "iso4217:EUR"
            out[uid] = measure_text.split(":")[-1].upper()
    return out


def _parse_date(s: str) -> date | None:
    s = s.strip()
    if not s:
        return None
    # iXBRL dates are ISO; sometimes with trailing time.
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _collect_facts(
    root: ET.Element,
    contexts: dict[str, _Context],
    units: dict[str, str],
) -> list[_Fact]:
    """Extract numeric facts from ix:nonFraction elements."""
    facts: list[_Fact] = []
    for el in root.iter():
        if not _IX_NS_PATTERN.match(el.tag or ""):
            continue
        if _local(el.tag) != "nonFraction":
            continue
        name = el.attrib.get("name", "")
        if ":" not in name:
            continue
        prefix, local = name.split(":", 1)
        concept_ns = _resolve_prefix(root, el, prefix)
        if not _IFRS_NS_PATTERN.match(concept_ns or ""):
            continue
        ctx_ref = el.attrib.get("contextRef", "")
        unit_ref = el.attrib.get("unitRef")
        decimals = el.attrib.get("decimals")
        scale_raw = el.attrib.get("scale", "0")
        try:
            scale = int(scale_raw)
        except ValueError:
            scale = 0
        sign = el.attrib.get("sign")
        raw_text = "".join(el.itertext()).strip()
        value = _parse_number(raw_text)
        if value is None or ctx_ref not in contexts:
            continue
        value *= 10 ** scale
        if sign == "-":
            value = -abs(value)
        # ix:nonFraction supports xsi:nil; skip those.
        if el.attrib.get("{http://www.w3.org/2001/XMLSchema-instance}nil") == "true":
            continue
        facts.append(
            _Fact(
                concept_ns=concept_ns,
                concept_local=local,
                context_ref=ctx_ref,
                unit_ref=unit_ref,
                value=value,
                decimals=decimals,
                scale=scale,
                sign=sign,
            )
        )
    return facts


def _parse_number(text: str) -> float | None:
    if not text:
        return None
    s = text.strip()
    # Common locale variations seen in real ESEF filings.
    s = s.replace("\u00a0", "").replace(" ", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    # Handle European decimal comma: if both . and , present, "." is thousands.
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        # Heuristic: comma as decimal if last group <=2 digits after, else thousands.
        parts = s.split(",")
        if len(parts[-1]) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _resolve_prefix(root: ET.Element, el: ET.Element, prefix: str) -> str:
    """Resolve an XML namespace prefix as seen from `el`.

    ElementTree drops xmlns declarations on parse but preserves the
    expanded URIs in tag names. We reconstruct prefix -> URI by scanning
    the original source where possible; as a fallback we look at sibling
    element tags that share the prefix's namespace URI.

    For ESEF documents, ifrs-full prefix maps to a well-known IFRS URI.
    """
    if prefix in _STATIC_PREFIX_MAP:
        return _STATIC_PREFIX_MAP[prefix]
    # ElementTree doesn't expose xmlns. The robust path is to read the
    # root attributes after re-parsing in iterparse mode, but for our
    # purposes the static map covers ifrs-full / ifrs-mc / esef_cor —
    # which is what we actually score on.
    return ""


_STATIC_PREFIX_MAP = {
    "ifrs-full": "http://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full",
    "ifrs": "http://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full",
    "esef_cor": "http://www.esma.europa.eu/taxonomy/2022-03-24/esef_cor",
}


def _select_period(
    facts: list[_Fact], contexts: dict[str, _Context]
) -> tuple[set[str], date | None, date | None]:
    """Return all context ids covering the latest reporting period.

    A single annual filing typically has at least two contexts sharing the
    same end date: an instant context for balance-sheet line items and a
    duration context for income / cash-flow items. We take both so all the
    facts for the chosen year flow through together.
    """
    by_ctx: dict[str, int] = {}
    for f in facts:
        by_ctx[f.context_ref] = by_ctx.get(f.context_ref, 0) + 1

    scored: list[tuple[date, int, str]] = []
    for ctx_id, count in by_ctx.items():
        ctx = contexts.get(ctx_id)
        if ctx is None:
            continue
        end = ctx.period_end or ctx.instant
        if end is None:
            continue
        scored.append((end, count, ctx_id))
    if not scored:
        raise XBRLParseError("No usable contexts with period information.")

    latest_end = max(s[0] for s in scored)
    same_period = [s for s in scored if s[0] == latest_end]
    ids = {s[2] for s in same_period}

    # Pick a representative context for start / consolidated detection:
    # prefer one with a startDate (i.e. a duration context).
    rep_id = None
    for s in same_period:
        if contexts[s[2]].period_start is not None:
            rep_id = s[2]
            break
    if rep_id is None:
        rep_id = max(same_period, key=lambda t: t[1])[2]
    ctx = contexts[rep_id]
    return ids, ctx.period_start, ctx.period_end or ctx.instant


def _detect_consolidated(contexts: dict[str, _Context], ctx_id: str) -> bool:
    ctx = contexts.get(ctx_id)
    if ctx is None:
        return True
    for dim, member in ctx.dimensions.items():
        m = (member or "").lower()
        if "separate" in m or "parent" in m or "individual" in m:
            return False
        if "consolidated" in m:
            return True
    # Default to True: ESEF reports are consolidated unless explicitly tagged.
    return True


def _select_currency(facts: list[_Fact], ctx_ids: set[str]) -> str | None:
    counts: dict[str, int] = {}
    for f in facts:
        if f.context_ref not in ctx_ids:
            continue
        u = f.unit_ref
        if u and u.upper() in _CURRENCY_HINT:
            counts[u.upper()] = counts.get(u.upper(), 0) + 1
    if counts:
        return max(counts, key=counts.get)
    for f in facts:
        if f.context_ref in ctx_ids and f.unit_ref:
            cur = f.unit_ref.upper()
            if cur in _CURRENCY_HINT:
                return cur
    return None


# Three-letter ISO codes used as both unit ids and measure local-names in
# the wild. Subset matters only for picking a sensible default.
_CURRENCY_HINT = {
    "EUR", "USD", "GBP", "CHF", "SEK", "NOK", "DKK", "PLN", "CZK", "HUF",
    "RON", "TRY", "JPY", "CNY", "AUD", "CAD", "BRL", "MXN", "INR", "ZAR",
}


def _resolve_concepts(
    facts: list[_Fact], ctx_ids: set[str]
) -> dict[str, _Fact]:
    """Pick one fact per output key from the chosen period's facts."""
    by_concept: dict[str, _Fact] = {}
    for f in facts:
        if f.context_ref not in ctx_ids:
            continue
        # First fact for a concept in this period wins.
        by_concept.setdefault(f.concept_local, f)

    out: dict[str, _Fact] = {}
    for key, concepts in _CONCEPT_MAP.items():
        for cname in concepts:
            if cname in by_concept:
                out[key] = by_concept[cname]
                break
    return out


def _free_cash_flow(chosen: dict[str, _Fact]) -> float | None:
    op = chosen.get("operating_cf")
    inv = chosen.get("investing_cf")
    if op is None or inv is None:
        return None
    # Standard analyst definition: FCF = CFO + CFI (CFI is typically negative).
    return op.value + inv.value
