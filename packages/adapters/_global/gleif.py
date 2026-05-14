"""GLEIF (Global Legal Entity Identifier) client.

Free, no auth, JSON:API spec. https://api.gleif.org/api/v1
"""
from __future__ import annotations

from typing import Any

from packages.adapters._base.http import build_http_client, get_with_retry


class GLEIFClient:
    BASE_URL = "https://api.gleif.org/api/v1"

    async def search(self, query: str, page_size: int = 10) -> list[dict[str, Any]]:
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(
                client,
                "/lei-records",
                params={
                    "filter[entity.legalName]": query,
                    "page[size]": page_size,
                },
            )
            resp.raise_for_status()
            return resp.json().get("data", [])

    async def get_by_lei(self, lei: str) -> dict[str, Any] | None:
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(client, f"/lei-records/{lei}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json().get("data")

    async def fuzzy(self, name: str, country: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {
            "field": "entity.legalName",
            "q": name,
            "page[size]": 10,
        }
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(client, "/fuzzycompletions", params=params)
            resp.raise_for_status()
            results = resp.json().get("data", [])
            if country:
                # Fuzzy doesn't filter by country directly; filter post-hoc on the
                # records when needed.
                pass
            return results
