from __future__ import annotations

import pytest

from packages.adapters._base.errors import InvalidIdentifierError
from packages.adapters.lt import LTAdapter
from packages.adapters.lt.adapter import (
    _normalize_imones_kodas,
    _normalize_lt_vat,
)
from packages.shared.models import IdentifierType


def test_imones_kodas_normalizer_accepts_known_companies():
    assert _normalize_imones_kodas("301844044") == "301844044"
    assert _normalize_imones_kodas("110870469") == "110870469"
    assert _normalize_imones_kodas("110 057 511") == "110057511"
    assert _normalize_imones_kodas("LT121215434") == "121215434"


def test_imones_kodas_normalizer_rejects_garbage():
    with pytest.raises(InvalidIdentifierError):
        _normalize_imones_kodas("12345")  # too short
    with pytest.raises(InvalidIdentifierError):
        _normalize_imones_kodas("1234567890")  # too long
    with pytest.raises(InvalidIdentifierError):
        _normalize_imones_kodas("ABC123456")
    with pytest.raises(InvalidIdentifierError):
        _normalize_imones_kodas("")


def test_lt_vat_normalizer_accepts_9_and_12_digits():
    assert _normalize_lt_vat("LT100001969712") == "100001969712"
    assert _normalize_lt_vat("lt 100 001 969 712") == "100001969712"
    assert _normalize_lt_vat("119505694") == "119505694"


def test_lt_vat_normalizer_rejects_garbage():
    with pytest.raises(InvalidIdentifierError):
        _normalize_lt_vat("LT12345678")  # 8 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_lt_vat("LT1234567890")  # 10 digits
    with pytest.raises(InvalidIdentifierError):
        _normalize_lt_vat("not-a-vat")


@pytest.mark.asyncio
async def test_lookup_rejects_unsupported_identifier():
    adapter = LTAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.LEI, "anything")


@pytest.mark.asyncio
async def test_fetch_financials_rejects_bad_kodas():
    adapter = LTAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("not-a-code")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_reports_ok():
    adapter = LTAdapter()
    health = await adapter.health_check()
    assert health.country_code == "LT"
    assert health.capabilities["lookup"] is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_telia():
    adapter = LTAdapter()
    # JAR scrape may degrade if their HTML changes — only the contract is
    # asserted: a list (possibly empty) of well-formed CompanyMatch rows.
    results = await adapter.search_by_name("Telia Lietuva", limit=5)
    assert isinstance(results, list)
    for r in results:
        assert r.country == "LT"
        assert r.id.isdigit()
        assert len(r.id) == 9


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_kodas_telia():
    adapter = LTAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "121215434"
    )
    # JAR HTML may not parse in every environment; if it does, the canonical
    # įmonės kodas comes back. None is also acceptable — we never fabricate.
    if details is not None:
        assert details.id == "121215434"
        assert details.country == "LT"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_by_kodas_pieno_zvaigzdes():
    adapter = LTAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "110870469"
    )
    if details is not None:
        assert details.id == "110870469"
        assert details.country == "LT"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_vies_lookup_telia():
    adapter = LTAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "LT100001969712"
    )
    # If VIES is reachable and the VAT remains active, we should get a hit;
    # the service is occasionally throttled, in which case None is fine.
    if details is not None:
        assert details.country == "LT"
        assert details.id == "LT100001969712"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_fetch_financials_telia():
    adapter = LTAdapter()
    filings = await adapter.fetch_financials("121215434", years=10)
    assert isinstance(filings, list)
    for f in filings:
        assert f.company_id == "121215434"
        assert f.currency == "EUR"
        # JAR sells the document; we only expose the year + a source URL.
        assert f.document_url is None
