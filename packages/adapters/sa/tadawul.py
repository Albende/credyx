"""Saudi Exchange (Tadawul) company-financials scraper.

The main-market company profile portal (WebSphere, behind Akamai) renders
a company's server-side financial-statements table only when a valid
portal render-state token (the ``!ut/p/z1/...`` blob) is present in the
URL. That blob rotates, so we never hard-code one: every profile page
embeds the full issuer directory, and each directory entry carries a
currently-valid profile link. We harvest the directory, pick the target
issuer's own link, and follow it.

Every figure returned comes verbatim from the exchange's rendered
financial-statements table. Nothing here computes or invents a value; a
company match is confirmed only when the issuer's Commercial Registration
number appears in the profile page text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from packages.adapters._base.http import fetch_with_bot_bypass
from packages.shared.models import FilingType, FinancialFiling

BASE = "https://www.saudiexchange.sa"
PROFILE_BASE = BASE + "/wps/portal/saudiexchange/hidden/company-profile-main/"

_DIRECTORY_RE = re.compile(
    r'company:\s*"(?P<symbol>\d+)"\s*,\s*'
    r'companyDisplay:\s*"(?P<name>[^"]+)".*?'
    r'link:\s*"(?P<link>[^"]*company-profile-main[^"]*companySymbol=\d+[^"]*)"',
    re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_YEAR_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


@dataclass(frozen=True)
class Issuer:
    symbol: str
    name: str
    profile_url: str


def _norm(value: str) -> str:
    return re.sub(r"[^A-Z0-9 ]", "", value.upper()).strip()


def _cells(fragment: str, tag: str) -> list[str]:
    return [
        _TAG_RE.sub("", cell).strip()
        for cell in re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", fragment, re.DOTALL)
    ]


async def fetch_directory() -> list[Issuer]:
    html, _status, _source = await fetch_with_bot_bypass(PROFILE_BASE)
    issuers: list[Issuer] = []
    for match in _DIRECTORY_RE.finditer(html):
        link = match.group("link").replace("&amp;", "&")
        issuers.append(
            Issuer(
                symbol=match.group("symbol"),
                name=match.group("name").strip(),
                profile_url=link if link.startswith("http") else BASE + link,
            )
        )
    return issuers


def rank_candidates(
    issuers: list[Issuer], names: list[str]
) -> list[tuple[Issuer, bool]]:
    """Rank issuers by name overlap with the entity's GLEIF name variants.

    Returns ``(issuer, exact)`` pairs, best first. ``exact`` marks an
    exact match against a GLEIF name variant — Tadawul display names are
    unique per issuer and GLEIF stores each entity's official short name,
    so an exact hit is a reliable identification. Weaker (containment or
    token-overlap) hits are left for the caller to confirm against the
    profile page's Commercial Registration number.
    """
    wanted = [_norm(n) for n in names if _norm(n)]
    wanted_flat = [w.replace(" ", "") for w in wanted]
    scored: list[tuple[int, Issuer]] = []
    for issuer in issuers:
        disp = _norm(issuer.name)
        disp_flat = disp.replace(" ", "")
        if not disp_flat:
            continue
        best = 0
        for name, flat in zip(wanted, wanted_flat):
            if disp == name:
                best = max(best, 100)
            elif disp_flat and (disp_flat in flat or flat in disp_flat):
                best = max(best, 40 + min(len(disp_flat), len(flat)))
            else:
                shared = {t for t in set(disp.split()) & set(name.split()) if len(t) >= 4}
                if shared:
                    best = max(best, 10 + len(shared))
        if best:
            scored.append((best, issuer))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [(issuer, score >= 100) for score, issuer in scored]


async def fetch_profile(profile_url: str) -> str:
    html, _status, _source = await fetch_with_bot_bypass(profile_url)
    return html


def page_confirms_cr(html: str, cr: str) -> bool:
    return re.search(rf"Registration\D{{0,60}}{re.escape(cr)}", html) is not None


def parse_financials(
    html: str, *, company_id: str, symbol: str, source_url: str, max_years: int
) -> list[FinancialFiling]:
    anchor = html.find("Total Assets")
    if anchor < 0:
        return []
    start = html.rfind("<table", 0, anchor)
    end = html.find("</table>", anchor)
    if start < 0 or end < 0:
        return []
    table = _COMMENT_RE.sub("", html[start : end + len("</table>")])

    by_year: dict[int, dict[str, object]] = {}
    for block in table.split("<thead")[1:]:
        head, _, body = block.partition("</thead>")
        headers = _cells(head, "th")
        if not headers:
            continue
        section = headers[0].strip()
        columns: list[tuple[int, date] | None] = []
        for header in headers[1:]:
            ym = _YEAR_RE.match(header.strip())
            columns.append(
                (int(ym.group(1)), date(int(ym.group(1)), int(ym.group(2)), int(ym.group(3))))
                if ym
                else None
            )
        body = body.split("<thead")[0]
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.DOTALL):
            cells = _cells(row, "td")
            if len(cells) < 2:
                continue
            label = cells[0].strip()
            if not label:
                continue
            for idx, column in enumerate(columns):
                if column is None or idx + 1 >= len(cells):
                    continue
                value = _parse_number(cells[idx + 1])
                if value is None:
                    continue
                year, period_end = column
                bucket = by_year.setdefault(
                    year, {"period_end": period_end, "statements": {}}
                )
                statements = bucket["statements"]  # type: ignore[assignment]
                statements.setdefault(section, {})[label] = value

    filings: list[FinancialFiling] = []
    for year in sorted(by_year, reverse=True)[: max(1, max_years)]:
        bucket = by_year[year]
        statements = bucket["statements"]
        if not statements:
            continue
        filings.append(
            FinancialFiling(
                company_id=company_id,
                year=year,
                type=FilingType.ANNUAL_REPORT,
                period_end=bucket["period_end"],  # type: ignore[arg-type]
                currency="SAR",
                structured_data={
                    "currency": "SAR",
                    "unit": "SAR '000 (per-share figures in SAR)",
                    "tadawul_symbol": symbol,
                    "statements": statements,
                },
                source_url=source_url,
            )
        )
    return filings


def _parse_number(raw: str) -> float | int | None:
    cleaned = raw.replace(",", "").replace("‏", "").strip()
    if cleaned in ("", "-", "—", "N/A"):
        return None
    try:
        return float(cleaned) if "." in cleaned else int(cleaned)
    except ValueError:
        return None
