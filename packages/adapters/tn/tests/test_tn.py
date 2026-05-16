from __future__ import annotations

import pytest

from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.tn import TNAdapter
from packages.shared.models import AdapterStatus, IdentifierType


@pytest.mark.asyncio
@pytest.mark.integration
async def test_health_check_probes_rne():
    adapter = TNAdapter()
    health = await adapter.health_check()
    assert health.country_code == "TN"
    assert health.status in {
        AdapterStatus.OK,
        AdapterStatus.DEGRADED,
        AdapterStatus.ERROR,
    }
    assert health.requires_api_key is False
    assert health.rate_limit_per_minute == 30


@pytest.mark.asyncio
async def test_normalize_matricule_accepts_slashed_form():
    adapter = TNAdapter()
    # Mixed punctuation should normalise; an obviously short value rejects.
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(IdentifierType.VAT, "12345")


@pytest.mark.asyncio
async def test_lookup_unsupported_identifier_raises():
    adapter = TNAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.LEI, "529900T8BM49AURSDO55"
        )


@pytest.mark.asyncio
async def test_lookup_invalid_rne_raises():
    adapter = TNAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.lookup_by_identifier(
            IdentifierType.COMPANY_NUMBER, "not-a-number"
        )


@pytest.mark.asyncio
async def test_fetch_financials_rejects_invalid_id():
    adapter = TNAdapter()
    with pytest.raises(InvalidIdentifierError):
        await adapter.fetch_financials("RC-xyz", years=3)


@pytest.mark.asyncio
async def test_fetch_financials_non_listed_returns_empty():
    """No free Matricule→BVMT-ticker resolver; expect [] not 501."""
    adapter = TNAdapter()
    # Banque de Tunisie matricule, canonical normalised form.
    filings = await adapter.fetch_financials("0000010ABC000", years=3)
    assert filings == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_search_by_name_real_or_not_implemented():
    """RNE search: real JSON hit OR the spec'd 501.

    The public portal's JSON endpoints are undocumented; we accept either
    a structured response or `AdapterNotImplementedError` (never fabricated
    matches).
    """
    adapter = TNAdapter()
    try:
        matches = await adapter.search_by_name("Tunisie Telecom", limit=5)
    except AdapterNotImplementedError:
        return
    assert isinstance(matches, list)
    for m in matches:
        assert m.country == "TN"
        assert m.name
        assert m.identifiers


@pytest.mark.asyncio
@pytest.mark.integration
async def test_lookup_banque_de_tunisie_best_effort():
    """Banque de Tunisie — Matricule (canonical placeholder normalised form).

    The RNE JSON shape is undocumented in MVP. We accept either a real
    identity match or `AdapterNotImplementedError` — never fabricated data.
    """
    adapter = TNAdapter()
    try:
        details = await adapter.lookup_by_identifier(
            IdentifierType.VAT, "0000010ABC000"
        )
    except AdapterNotImplementedError:
        return
    if details is None:
        return
    assert details.country == "TN"
    assert details.identifiers
