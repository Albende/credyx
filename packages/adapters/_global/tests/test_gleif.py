"""Tests for the GLEIF client.

The unit test mocks the GLEIF JSON:API payload to assert the mapping into
CompanyMatch / CompanyDetails. The integration test hits the real GLEIF
API and is gated by `@pytest.mark.integration`.
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from packages.adapters._global.gleif import GLEIFClient
from packages.shared.models import IdentifierType


_NOKIA_SEARCH_PAYLOAD: dict[str, Any] = {
    "meta": {"pagination": {"total": 1}},
    "data": [
        {
            "type": "lei-records",
            "id": "549300A0JPRWG1KI7U06",
            "attributes": {
                "lei": "549300A0JPRWG1KI7U06",
                "entity": {
                    "legalName": {"name": "NOKIA OYJ", "language": "fi"},
                    "legalAddress": {
                        "language": "fi",
                        "addressLines": ["Karakaari 7"],
                        "city": "Espoo",
                        "region": "FI-18",
                        "country": "FI",
                        "postalCode": "02610",
                    },
                    "headquartersAddress": {
                        "addressLines": ["Karakaari 7"],
                        "city": "Espoo",
                        "country": "FI",
                        "postalCode": "02610",
                    },
                    "legalForm": {"id": "JHF1"},
                    "status": "ACTIVE",
                    "registeredAt": {"id": "RA000189"},
                    "registeredAs": "0112038-9",
                },
                "registration": {"status": "ISSUED"},
            },
        }
    ],
}


_NOKIA_LEI_PAYLOAD: dict[str, Any] = {
    "data": _NOKIA_SEARCH_PAYLOAD["data"][0],
}


@pytest.mark.asyncio
async def test_search_by_name_maps_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=_NOKIA_SEARCH_PAYLOAD)

    transport = httpx.MockTransport(handler)

    from packages.adapters._base import http as http_module

    def fake_build(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("base_url", None)
        kwargs.pop("auth", None)
        kwargs.pop("follow_redirects", None)
        kwargs.pop("timeout", None)
        headers = kwargs.pop("headers", None) or {}
        return httpx.AsyncClient(
            base_url=GLEIFClient.BASE_URL,
            transport=transport,
            headers=headers,
        )

    monkeypatch.setattr(http_module, "build_http_client", fake_build)
    # Also patch the symbol imported into gleif module.
    from packages.adapters._global import gleif as gleif_module

    monkeypatch.setattr(gleif_module, "build_http_client", fake_build)

    matches = await GLEIFClient().search_by_name(name="Nokia", country="FI", limit=5)

    assert captured["params"]["filter[entity.legalName]"] == "Nokia"
    assert captured["params"]["filter[entity.legalAddress.country]"] == "FI"
    assert captured["params"]["page[size]"] == "5"

    assert len(matches) == 1
    m = matches[0]
    assert m.id == "549300A0JPRWG1KI7U06"
    assert m.name == "NOKIA OYJ"
    assert m.country == "FI"
    assert m.status == "active"
    assert m.source_url == "https://search.gleif.org/#/record/549300A0JPRWG1KI7U06"
    assert any(i.type == IdentifierType.LEI for i in m.identifiers)
    assert "Espoo" in (m.address or "")


@pytest.mark.asyncio
async def test_lookup_by_lei_maps_details(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/lei-records/549300A0JPRWG1KI7U06")
        return httpx.Response(200, json=_NOKIA_LEI_PAYLOAD)

    transport = httpx.MockTransport(handler)

    from packages.adapters._global import gleif as gleif_module

    def fake_build(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("base_url", None)
        kwargs.pop("auth", None)
        kwargs.pop("follow_redirects", None)
        kwargs.pop("timeout", None)
        headers = kwargs.pop("headers", None) or {}
        return httpx.AsyncClient(
            base_url=GLEIFClient.BASE_URL,
            transport=transport,
            headers=headers,
        )

    monkeypatch.setattr(gleif_module, "build_http_client", fake_build)

    details = await GLEIFClient().lookup_by_lei("549300A0JPRWG1KI7U06")
    assert details is not None
    assert details.id == "549300A0JPRWG1KI7U06"
    assert details.name == "NOKIA OYJ"
    assert details.country == "FI"
    assert details.status == "active"
    assert details.legal_form == "JHF1"
    assert any(i.type == IdentifierType.LEI for i in details.identifiers)


@pytest.mark.asyncio
async def test_lookup_by_lei_returns_none_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"errors": [{"status": "404"}]})

    transport = httpx.MockTransport(handler)

    from packages.adapters._global import gleif as gleif_module

    def fake_build(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("base_url", None)
        kwargs.pop("auth", None)
        kwargs.pop("follow_redirects", None)
        kwargs.pop("timeout", None)
        headers = kwargs.pop("headers", None) or {}
        return httpx.AsyncClient(
            base_url=GLEIFClient.BASE_URL,
            transport=transport,
            headers=headers,
        )

    monkeypatch.setattr(gleif_module, "build_http_client", fake_build)

    details = await GLEIFClient().lookup_by_lei("000000000000000000NO")
    assert details is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_live_search_nokia_returns_finnish_lei() -> None:
    """Hits the real GLEIF API. Slow."""
    matches = await GLEIFClient().search_by_name(name="Nokia", country="FI", limit=10)
    assert matches, "expected at least one Nokia match in GLEIF"
    fi_match = next((m for m in matches if m.country == "FI"), None)
    assert fi_match is not None, "expected a Finnish Nokia entity"
    lei_ids = [i for i in fi_match.identifiers if i.type == IdentifierType.LEI]
    assert lei_ids, "expected an LEI identifier on the Finnish Nokia match"
    assert len(lei_ids[0].value) == 20  # LEI codes are always 20 chars
