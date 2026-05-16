"""Israel — open.gov.il CKAN companies dataset.

Source: https://data.gov.il/dataset/ica_companies — the Israeli Corporations
Authority publishes the registered-companies dataset via the CKAN datastore
API. Unlike the BE/UA/LV dumps which are huge offline files, CKAN exposes a
paginated JSON endpoint we can stream live; we still cache the resulting
records into Postgres so adapter searches stay fast.

The resource id is fixed (it changes very rarely — when it does, set
`IL_CKAN_RESOURCE_ID`).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, AsyncIterator

import httpx

from packages.adapters._base.http import build_http_client
from packages.ingestion.sources._base import IngestedCompanyDTO, IngestionSource

logger = logging.getLogger(__name__)

DEFAULT_RESOURCE_ID = "f004176c-b85f-4542-8901-7b3176f9a054"
ENV_RESOURCE = "IL_CKAN_RESOURCE_ID"
CKAN_BASE = "https://data.gov.il/api/3/action/datastore_search"
PAGE_SIZE = 1000


class ILCkanSource(IngestionSource):
    country_code = "IL"
    name = "il_ckan"
    schedule = "daily"

    def __init__(
        self,
        *,
        resource_id: str | None = None,
        client: httpx.AsyncClient | None = None,
        page_size: int = PAGE_SIZE,
    ) -> None:
        self._resource_id = (
            resource_id or os.environ.get(ENV_RESOURCE) or DEFAULT_RESOURCE_ID
        )
        self._client = client
        self._page_size = page_size

    async def download(self, *, since: datetime | None = None) -> AsyncIterator[bytes]:
        """Stream raw CKAN page JSON one page at a time as bytes."""
        owns_client = self._client is None
        client = self._client or build_http_client(timeout=60.0)
        try:
            offset = 0
            while True:
                params = {
                    "resource_id": self._resource_id,
                    "limit": self._page_size,
                    "offset": offset,
                }
                resp = await client.get(CKAN_BASE, params=params)
                if resp.status_code == 429:
                    raise RuntimeError("IL CKAN rate-limited; back off and retry later")
                resp.raise_for_status()
                yield resp.content
                payload = resp.json()
                records = payload.get("result", {}).get("records", [])
                if len(records) < self._page_size:
                    return
                offset += self._page_size
        finally:
            if owns_client:
                await client.aclose()

    async def parse(
        self, chunks: AsyncIterator[bytes]
    ) -> AsyncIterator[IngestedCompanyDTO]:
        async for chunk in chunks:
            try:
                payload = json.loads(chunk)
            except json.JSONDecodeError as exc:
                logger.warning("IL CKAN bad page JSON: %s", exc)
                continue
            for record in payload.get("result", {}).get("records", []):
                dto = self._to_dto(record)
                if dto is not None:
                    yield dto

    @staticmethod
    def _to_dto(record: dict[str, Any]) -> IngestedCompanyDTO | None:
        # The dataset uses Hebrew column names in some snapshots and English
        # in others; accept both. The company number is always `מספר חברה` /
        # `Company Number`.
        cid = (
            str(record.get("מספר חברה")
                or record.get("Company Number")
                or record.get("company_number")
                or "").strip()
        )
        name = (
            record.get("שם חברה")
            or record.get("Company Name")
            or record.get("company_name")
            or ""
        ).strip()
        if not cid or not name:
            return None
        status = (
            record.get("סטטוס חברה")
            or record.get("Status")
            or record.get("status")
        )
        address_parts = [
            record.get("שם רחוב") or record.get("Street"),
            record.get("מספר בית") or record.get("House Number"),
            record.get("שם עיר") or record.get("City"),
        ]
        address = " ".join(p for p in address_parts if p) or None
        return IngestedCompanyDTO(
            country="IL",
            source_id=cid,
            name=name,
            status=str(status) if status else None,
            address=address,
            identifiers=[{"type": "OTHER", "value": cid, "label": "IL_COMPANY_NUMBER"}],
            raw=record,
        )
