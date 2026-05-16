"""Tests for the Japan adapter (NTA Houjin-Bangou + EDINET).

Pure unit tests run unconditionally. Integration tests that hit real
APIs are gated on `JP_HOJIN_BANGO_APP_ID` being present and the
`integration` pytest marker.
"""
from __future__ import annotations

import io
import os
import zipfile

import pytest

from packages.adapters.jp import JPAdapter
from packages.adapters.jp.adapter import (
    _normalize_edinet_code,
    _normalize_hojin_bango,
    _parse_edinet_xbrl_zip,
    _select_xbrl_instance,
)
from packages.adapters._base.errors import InvalidIdentifierError
from packages.shared.models import IdentifierType


TOYOTA_HOJIN_BANGO = "1180301018771"
TOYOTA_EDINET = "E02144"

_requires_api_key = pytest.mark.skipif(
    not os.getenv("JP_HOJIN_BANGO_APP_ID"),
    reason="JP_HOJIN_BANGO_APP_ID not set",
)


def test_normalize_hojin_bango_strips_and_validates():
    assert _normalize_hojin_bango("  1180301018771 ") == TOYOTA_HOJIN_BANGO
    assert _normalize_hojin_bango("1180-3010-18771") == TOYOTA_HOJIN_BANGO
    assert _normalize_hojin_bango("JP1180301018771") == TOYOTA_HOJIN_BANGO
    with pytest.raises(InvalidIdentifierError):
        _normalize_hojin_bango("123")
    with pytest.raises(InvalidIdentifierError):
        _normalize_hojin_bango("ABCDEFGHIJKLM")


def test_normalize_edinet_code_validates():
    assert _normalize_edinet_code("e02144") == "E02144"
    with pytest.raises(InvalidIdentifierError):
        _normalize_edinet_code("02144")
    with pytest.raises(InvalidIdentifierError):
        _normalize_edinet_code("E1234")


# ---------- XBRL parser unit tests ----------

_JPCRP_NS = "http://disclosure.edinet-fsa.go.jp/taxonomy/jpcrp/2024-11-01/jpcrp_cor"
_XBRLI_NS = "http://www.xbrl.org/2003/instance"
_XBRLDI_NS = "http://xbrl.org/2006/xbrldi"

_FAKE_INSTANCE_JP_GAAP = f"""<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl
  xmlns:xbrli="{_XBRLI_NS}"
  xmlns:xbrldi="{_XBRLDI_NS}"
  xmlns:jpcrp_cor="{_JPCRP_NS}"
  xmlns:jppfs_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jppfs/2024-11-01/jppfs_cor"
  xmlns:jpcrp030000-asr_E02144-000="http://disclosure.edinet-fsa.go.jp/jpcrp030000-asr_E02144-000">
  <xbrli:context id="CurrentYearInstant">
    <xbrli:entity><xbrli:identifier scheme="http://disclosure.edinet-fsa.go.jp">E02144</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2024-03-31</xbrli:instant></xbrli:period>
    <xbrli:scenario>
      <xbrldi:explicitMember dimension="jpcrp_cor:ConsolidatedOrNonConsolidatedAxis">jpcrp_cor:ConsolidatedMember</xbrldi:explicitMember>
    </xbrli:scenario>
  </xbrli:context>
  <xbrli:context id="CurrentYearDuration">
    <xbrli:entity><xbrli:identifier scheme="http://disclosure.edinet-fsa.go.jp">E02144</xbrli:identifier></xbrli:entity>
    <xbrli:period>
      <xbrli:startDate>2023-04-01</xbrli:startDate>
      <xbrli:endDate>2024-03-31</xbrli:endDate>
    </xbrli:period>
    <xbrli:scenario>
      <xbrldi:explicitMember dimension="jpcrp_cor:ConsolidatedOrNonConsolidatedAxis">jpcrp_cor:ConsolidatedMember</xbrldi:explicitMember>
    </xbrli:scenario>
  </xbrli:context>
  <xbrli:context id="Prior1YearInstant">
    <xbrli:entity><xbrli:identifier scheme="http://disclosure.edinet-fsa.go.jp">E02144</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2023-03-31</xbrli:instant></xbrli:period>
  </xbrli:context>

  <jpcrp_cor:Assets contextRef="CurrentYearInstant" unitRef="JPY" decimals="-6">93601350000000</jpcrp_cor:Assets>
  <jpcrp_cor:Assets contextRef="Prior1YearInstant" unitRef="JPY" decimals="-6">90000000000000</jpcrp_cor:Assets>
  <jpcrp_cor:CurrentAssets contextRef="CurrentYearInstant" unitRef="JPY" decimals="-6">29000000000000</jpcrp_cor:CurrentAssets>
  <jpcrp_cor:Liabilities contextRef="CurrentYearInstant" unitRef="JPY" decimals="-6">55000000000000</jpcrp_cor:Liabilities>
  <jpcrp_cor:NetAssets contextRef="CurrentYearInstant" unitRef="JPY" decimals="-6">38601350000000</jpcrp_cor:NetAssets>
  <jpcrp_cor:CashAndDeposits contextRef="CurrentYearInstant" unitRef="JPY" decimals="-6">8982000000000</jpcrp_cor:CashAndDeposits>
  <jpcrp_cor:NetSales contextRef="CurrentYearDuration" unitRef="JPY" decimals="-6">45095325000000</jpcrp_cor:NetSales>
  <jpcrp_cor:OperatingIncome contextRef="CurrentYearDuration" unitRef="JPY" decimals="-6">5352934000000</jpcrp_cor:OperatingIncome>
  <jpcrp_cor:NetIncomeLoss contextRef="CurrentYearDuration" unitRef="JPY" decimals="-6">4944933000000</jpcrp_cor:NetIncomeLoss>
  <jpcrp_cor:NetCashProvidedByUsedInOperatingActivities contextRef="CurrentYearDuration" unitRef="JPY" decimals="-6">7982000000000</jpcrp_cor:NetCashProvidedByUsedInOperatingActivities>
</xbrli:xbrl>
""".encode("utf-8")


