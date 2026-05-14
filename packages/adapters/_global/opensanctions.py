"""OpenSanctions API client for sanctions / PEP screening.

Free non-commercial API at https://api.opensanctions.org. For production
commercial use a license is required, but the free tier is fine for risk
flagging during dev/MVP.
"""
from __future__ import annotations

import os
from typing import Any

from packages.adapters._base.http import build_http_client, get_with_retry


class OpenSanctionsClient:
    BASE_URL = "https://api.opensanctions.org"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.getenv("OPENSANCTIONS_API_KEY")

    def _headers(self) -> dict[str, str]:
        if self.api_key:
            return {"Authorization": f"ApiKey {self.api_key}"}
        return {}

    async def screen(self, name: str, country: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"q": name, "limit": 5}
        if country:
            params["countries"] = country.lower()
        async with build_http_client(base_url=self.BASE_URL, headers=self._headers()) as client:
            resp = await get_with_retry(client, "/search/default", params=params)
            if resp.status_code >= 400:
                return []
            return resp.json().get("results", [])
