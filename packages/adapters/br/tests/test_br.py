"""Integration tests for the BR adapter (BrasilAPI).

These hit real BrasilAPI endpoints and depend on the Receita Federal data
mirror staying online. Marked `integration` so CI can skip with
`-m "not integration"`.
"""
from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.br import BRAdapter
from packages.shared.models import IdentifierType


@pytest.mark.asyncio
async def test_search_by_name_raises_not_implemented():
    adapter = BRAdapter()
    with pytest.raises(AdapterNotImplementedError):
        await adapter.search_by_name("Petrobras")


@pytest.mark.asyncio
async def test_invalid_cnpj_rejected():
    adapter = BRAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "12345678901234")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_petrobras_cnpj():
    adapter = BRAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "33.000.167/0001-01"
    )
    assert details is not None
    assert "petrobras" in details.name.lower() or "petroleo" in details.name.lower()
    assert any(i.type == IdentifierType.VAT for i in details.identifiers)
    assert details.country == "BR"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_vale_cnpj():
    adapter = BRAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.VAT, "33592510000154"
    )
    assert details is not None
    assert "vale" in details.name.lower()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_via_company_number_alias():
    adapter = BRAdapter()
    details = await adapter.lookup_by_identifier(
        IdentifierType.COMPANY_NUMBER, "07526557000100"
    )
    assert details is not None
    assert "ambev" in details.name.lower()
