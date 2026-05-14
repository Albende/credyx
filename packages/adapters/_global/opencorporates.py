"""OpenCorporates API client.

Free tier: 500 req/month, requires API token (env OPENCORPORATES_API_KEY).
https://api.opencorporates.com/documentation/API-Reference
"""
from __future__ import annotations

import os
from typing import Any

from packages.adapters._base.http import build_http_client, get_with_retry


class OpenCorporatesClient:
    BASE_URL = "https://api.opencorporates.com/v0.4"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("OPENCORPORATES_API_KEY")

    def _params(self, **extra: Any) -> dict[str, Any]:
        params: dict[str, Any] = dict(extra)
        if self.api_key:
            params["api_token"] = self.api_key
        return params

    async def search_companies(
        self,
        query: str,
        *,
        jurisdiction: str | None = None,
        per_page: int = 10,
    ) -> list[dict[str, Any]]:
        params = self._params(q=query, per_page=per_page)
        if jurisdiction:
            params["jurisdiction_code"] = jurisdiction.lower()
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(client, "/companies/search", params=params)
            if resp.status_code == 401:
                return []
            resp.raise_for_status()
            data = resp.json()
            return [item["company"] for item in data.get("results", {}).get("companies", [])]

    async def get_company(
        self, jurisdiction: str, company_number: str
    ) -> dict[str, Any] | None:
        params = self._params()
        async with build_http_client(base_url=self.BASE_URL) as client:
            resp = await get_with_retry(
                client,
                f"/companies/{jurisdiction.lower()}/{company_number}",
                params=params,
            )
            if resp.status_code == 404:
                return None
            if resp.status_code == 401:
                return None
            resp.raise_for_status()
            return resp.json().get("results", {}).get("company")
