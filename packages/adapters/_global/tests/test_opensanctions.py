"""Unit + integration tests for the OpenSanctions client."""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from packages.adapters._global.opensanctions import (
    HIGH_CONFIDENCE_THRESHOLD,
    OpenSanctionsClient,
    SanctionHit,
    screen_many,
)


class _StubAsyncClient:
    """Drop-in for httpx.AsyncClient with controllable POST/GET behavior."""

    def __init__(self, *, response: httpx.Response | None = None, exc: Exception | None = None) -> None:
        self._response = response
        self._exc = exc
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __aenter__(self) -> "_StubAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(self, url: str, *, json: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> httpx.Response:
        self.calls.append((url, {"json": json, "params": params}))
        if self._exc:
            raise self._exc
        assert self._response is not None
        return self._response

    async def get(self, url: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        self.calls.append((url, {"params": params}))
        if self._exc:
            raise self._exc
        assert self._response is not None
        return self._response


def _match_response(results: list[dict[str, Any]], status: int = 200) -> httpx.Response:
    body = {"responses": {"q1": {"results": results}}}
    return httpx.Response(status_code=status, json=body, request=httpx.Request("POST", "https://x"))


@pytest.fixture
def patch_client(monkeypatch: pytest.MonkeyPatch):
    holder: dict[str, _StubAsyncClient] = {}

    def _install(stub: _StubAsyncClient) -> _StubAsyncClient:
        holder["stub"] = stub

        def _factory(**_kwargs: Any) -> _StubAsyncClient:
            return stub

        monkeypatch.setattr(
            "packages.adapters._global.opensanctions.build_http_client", _factory
        )
        return stub

    return _install


@pytest.mark.asyncio
async def test_screen_returns_ranked_hits(patch_client) -> None:
    stub = patch_client(
        _StubAsyncClient(
            response=_match_response(
                [
                    {
                        "id": "Q7747",
                        "caption": "Vladimir Putin",
                        "score": 0.97,
                        "schema": "Person",
                        "datasets": ["us_ofac_sdn", "eu_fsf"],
                        "properties": {"name": ["Vladimir Putin"], "country": ["ru"]},
                    },
                    {
                        "id": "Q123",
                        "caption": "Another Person",
                        "score": 0.42,
                        "schema": "Person",
                        "datasets": ["wd_peps"],
                        "properties": {"name": ["Another Person"]},
                    },
                ]
            )
        )
    )
    client = OpenSanctionsClient(api_key=None)
    hits = await client.screen(name="Vladimir Putin", country="RU", schema="Person")

    assert len(hits) == 2
    assert hits[0].score >= hits[1].score
    top = hits[0]
    assert top.id == "Q7747"
    assert top.score >= HIGH_CONFIDENCE_THRESHOLD
    assert "us_ofac_sdn" in top.datasets
    assert top.source_url == "https://www.opensanctions.org/entities/Q7747/"
    assert top.properties["country"] == ["ru"]

    # Request shape: POST /match/default with the right query body.
    url, kwargs = stub.calls[0]
    assert url == "/match/default"
    body = kwargs["json"]
    assert body["queries"]["q1"]["schema"] == "Person"
    assert body["queries"]["q1"]["properties"]["name"] == ["Vladimir Putin"]
    assert body["queries"]["q1"]["properties"]["country"] == ["ru"]


@pytest.mark.asyncio
async def test_screen_empty_name_short_circuits(patch_client) -> None:
    patch_client(_StubAsyncClient(response=_match_response([])))
    client = OpenSanctionsClient()
    assert await client.screen(name="   ") == []


@pytest.mark.asyncio
async def test_screen_handles_network_failure_gracefully(patch_client) -> None:
    patch_client(
        _StubAsyncClient(
            exc=httpx.ConnectError("boom", request=httpx.Request("POST", "https://x"))
        )
    )
    client = OpenSanctionsClient()
    hits = await client.screen(name="ACME Ltd", country="GB")
    assert hits == []


@pytest.mark.asyncio
async def test_screen_handles_rate_limit(patch_client) -> None:
    patch_client(_StubAsyncClient(response=_match_response([], status=429)))
    client = OpenSanctionsClient()
    assert await client.screen(name="ACME Ltd") == []


@pytest.mark.asyncio
async def test_screen_passes_identifiers_as_registration_number(patch_client) -> None:
    stub = patch_client(_StubAsyncClient(response=_match_response([])))
    client = OpenSanctionsClient()
    await client.screen(name="ACME", identifiers=["GB12345678"], schema="Company")
    body = stub.calls[0][1]["json"]
    assert body["queries"]["q1"]["properties"]["registrationNumber"] == ["GB12345678"]


@pytest.mark.asyncio
async def test_api_key_added_to_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, dict[str, str]] = {}

    def _factory(**kwargs: Any) -> _StubAsyncClient:
        captured["headers"] = kwargs.get("headers") or {}
        return _StubAsyncClient(response=_match_response([]))

    monkeypatch.setattr(
        "packages.adapters._global.opensanctions.build_http_client", _factory
    )
    client = OpenSanctionsClient(api_key="secret-key")
    await client.screen(name="ACME")
    assert captured["headers"]["Authorization"] == "ApiKey secret-key"


@pytest.mark.asyncio
async def test_screen_many_runs_concurrently(patch_client) -> None:
    patch_client(
        _StubAsyncClient(
            response=_match_response(
                [
                    {
                        "id": "X",
                        "caption": "X",
                        "score": 0.5,
                        "schema": "Company",
                        "datasets": [],
                        "properties": {},
                    }
                ]
            )
        )
    )
    client = OpenSanctionsClient()
    targets = [
        {"name": "ACME", "schema": "Company"},
        {"name": "Jane Doe", "schema": "Person"},
        {"name": "John Smith", "schema": "Person"},
    ]
    results = await screen_many(client, targets, max_concurrency=2)
    assert len(results) == 3
    for hits in results:
        assert len(hits) == 1
        assert isinstance(hits[0], SanctionHit)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_live_screen_vladimir_putin_returns_high_confidence_hit() -> None:
    """Live test — should always find Vladimir Putin on sanctions lists."""
    client = OpenSanctionsClient()
    hits = await client.screen(name="Vladimir Putin", country="RU", schema="Person")
    if not hits:
        pytest.skip("OpenSanctions returned no results — service may be down or rate-limited")
    top = hits[0]
    assert top.score >= 0.6, f"Expected a strong match for Putin, got {top.score}"
    assert top.datasets, "Expected at least one source dataset"
