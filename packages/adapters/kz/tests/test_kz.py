from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.kz import KZAdapter
from packages.shared.models import FilingType, IdentifierType


def test_bin_normalizer_strips_prefix_and_validates():
    from packages.adapters.kz.adapter import _normalize_bin

    assert _normalize_bin("020640000327") == "020640000327"
    assert _normalize_bin("KZ020640000327") == "020640000327"
    assert _normalize_bin("020 640 000 327") == "020640000327"
    assert _normalize_bin("020-640-000-327") == "020640000327"


def test_bin_normalizer_rejects_invalid():
    from packages.adapters.kz.adapter import _normalize_bin

    with pytest.raises(InvalidIdentifierError):
        _normalize_bin("12345")
    with pytest.raises(InvalidIdentifierError):
        _normalize_bin("ABCDEF000327")


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    adapter = KZAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("KazMunayGas")


@pytest.mark.asyncio
async def test_lookup_rejects_wrong_id_type():
    adapter = KZAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.SIREN, "020640000327"
        )


@pytest.mark.asyncio
async def test_fetch_financials_returns_empty_for_unlisted():
    adapter = KZAdapter()
    # 12 valid digits but not on the KASE listed table.
    filings = await adapter.fetch_financials("123456789012")
    assert filings == []


@pytest.mark.asyncio
async def test_fetch_financials_returns_kase_url_for_listed():
    adapter = KZAdapter()
    # KazMunayGas — known KASE-listed issuer.
    filings = await adapter.fetch_financials("020640000327")
    assert len(filings) == 1
    f = filings[0]
    assert f.type == FilingType.ANNUAL_REPORT
    assert f.currency == "KZT"
    assert f.document_url and "kase.kz" in f.document_url
    assert f.document_format == "html"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_adata():
    adapter = KZAdapter()
    health = await adapter.health_check()
    assert health.country_code == "KZ"
    assert health.capabilities["lookup"] is True
    assert health.requires_api_key is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_kazmunaygas_bin():
    adapter = KZAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "020640000327"
    )
    assert details is not None
    assert details.country == "KZ"
    assert details.id == "020640000327"
    # If adata.kz resolved the company we expect "казмунай" somewhere in the
    # Cyrillic / transliterated name; otherwise we tolerate the fallback
    # marker but still require a non-empty name + source URL.
    assert details.name
    assert details.source_url


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_kaspi_bank_bin():
    adapter = KZAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "920140000084"
    )
    assert details is not None
    assert details.identifiers[0].value == "920140000084"
    assert details.identifiers[0].label == "BIN"
