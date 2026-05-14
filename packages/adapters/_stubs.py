"""Stub adapters for countries whose live integration isn't built yet.

Spec rule: no mock data. These return AdapterNotImplementedError on calls and
report `not_implemented` health, so the API layer can surface a clear 501.

Each entry below records the official registry name, primary identifier type,
and a short note pointing at the research doc — that way the frontend can show
"coming soon" with real context, not just a blank.
"""
from __future__ import annotations

from packages.adapters._base.adapter import NotImplementedAdapter
from packages.shared.models import IdentifierType


def _stub(cc: str, name: str, identifier_types: list[IdentifierType], notes: str) -> NotImplementedAdapter:
    return NotImplementedAdapter(
        country_code=cc,
        country_name=name,
        identifier_types=identifier_types,
        notes=notes,
    )


def build_stub_registry() -> dict[str, NotImplementedAdapter]:
    return {
        "PL": _stub("PL", "Poland", [IdentifierType.KRS, IdentifierType.NIP, IdentifierType.REGON],
                   "KRS API requires SOAP cert; CEIDG public for sole-traders. See docs/countries/pl.md."),
        "DE": _stub("DE", "Germany", [IdentifierType.HRB, IdentifierType.VAT],
                   "Handelsregister.de bulk data is paywalled; OffeneRegister scrape WIP. See docs/countries/de.md."),
        "ES": _stub("ES", "Spain", [IdentifierType.CIF, IdentifierType.NIF],
                   "BORME publishes daily PDFs; no free structured API. See docs/countries/es.md."),
        "IT": _stub("IT", "Italy", [IdentifierType.VAT, IdentifierType.OTHER],
                   "Registro Imprese requires paid InfoCamere subscription. See docs/countries/it.md."),
        "BE": _stub("BE", "Belgium", [IdentifierType.OTHER, IdentifierType.VAT],
                   "KBO/BCE provides public open data dump (CSV) but no live search. See docs/countries/be.md."),
        "SE": _stub("SE", "Sweden", [IdentifierType.ORG_NR],
                   "Bolagsverket API is paid (Näringslivsregistret). See docs/countries/se.md."),
        "DK": _stub("DK", "Denmark", [IdentifierType.CVR],
                   "CVR open data via virk.dk available; ElasticSearch endpoint needs free key. See docs/countries/dk.md."),
        "IE": _stub("IE", "Ireland", [IdentifierType.COMPANY_NUMBER],
                   "CRO open data PDF docs free; structured per-company API paid. See docs/countries/ie.md."),
        "AT": _stub("AT", "Austria", [IdentifierType.OTHER],
                   "FirmenABC scraping only; Justizportal requires citizen-card login. See docs/countries/at.md."),
        "SK": _stub("SK", "Slovakia", [IdentifierType.ICO],
                   "OR SR provides public scrape; FinStat is paid. See docs/countries/sk.md."),
        "HU": _stub("HU", "Hungary", [IdentifierType.OTHER],
                   "E-cégjegyzék requires Hungarian eID. See docs/countries/hu.md."),
        "RO": _stub("RO", "Romania", [IdentifierType.OTHER],
                   "ONRC requires login; public RECOM is partial. See docs/countries/ro.md."),
        "BG": _stub("BG", "Bulgaria", [IdentifierType.OTHER],
                   "Bulgarian Trade Register requires paid API. See docs/countries/bg.md."),
        "HR": _stub("HR", "Croatia", [IdentifierType.OTHER],
                   "Sudski registar is public web only; scrape needed. See docs/countries/hr.md."),
        "SI": _stub("SI", "Slovenia", [IdentifierType.OTHER],
                   "AJPES has free APIs but registration is per-use case. See docs/countries/si.md."),
        "LT": _stub("LT", "Lithuania", [IdentifierType.OTHER],
                   "Registrų centras: free search, paid extracts. See docs/countries/lt.md."),
        "LV": _stub("LV", "Latvia", [IdentifierType.OTHER],
                   "Lursoft is paid; UR open data partial. See docs/countries/lv.md."),
        "PT": _stub("PT", "Portugal", [IdentifierType.VAT],
                   "Portal da Empresa public search only via web. See docs/countries/pt.md."),
        "LU": _stub("LU", "Luxembourg", [IdentifierType.OTHER],
                   "LBR/RCSL: free PDF search, no JSON API. See docs/countries/lu.md."),
        "MT": _stub("MT", "Malta", [IdentifierType.OTHER],
                   "MBR online search free; per-document fee. See docs/countries/mt.md."),
        "CY": _stub("CY", "Cyprus", [IdentifierType.OTHER],
                   "DRCOR public web search; no structured API. See docs/countries/cy.md."),
        "GR": _stub("GR", "Greece", [IdentifierType.OTHER],
                   "GEMI public web; KYC service is paid. See docs/countries/gr.md."),
        "TR": _stub("TR", "Türkiye", [IdentifierType.VKN, IdentifierType.MERSIS],
                   "Ticaret Sicil + GİB require Turkish eID; MERSIS public partial. See docs/countries/tr.md."),
        "AT": _stub("AT", "Austria", [IdentifierType.OTHER],
                   "FirmenABC scraping only; Justizportal requires citizen-card login. See docs/countries/at.md."),
    }
