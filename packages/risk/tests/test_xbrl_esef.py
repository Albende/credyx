"""Unit tests for the ESEF iXBRL parser.

All fixtures here are minimal hand-built iXBRL documents that exercise the
parser code paths. No network access; no real filings bundled. The IFRS
namespace is the official 2024-03-27 taxonomy URL — issuers vary but the
parser normalises across the patterns documented in `xbrl_esef.py`.
"""
from __future__ import annotations

import io
import zipfile

import pytest

from packages.risk import parse_esef
from packages.risk.xbrl_esef import XBRLParseError


_IFRS_NS = "http://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full"


def _doc(
    facts_xml: str,
    *,
    contexts_xml: str | None = None,
    units_xml: str | None = None,
) -> str:
    if contexts_xml is None:
        contexts_xml = """
            <xbrli:context id="C_2024">
              <xbrli:entity><xbrli:identifier scheme="http://lei">5493000000000000XXXX</xbrli:identifier></xbrli:entity>
              <xbrli:period>
                <xbrli:startDate>2024-01-01</xbrli:startDate>
                <xbrli:endDate>2024-12-31</xbrli:endDate>
              </xbrli:period>
            </xbrli:context>
            <xbrli:context id="C_2024_INSTANT">
              <xbrli:entity><xbrli:identifier scheme="http://lei">5493000000000000XXXX</xbrli:identifier></xbrli:entity>
              <xbrli:period>
                <xbrli:instant>2024-12-31</xbrli:instant>
              </xbrli:period>
            </xbrli:context>
        """
    if units_xml is None:
        units_xml = """
            <xbrli:unit id="EUR"><xbrli:measure>iso4217:EUR</xbrli:measure></xbrli:unit>
        """
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
      xmlns:ifrs-full="{_IFRS_NS}">
  <head><title>Test ESEF</title></head>
  <body>
    <ix:header>
      <ix:resources>
        {contexts_xml}
        {units_xml}
      </ix:resources>
    </ix:header>
    <div>
      {facts_xml}
    </div>
  </body>