def _make_xbrl_zip(instance_path: str, instance_bytes: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("XBRL/PublicDoc/jpcrp030000-asr-001_E02144-000_2024-03-31_01_2024-06-25.xsd", "schema")
        zf.writestr("XBRL/PublicDoc/jpcrp030000-asr-001_E02144-000_2024-03-31_01_2024-06-25_lab.xml", "label")
        zf.writestr(instance_path, instance_bytes)
        zf.writestr("AuditDoc/header.htm", "ignored")
    return buf.getvalue()


def test_select_xbrl_instance_prefers_publicdoc_xbrl():
    names = [
        "XBRL/PublicDoc/jpcrp030000-asr-001_E02144.xsd",
        "XBRL/PublicDoc/jpcrp030000-asr-001_E02144_lab.xml",
        "XBRL/PublicDoc/jpcrp030000-asr-001_E02144.xbrl",
        "AuditDoc/something.xbrl",
    ]
    chosen = _select_xbrl_instance(names)
    assert chosen == "XBRL/PublicDoc/jpcrp030000-asr-001_E02144.xbrl"


def test_parse_edinet_xbrl_zip_jp_gaap_extracts_known_values():
    payload = _make_xbrl_zip(
        "XBRL/PublicDoc/jpcrp030000-asr-001_E02144-000_2024-03-31_01_2024-06-25.xbrl",
        _FAKE_INSTANCE_JP_GAAP,
    )
    parsed = _parse_edinet_xbrl_zip(payload)
    assert parsed is not None
    assert parsed["currency"] == "JPY"
    assert parsed["period_end"] == "2024-03-31"
    assert parsed["consolidated"] is True

    bs = parsed["balance_sheet"]
    assert bs["total_assets"] == 93601350000000.0
    assert bs["current_assets"] == 29000000000000.0
    assert bs["total_liabilities"] == 55000000000000.0
    assert bs["total_equity"] == 38601350000000.0
    assert bs["cash_and_equivalents"] == 8982000000000.0

    is_ = parsed["income_statement"]
    assert is_["revenue"] == 45095325000000.0
    assert is_["operating_profit"] == 5352934000000.0
    assert is_["net_income"] == 4944933000000.0

    cf = parsed["cash_flow"]
    assert cf["operating_cf"] == 7982000000000.0

    # Prior-year Assets should NOT bleed into structured_data.
    assert parsed["raw_concepts"]["jpcrp_cor:Assets"] == 93601350000000.0


_IFRS_NS = "http://xbrl.ifrs.org/taxonomy/2023-03-23/ifrs-full"

_FAKE_INSTANCE_IFRS = f"""<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl
  xmlns:xbrli="{_XBRLI_NS}"
  xmlns:ifrs-full="{_IFRS_NS}"
  xmlns:jpigp_cor="http://disclosure.edinet-fsa.go.jp/taxonomy/jpigp/2024-11-01/jpigp_cor">
  <xbrli:context id="CurrentYearInstant">
    <xbrli:entity><xbrli:identifier scheme="http://disclosure.edinet-fsa.go.jp">E01777</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2024-03-31</xbrli:instant></xbrli:period>
  </xbrli:context>
  <xbrli:context id="CurrentYearDuration">
    <xbrli:entity><xbrli:identifier scheme="http://disclosure.edinet-fsa.go.jp">E01777</xbrli:identifier></xbrli:entity>
    <xbrli:period>
      <xbrli:startDate>2023-04-01</xbrli:startDate>
      <xbrli:endDate>2024-03-31</xbrli:endDate>
    </xbrli:period>
  </xbrli:context>

  <ifrs-full:Assets contextRef="CurrentYearInstant" unitRef="JPY" decimals="-6">34571000000000</ifrs-full:Assets>
  <ifrs-full:CurrentAssets contextRef="CurrentYearInstant" unitRef="JPY" decimals="-6">15000000000000</ifrs-full:CurrentAssets>
  <ifrs-full:Liabilities contextRef="CurrentYearInstant" unitRef="JPY" decimals="-6">20000000000000</ifrs-full:Liabilities>
  <ifrs-full:Equity contextRef="CurrentYearInstant" unitRef="JPY" decimals="-6">14571000000000</ifrs-full:Equity>
  <ifrs-full:CashAndCashEquivalents contextRef="CurrentYearInstant" unitRef="JPY" decimals="-6">2100000000000</ifrs-full:CashAndCashEquivalents>
  <ifrs-full:Revenue contextRef="CurrentYearDuration" unitRef="JPY" decimals="-6">13020000000000</ifrs-full:Revenue>
  <ifrs-full:ProfitLoss contextRef="CurrentYearDuration" unitRef="JPY" decimals="-6">970000000000</ifrs-full:ProfitLoss>
</xbrli:xbrl>
""".encode("utf-8")


def test_parse_edinet_xbrl_zip_ifrs_extracts_known_values():
    payload = _make_xbrl_zip(
        "XBRL/PublicDoc/jpcrp030000-asr-001_E01777.xbrl",
        _FAKE_INSTANCE_IFRS,
    )
    parsed = _parse_edinet_xbrl_zip(payload)
    assert parsed is not None
    assert parsed["currency"] == "JPY"
    assert parsed["period_end"] == "2024-03-31"
    assert parsed["balance_sheet"]["total_assets"] == 34571000000000.0
    assert parsed["balance_sheet"]["total_equity"] == 14571000000000.0
    assert parsed["balance_sheet"]["cash_and_equivalents"] == 2100000000000.0
    assert parsed["income_statement"]["revenue"] == 13020000000000.0
    assert parsed["income_statement"]["net_income"] == 970000000000.0


def test_parse_edinet_xbrl_zip_returns_none_when_no_instance():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("XBRL/PublicDoc/foo.xsd", "schema")
    assert _parse_edinet_xbrl_zip(buf.getvalue()) is None


# ---------- Integration tests ----------

@_requires_api_key
@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_toyota():
    adapter = JPAdapter()
    matches = await adapter.search_by_name("トヨタ自動車", limit=5)
    assert matches, "expected NTA search to return Toyota Motor results"
    assert any(m.id == TOYOTA_HOJIN_BANGO for m in matches) or any(
        "トヨタ" in m.name for m in matches
    )


@_requires_api_key
@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_toyota_hojin_bango():
    adapter = JPAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, TOYOTA_HOJIN_BANGO
    )
    assert details is not None
    assert details.id == TOYOTA_HOJIN_BANGO
    assert any(
        i.type == IdentifierType.COMPANY_NUMBER and i.value == TOYOTA_HOJIN_BANGO
        for i in details.identifiers
    )


@_requires_api_key
@pytest.mark.asyncio
@pytest.mark.integration
async def test_financials_toyota_returns_at_least_one_yuho():
    adapter = JPAdapter()
    filings = await adapter.fetch_financials(TOYOTA_HOJIN_BANGO, years=3)
    assert filings, "expected at least one Toyota Yuho annual filing on EDINET"
    f = filings[0]
    assert f.document_url and "edinet-fsa.go.jp" in f.document_url
    assert f.document_format == "xbrl"
    assert f.currency == "JPY"


@_requires_api_key
@pytest.mark.asyncio
@pytest.mark.integration
async def test_financials_toyota_has_structured_data():
    adapter = JPAdapter()
    filings = await adapter.fetch_financials(TOYOTA_EDINET, years=2)
    assert filings, "expected at least one Toyota Yuho annual filing on EDINET"
    parsed = [f for f in filings if f.structured_data]
    assert parsed, "expected at least one Toyota filing with parsed XBRL"
    bs = parsed[0].structured_data["balance_sheet"]
    assert bs.get("total_assets", 0) > 0
