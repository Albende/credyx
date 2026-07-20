"""Botswana adapter — CIPA OBRS registry + BSE listed-company disclosures.

Free public sources only, no API key:

- **CIPA** (Companies and Intellectual Property Authority) runs a public
  "Search the Register" on its Foster Moore Catalyst platform at
  ``cipa.co.bw/master/ui/start/CIPARegisterSearch``. The old reCAPTCHA-gated
  form is gone: the current portal answers name/number searches over a JSON
  command protocol that needs only a session cookie (issued on the first GET).
  We drive it for ``search_by_name`` and ``lookup_by_identifier``.
- **BSE** (Botswana Stock Exchange) exposes its X-News disclosure feed as a
  free JSON API at ``apis.bse.co.bw``. Each disclosure carries a real,
  downloadable PDF (annual reports, audited financials). We use it for
  ``fetch_financials`` of listed issuers, keyed by BSE ticker / issuer code.

Identifier: CIPA registration number (e.g. ``BW00001731678``). For financials
the BSE issuer code / ticker (e.g. ``SEFA``, ``FNBB``) is accepted.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from packages.adapters._base.adapter import CountryAdapter
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

_NUMBER_IN_LABEL = re.compile(r"^(?P<name>.*?)\s*\((?P<num>[A-Za-z]{2}\d+)\)\s*$")
_YEAR_IN_TEXT = re.compile(r"\b(20\d{2})\b")


def _node_id_before(html: str, marker: str) -> str | None:
    """Return the Catalyst node id that immediately precedes ``marker``.

    The register page embeds its view state as JSON where each node is emitted
    as ``{"id":"<hex>",...,<marker>}``; the id we want is the last one before
    the marker occurrence.
    """
    pos = html.find(marker)
    if pos < 0:
        return None
    window = html[max(0, pos - 400) : pos]
    ids = re.findall(r'"id":"([0-9a-f]{8,})"', window)
    return ids[-1] if ids else None


class BWAdapter(CountryAdapter):
    country_code = "BW"
    country_name = "Botswana"
    identifier_types = [IdentifierType.COMPANY_NUMBER]
    primary_identifier = IdentifierType.COMPANY_NUMBER
    requires_api_key = False
    rate_limit_per_minute = 30

    CIPA_SEARCH_URL = "https://www.cipa.co.bw/master/ui/start/CIPARegisterSearch"
    BSE_NEWS_SEARCH_URL = "https://apis.bse.co.bw/api/v1/x-news-search"
    BSE_ISSUER_URL = "https://www.bse.co.bw"

    async def health_check(self) -> AdapterHealth:
        search_ok = False
        financials_ok = False
        errors: list[str] = []
        try:
            async with build_http_client() as client:
                resp = await get_with_retry(client, self.CIPA_SEARCH_URL)
                search_ok = resp.status_code < 400 and "NameOrNumber" in resp.text
        except Exception as exc:
            errors.append(f"CIPA: {str(exc)[:80]}")
        try:
            async with build_http_client() as client:
                resp = await client.post(
                    self.BSE_NEWS_SEARCH_URL,
                    json={"perpage": "1", "search_word": "SEFA"},
                    headers={"X-Requested-With": "XMLHttpRequest"},
                )
                financials_ok = resp.status_code < 400
        except Exception as exc:
            errors.append(f"BSE: {str(exc)[:80]}")
        status = (
            AdapterStatus.OK
            if search_ok and financials_ok
            else AdapterStatus.DEGRADED
            if search_ok or financials_ok
            else AdapterStatus.ERROR
        )
        return AdapterHealth(
            country_code=self.country_code,
            name=self.country_name,
            status=status,
            capabilities={
                "search": search_ok,
                "lookup": search_ok,
                "financials": financials_ok,
            },
            rate_limit_per_minute=self.rate_limit_per_minute,
            notes=(
                "CIPA OBRS register search + BSE X-News disclosures. "
                "Financials cover BSE-listed issuers only."
                + (f" Probe issues: {'; '.join(errors)}" if errors else "")
            ),
        )

    async def _cipa_query(self, term: str) -> list[dict[str, Any]]:
        """Run a register search and return structured result cards."""
        async with build_http_client() as client:
            page = await get_with_retry(client, self.CIPA_SEARCH_URL)
            session_url = str(page.url)
            name_id = _node_id_before(page.text, '"attribute":"NameOrNumber"')
            search_id = _node_id_before(page.text, '"text":{"label":"Search"}')
            if not name_id or not search_id:
                return []
            headers = {
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            }
            await client.post(
                session_url,
                json={
                    "returnRootHtmlOnChange": False,
                    "returnChangesOnly": True,
                    "commands": [
                        {
                            "type": "view-node-set-attribute-value",
                            "id": name_id,
                            "value": term,
                        }
                    ],
                },
                headers=headers,
            )
            result = await client.post(
                session_url,
                json={
                    "returnRootHtmlOnChange": False,
                    "returnChangesOnly": True,
                    "commands": [
                        {"type": "view-node-button-click", "id": search_id}
                    ],
                },
                headers=headers,
            )
        return self._parse_cards(result.json())

    @staticmethod
    def _parse_cards(payload: dict[str, Any]) -> list[dict[str, Any]]:
        state = {
            k: v for k, v in (payload.get("state") or {}).items() if isinstance(v, dict)
        }

        def descendants(root: str) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            stack = [root]
            while stack:
                node = state.get(stack.pop())
                if not node:
                    continue
                out.append(node)
                stack.extend(node.get("children") or [])
            return out

        cards: list[dict[str, Any]] = []
        for nid, node in state.items():
            if "css-search-result" not in (node.get("dos") or []):
                continue
            card: dict[str, Any] = {}
            for child in descendants(nid):
                dos = child.get("dos") or []
                if child.get("nodetype") == "button" and "searchView" in dos:
                    label = (child.get("text") or {}).get("label", "")
                    m = _NUMBER_IN_LABEL.match(label)
                    if m:
                        card["name"] = m.group("name").strip()
                        card["number"] = m.group("num")
                    else:
                        card["name"] = label.strip()
                attr = child.get("attribute")
                if attr in ("Status", "EntityType", "appCode"):
                    text = child.get("text") or {}
                    card[attr] = text.get("label") or child.get("attributeValue")
                elif attr == "RegistrationDate":
                    card["RegistrationDate"] = child.get("attributeValue")
                elif attr == "FullAddress":
                    card["FullAddress"] = child.get("attributeValue") or card.get(
                        "FullAddress"
                    )
            if card.get("name"):
                cards.append(card)
        return cards

    @staticmethod
    def _parse_reg_date(value: str | None) -> date | None:
        if not value:
            return None
        try:
            return datetime.strptime(value.strip(), "%d %B %Y").date()
        except ValueError:
            return None

    async def search_by_name(self, name: str, limit: int = 10) -> list[CompanyMatch]:
        cards = await self._cipa_query(name.strip())
        matches: list[CompanyMatch] = []
        for card in cards:
            number = card.get("number")
            if not number or (card.get("appCode") or "").lower() != "companies":
                continue
            matches.append(
                CompanyMatch(
                    id=number,
                    name=card["name"],
                    country=self.country_code,
                    identifiers=[
                        RegistryIdentifier(
                            type=IdentifierType.COMPANY_NUMBER, value=number
                        )
                    ],
                    address=card.get("FullAddress") or None,
                    status=card.get("Status"),
                    source_url=self.CIPA_SEARCH_URL,
                )
            )
            if len(matches) >= limit:
                break
        return matches

    async def lookup_by_identifier(
        self, id_type: IdentifierType, value: str
    ) -> CompanyDetails | None:
        target = value.strip().upper()
        cards = await self._cipa_query(target)
        for card in cards:
            if (card.get("number") or "").upper() != target:
                continue
            return CompanyDetails(
                id=card["number"],
                name=card["name"],
                country=self.country_code,
                legal_form=card.get("EntityType"),
                status=card.get("Status"),
                incorporation_date=self._parse_reg_date(card.get("RegistrationDate")),
                registered_address=card.get("FullAddress") or None,
                identifiers=[
                    RegistryIdentifier(
                        type=IdentifierType.COMPANY_NUMBER, value=card["number"]
                    )
                ],
                source_url=self.CIPA_SEARCH_URL,
            )
        return None

    @staticmethod
    def _classify_filing(subject: str) -> FilingType | None:
        s = subject.upper()
        if "AUDITOR" in s and "REPORT" in s:
            return FilingType.AUDIT_REPORT
        if (
            "ANNUAL REPORT" in s
            or "ANNUALREPORT" in s
            or "INTEGRATED ANNUAL" in s
            or "INTEGRATED REPORT" in s
            or "FINANCIAL STATEMENT" in s
            or "ABRIDGED" in s
            or "AUDITED" in s
            or "FINANCIAL RESULT" in s
            or "INTERIM FINANCIAL" in s
        ):
            return FilingType.ANNUAL_REPORT
        return None

    async def fetch_financials(
        self, company_id: str, years: int = 5
    ) -> list[FinancialFiling]:
        query = company_id.strip().upper()
        if not query:
            return []
        rows = await self._bse_disclosures(query)
        if not rows and " " in query:
            rows = await self._bse_disclosures(query.split()[0])

        filings: list[FinancialFiling] = []
        for row in rows:
            instrument = row.get("instrument")
            if not isinstance(instrument, dict):
                continue
            name = (instrument.get("name") or "").upper()
            issuer = (instrument.get("issuer") or "").upper()
            if not (query in name or name in query or query in issuer or issuer in query):
                continue
            subject = (row.get("subject") or "").strip()
            ftype = self._classify_filing(subject)
            pdf = row.get("uploaded_to")
            if not ftype or not pdf:
                continue
            announced = (row.get("dateannounced") or "")[:10]
            year_match = _YEAR_IN_TEXT.search(subject) or _YEAR_IN_TEXT.search(announced)
            if not year_match:
                continue
            filings.append(
                FinancialFiling(
                    company_id=issuer or name or query,
                    year=int(year_match.group(1)),
                    type=ftype,
                    currency="BWP",
                    document_url=pdf,
                    document_format="pdf",
                    source_url=f"{self.BSE_ISSUER_URL}/{(issuer or query).lower()}/",
                )
            )

        filings.sort(key=lambda f: (f.year, f.document_url or ""), reverse=True)
        if years > 0 and filings:
            keep_years = sorted({f.year for f in filings}, reverse=True)[:years]
            filings = [f for f in filings if f.year in keep_years]
        return filings

    async def _bse_disclosures(self, search_word: str) -> list[dict[str, Any]]:
        async with build_http_client() as client:
            resp = await client.post(
                self.BSE_NEWS_SEARCH_URL,
                json={"perpage": "5000", "search_word": search_word},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            payload = resp.json()
        try:
            node = payload[0]["data"]["disclosures"]
        except (KeyError, IndexError, TypeError):
            return []
        rows = node.get("data") if isinstance(node, dict) else node
        return rows if isinstance(rows, list) else []
