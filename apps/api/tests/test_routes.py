"""Core route smoke tests — /api/countries, /api/search, /api/companies, /api/jobs."""
from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, patch

import pytest

from packages.shared.models import (
    CompanyDetails,
    CompanyMatch,
    IdentifierType,
    RegistryIdentifier,
)


async def test_list_countries_returns_at_least_100(client):
    r = await client.get("/api/countries")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "countries" in body
    assert isinstance(body["countries"], list)
    assert len(body["countries"]) >= 100, f"only {len(body['countries'])} countries"


async def test_search_falls_back_to_gleif_for_stub_country(client, make_user, auth_headers):
    """A country with only a stub adapter raises NotImplemented; the route
    then falls back to GLEIF. We stub GLEIF to return a deterministic result.
    """
    user = await make_user("searcher@example.com")
    fake_match = CompanyMatch(
        id="LEI123",
        name="Stub Corp BG",
        country="BG",
        identifiers=[RegistryIdentifier(type=IdentifierType.LEI, value="LEI123")],
    )
    with patch(
        "apps.api.app.routes.GLEIFClient.search_by_name",
        new=AsyncMock(return_value=[fake_match]),
    ):
        r = await client.get(
            "/api/search",
            params={"country": "BG", "name": "Stub Corp"},
            headers=auth_headers(user),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body["results"], list)
    assert body["source"] == "gleif"
    assert body["results"][0]["name"] == "Stub Corp BG"


async def test_get_company_cache_miss_then_hit(client, make_user, auth_headers):
    """First call hits the adapter (stubbed via LEI path → GLEIF lookup);
    second call should be served from the DB cache.
    """
    user = await make_user("companies@example.com")
    h = auth_headers(user)

    details = CompanyDetails(
        id="529900T8BM49AURSDO55",
        name="Cache Demo Ltd",
        country="GB",
        legal_form="Limited",
        identifiers=[
            RegistryIdentifier(type=IdentifierType.LEI, value="529900T8BM49AURSDO55"),
        ],
    )
    with patch(
        "apps.api.app.routes.GLEIFClient.lookup_by_lei",
        new=AsyncMock(return_value=details),
    ) as mocked:
        r1 = await client.get(
            "/api/companies/GB/529900T8BM49AURSDO55", headers=h
        )
        assert r1.status_code == 200, r1.text
        b1 = r1.json()
        assert b1["cached"] is False
        assert b1["details"]["name"] == "Cache Demo Ltd"

        r2 = await client.get(
            "/api/companies/GB/529900T8BM49AURSDO55", headers=h
        )
        assert r2.status_code == 200, r2.text
        b2 = r2.json()
        assert b2["cached"] is True
        # GLEIF must be hit only once because the second call returns the cache.
        assert mocked.call_count == 1


async def test_risk_analysis_kickoff_then_job_lookup(client, make_user, auth_headers):
    """POST /risk-analysis returns a queued job_id, GET /jobs/{id} resolves
    the job row even if the inline background task has not finished.
    """
    user = await make_user("riskuser@example.com", plan_slug="pro")
    h = auth_headers(user)

    details = CompanyDetails(
        id="529900T8BM49AURSDO66",
        name="Risk Demo Ltd",
        country="GB",
        identifiers=[
            RegistryIdentifier(type=IdentifierType.LEI, value="529900T8BM49AURSDO66"),
        ],
    )
    # Pre-populate the company cache so the risk route doesn't need a real
    # adapter lookup. The /companies route stores via upsert_company.
    with patch(
        "apps.api.app.routes.GLEIFClient.lookup_by_lei",
        new=AsyncMock(return_value=details),
    ):
        prime = await client.get(
            "/api/companies/GB/529900T8BM49AURSDO66", headers=h
        )
        assert prime.status_code == 200, prime.text

    # Stub the risk engine so the background task never actually fires the LLM.
    fake_engine = AsyncMock()
    fake_engine.analyze = AsyncMock(side_effect=RuntimeError("stubbed-engine"))
    with patch(
        "apps.api.app.routes.get_risk_engine", return_value=fake_engine
    ):
        r = await client.post(
            "/api/companies/GB/529900T8BM49AURSDO66/risk-analysis", headers=h
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "queued"
    job_id = body["job_id"]

    # Poll the job — it should exist and be in queued/running/error.
    rj = await client.get(f"/api/jobs/{job_id}")
    assert rj.status_code == 200, rj.text
    jb = rj.json()
    assert jb["job_id"] == job_id
    assert jb["status"] in {"queued", "running", "error", "done"}
