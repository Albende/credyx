"""Latvia — Uznemumu Registrs (UR) open data.

Source: https://data.gov.lv/dati/eng/dataset/uz - the Latvian Enterprise
Register publishes a daily CSV dump of all registered legal entities.

We expect a CSV at `LV_UR_DATA_PATH` with the dataset's canonical columns:
    regcode, name, name_before_quotes, sepa, regtype, regtype_text,
    type, type_text, registered, terminated, address, index, addressid,
    region, region_text, city, city_text, atvk
"""
from __future__ import annotations

import csv
import io
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator

from packages.ingestion.sources._base import IngestedCompanyDTO, IngestionSource

logger = logging.getLogger(__name__)

ENV_DATA_PATH = "LV_UR_DATA_PATH"
CHUNK_SIZE = 64 * 1024


class LVUrSource(IngestionSource):
    country_code = "LV"
    name = "lv_ur"
    schedule = "daily"

    def __init__(self, data_path: str | os.PathLike[str] | None = None) -> None:
        self._explicit_path = Path(data_path) if data_path is not None else None

    def _resolve_path(self) -> Path:
        candidate = self._explicit_path or Path(os.environ.get(ENV_DATA_PATH, ""))
        if not candidate or str(candidate) == ".":
            raise FileNotFoundError(
                f"{ENV_DATA_PATH} is not set. Download the UR open dataset from "
                f"https://data.gov.lv/dati/eng/dataset/uz and point {ENV_DATA_PATH} "
                "at the CSV file."
            )
        if not candidate.exists():
            raise FileNotFoundError(f"LV UR CSV not found at {candidate}")
        return candidate

    async def download(self, *, since: datetime | None = None) -> AsyncIterator[bytes]:
        path = self._resolve_path()
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(CHUNK_SIZE)
                if not chunk:
                    return
                yield chunk

    async def parse(
        self, chunks: AsyncIterator[bytes]
    ) -> AsyncIterator[IngestedCompanyDTO]:
        buffer = ""
        header_seen = False
        async for chunk in chunks:
            buffer += chunk.decode("utf-8", errors="replace")
            last_nl = buffer.rfind("\n")
            if last_nl == -1:
                continue
            block, buffer = buffer[: last_nl + 1], buffer[last_nl + 1 :]
            for dto in self._parse_block(block, header_seen):
                header_seen = True
                yield dto
            header_seen = True  # subsequent blocks have no header
        if buffer.strip():
            for dto in self._parse_block(buffer, header_seen):
                yield dto

    def _parse_block(self, block: str, header_seen: bool) -> list[IngestedCompanyDTO]:
        out: list[IngestedCompanyDTO] = []
        if header_seen:
            reader = csv.DictReader(
                io.StringIO(block),
                fieldnames=[
                    "regcode", "name", "name_before_quotes", "sepa",
                    "regtype", "regtype_text", "type", "type_text",
                    "registered", "terminated", "address", "index",
                    "addressid", "region", "region_text", "city",
                    "city_text", "atvk",
                ],
            )
        else:
            reader = csv.DictReader(io.StringIO(block))
        for row in reader:
            regcode = (row.get("regcode") or "").strip()
            name = (row.get("name") or row.get("name_before_quotes") or "").strip()
            if not regcode or not name:
                continue
            terminated = (row.get("terminated") or "").strip()
            status = "terminated" if terminated else "active"
            out.append(
                IngestedCompanyDTO(
                    country="LV",
                    source_id=regcode,
                    name=name,
                    status=status,
                    address=(row.get("address") or None),
                    identifiers=[{"type": "OTHER", "value": regcode, "label": "REGCODE"}],
                    raw={k: v for k, v in row.items() if v},
                )
            )
        return out
