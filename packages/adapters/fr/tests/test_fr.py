from __future__ import annotations

import pytest

from packages.adapters.fr import FRAdapter
from packages.shared.models import IdentifierType


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_finds_total():
    adapter = FRAdapter()
    matches = await adapter.search_by_name("TotalEnergies", limit=5)
    assert any("total" in m.name.lower() for m in matches)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_total_siren():
    adapter = FRAdapter()
    details = await adapter.lookup_by_identifier(IdentifierType.SIREN, "542051180")
    assert details is not None
    assert "total" in details.name.lower()
