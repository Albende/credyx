from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.qa import QAAdapter
from packages.shared.models import AdapterStatus, FilingType, IdentifierType


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    adapter = QAAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Qatar National Bank")


@pytest.mark.asyncio
async def test_lookup_cr_raises_not_implemented():
    adapter = QAAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "12345"
        )


@pytest.mark.asyncio
async def test_lookup_cr_rejects_non_numeric():
    adapter = QAAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "ABC"
        )


@pytest.mark.asyncio
async def test_lookup_tin_raises_not_implemented():
    adapter = QAAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(
            IdentifierType.VAT, "12345678"
        )


@pytest.mark.asyncio
async def test_lookup_tin_strips_qa_prefix():
    adapter = QAAdapter()
    # The QA prefix is stripped before format validation; passing a
    # well-formed numeric body should still resolve to "not implemented"
    # (because the underlying source is reCAPTCHA-gated) rather than
    # InvalidIdentifierError.
    with pytest.raises(AdapterNotImplementedError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "QA12345678")


@pytest.mark.asyncio
async def test_lookup_tin_rejects_short():
    adapter = QAAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "123")


@pytest.mark.asyncio
async def test_lookup_unsupported_identifier():
    adapter = QAAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "529900T8BM49AURSDO55")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ticker",
    ["QNBK", "IQCD", "ORDS", "QATI"],
)
async def test_fetch_financials_known_tickers(ticker: str):
    adapter = QAAdapter()
    filings = await adapter.fetch_financials(ticker, years=3)
    assert filings, f"expected filings for {ticker}"
    assert all(f.type == FilingType.ANNUAL_REPORT for f in filings)
    assert all(f.currency == "QAR" for f in filings)
    assert all(ticker in (f.document_url or "") for f in filings)


@pytest.mark.asyncio
async def test_fetch_financials_accepts_qse_prefix():
    adapter = QAAdapter()
    filings = await adapter.fetch_financials("QSE:QNBK", years=2)
    assert filings
    assert all("QNBK" in (f.document_url or "") for f in filings)


@pytest.mark.asyncio
async def test_fetch_financials_cr_returns_empty():
    adapter = QAAdapter()
    filings = await adapter.fetch_financials("123456")
    assert filings == []


@pytest.mark.asyncio
async def test_fetch_financials_rejects_junk():
    adapter = QAAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("!!!not-a-cr!!!")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_probes_qse():
    adapter = QAAdapter()
    health = await adapter.health_check()
    assert health.country_code == "QA"
    assert health.status in {
        AdapterStatus.OK,
        AdapterStatus.DEGRADED,
        AdapterStatus.ERROR,
    }