</html>
"""


def _fact(name: str, value: str, ctx: str = "C_2024_INSTANT", unit: str = "EUR",
          *, decimals: str = "-6", scale: str = "0", sign: str = "") -> str:
    sign_attr = f' sign="{sign}"' if sign else ""
    return (
        f'<ix:nonFraction name="ifrs-full:{name}" '
        f'contextRef="{ctx}" unitRef="{unit}" '
        f'decimals="{decimals}" scale="{scale}"{sign_attr}>{value}</ix:nonFraction>'
    )


def test_parse_basic_balance_sheet():
    facts = (
        _fact("Assets", "1000000")
        + _fact("CurrentAssets", "400000")
        + _fact("NoncurrentAssets", "600000")
        + _fact("CashAndCashEquivalents", "75000")
        + _fact("Inventories", "120000")
        + _fact("Liabilities", "600000")
        + _fact("CurrentLiabilities", "200000")
        + _fact("NoncurrentLiabilities", "400000")
        + _fact("Equity", "400000")
        + _fact("IssuedCapital", "100000")
        + _fact("RetainedEarnings", "250000")
        + _fact("Revenue", "2000000", ctx="C_2024")
        + _fact("GrossProfit", "800000", ctx="C_2024")
        + _fact("ProfitLossFromOperatingActivities", "350000", ctx="C_2024")
        + _fact("ProfitLoss", "250000", ctx="C_2024")
    )
    out = parse_esef(_doc(facts))

    assert out["currency"] == "EUR"
    assert out["period_end"] == "2024-12-31"
    assert out["consolidated"] is True

    bs = out["balance_sheet"]
    assert bs["total_assets"] == 1_000_000.0
    assert bs["current_assets"] == 400_000.0
    assert bs["non_current_assets"] == 600_000.0
    assert bs["cash_and_equivalents"] == 75_000.0
    assert bs["inventories"] == 120_000.0
    assert bs["total_liabilities"] == 600_000.0
    assert bs["current_liabilities"] == 200_000.0
    assert bs["non_current_liabilities"] == 400_000.0
    assert bs["total_equity"] == 400_000.0
    assert bs["share_capital"] == 100_000.0
    assert bs["retained_earnings"] == 250_000.0

    is_ = out["income_statement"]
    assert is_["revenue"] == 2_000_000.0
    assert is_["gross_profit"] == 800_000.0
    assert is_["operating_profit"] == 350_000.0
    assert is_["net_income"] == 250_000.0


def test_scale_attribute_multiplies_value():
    # scale=3 means reported in thousands; raw 1500 -> 1,500,000
    facts = _fact("Assets", "1500", scale="3") + _fact("Revenue", "2", scale="6", ctx="C_2024")
    out = parse_esef(_doc(facts))
    assert out["balance_sheet"]["total_assets"] == 1_500_000.0
    assert out["income_statement"]["revenue"] == 2_000_000.0


def test_negative_sign_attribute_inverts_value():
    facts = _fact("ProfitLoss", "50000", ctx="C_2024", sign="-")
    out = parse_esef(_doc(facts))
    assert out["income_statement"]["net_income"] == -50_000.0


def test_parenthesised_negative_number():
    facts = _fact("ProfitLoss", "(123456)", ctx="C_2024")
    out = parse_esef(_doc(facts))
    assert out["income_statement"]["net_income"] == -123_456.0


def test_european_decimal_comma():
    facts = _fact("Assets", "1.234.567,89")
    out = parse_esef(_doc(facts))
    assert out["balance_sheet"]["total_assets"] == pytest.approx(1_234_567.89)


def test_picks_latest_period_when_multiple_present():
    contexts = """
        <xbrli:context id="C_2023">
          <xbrli:entity><xbrli:identifier scheme="x">A</xbrli:identifier></xbrli:entity>
          <xbrli:period><xbrli:instant>2023-12-31</xbrli:instant></xbrli:period>
        </xbrli:context>
        <xbrli:context id="C_2024">
          <xbrli:entity><xbrli:identifier scheme="x">A</xbrli:identifier></xbrli:entity>
          <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
        </xbrli:context>
    """
    facts = (
        _fact("Assets", "111", ctx="C_2023")
        + _fact("Equity", "55", ctx="C_2023")
        + _fact("Assets", "222", ctx="C_2024")
        + _fact("Equity", "100", ctx="C_2024")
    )
    out = parse_esef(_doc(facts, contexts_xml=contexts))
    assert out["period_end"] == "2024-12-31"
    assert out["balance_sheet"]["total_assets"] == 222.0
    assert out["balance_sheet"]["total_equity"] == 100.0


def test_detects_parent_only_context():
    contexts = """
        <xbrli:context id="C_PARENT">
          <xbrli:entity><xbrli:identifier scheme="x">A</xbrli:identifier>
            <xbrli:segment>
              <xbrldi:explicitMember xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
                                     dimension="ifrs-full:ConsolidatedAndSeparateFinancialStatementsAxis">
                ifrs-full:SeparateMember
              </xbrldi:explicitMember>
            </xbrli:segment>
          </xbrli:entity>
          <xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period>
        </xbrli:context>
    """
    facts = _fact("Assets", "100", ctx="C_PARENT")
    out = parse_esef(_doc(facts, contexts_xml=contexts))
    assert out["consolidated"] is False


def test_free_cash_flow_computed_from_cfo_cfi():
    facts = (
        _fact("CashFlowsFromUsedInOperatingActivities", "800", ctx="C_2024")
        + _fact("CashFlowsFromUsedInInvestingActivities", "300", ctx="C_2024", sign="-")
        + _fact("CashFlowsFromUsedInFinancingActivities", "100", ctx="C_2024", sign="-")
    )
    out = parse_esef(_doc(facts))
    cf = out["cash_flow"]
    assert cf["operating_cf"] == 800.0
    assert cf["investing_cf"] == -300.0
    assert cf["financing_cf"] == -100.0
    assert cf["free_cash_flow"] == 500.0


def test_raw_concepts_populated_for_debugging():
    facts = _fact("Assets", "999") + _fact("Equity", "111")
    out = parse_esef(_doc(facts))
    raw = out["raw_concepts"]
    assert any("Assets" in k for k in raw)
    assert any("Equity" in k for k in raw)


def test_malformed_xml_raises_parse_error():
    with pytest.raises(XBRLParseError):
        parse_esef("<not-valid <<")


def test_document_without_ix_facts_raises():
    empty = """<?xml version="1.0"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance">
  <body><p>Annual report (narrative only).</p></body>
</html>"""
    with pytest.raises(XBRLParseError):
        parse_esef(empty)


def test_zip_package_is_unpacked():
    facts = _fact("Assets", "777") + _fact("Equity", "200")
    xhtml = _doc(facts)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("META-INF/manifest.xml", "<x/>")
        zf.writestr("reports/report.xhtml", xhtml)
    out = parse_esef(buf.getvalue(), filename="package.zip")
    assert out["balance_sheet"]["total_assets"] == 777.0
    assert out["balance_sheet"]["total_equity"] == 200.0


def test_zip_magic_detected_without_filename_hint():
    facts = _fact("Assets", "42")
    xhtml = _doc(facts)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("reports/main.xhtml", xhtml)
    out = parse_esef(buf.getvalue())  # no filename
    assert out["balance_sheet"]["total_assets"] == 42.0


def test_currency_picked_from_units():
    units = """
        <xbrli:unit id="USD"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
    """
    facts = _fact("Assets", "1000", unit="USD") + _fact("Revenue", "2000", ctx="C_2024", unit="USD")
    out = parse_esef(_doc(facts, units_xml=units))
    assert out["currency"] == "USD"


def test_non_ifrs_concept_is_ignored():
    facts = (
        _fact("Assets", "500")
        + '<ix:nonFraction name="custom:MyMetric" contextRef="C_2024_INSTANT" '
          'unitRef="EUR" decimals="0" scale="0">99999</ix:nonFraction>'
    )
    out = parse_esef(_doc(facts))
    assert out["balance_sheet"]["total_assets"] == 500.0
    # The custom metric should not leak in as a known line item.
    assert all(v != 99999 for v in out["balance_sheet"].values() if v is not None)
