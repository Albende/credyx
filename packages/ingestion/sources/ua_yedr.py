"""Ukraine — YeDR (Unified State Register) open dataset.

Source: https://data.gov.ua/ — YeDR releases periodic XML dumps of all
registered legal entities under the dataset "Єдиний державний реєстр
юридичних осіб, фізичних осіб-підприємців".

Like BE KBO, the dump is large (~1 GB extracted) and behind a button click,
so for the MVP we accept a path via `UA_YEDR_DATA_PATH` pointing at the
extracted XML file.

The XML structure is roughly:
    <DATA>
      <RECORD>
        <NAME>...</NAME>
        <SHORT_NAME>...</SHORT_NAME>
        <EDRPOU>12345678</EDRPOU>
        <ADDRESS>...</ADDRESS>
        <STAN>зареєстровано</STAN>
      </RECORD>
      ...
    </DATA>
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator

from packages.ingestion.sources._base import IngestedCompanyDTO, IngestionSource

logger = logging.getLogger(__name__)

ENV_DATA_PATH = "UA_YEDR_DATA_PATH"
CHUNK_SIZE = 64 * 1024


class UAYedrSource(IngestionSource):
    country_code = "UA"
    name = "ua_yedr"
    schedule = "weekly"

    def __init__(self, data_path: str | os.PathLike[str] | None = None) -> None:
        self._explicit_path = Path(data_path) if data_path is not None else None

    def _resolve_path(self) -> Path:
        candidate = self._explicit_path or Path(os.environ.get(ENV_DATA_PATH, ""))
        if not candidate or str(candidate) == ".":
            raise FileNotFoundError(
                f"{ENV_DATA_PATH} is not set. Download the YeDR dump from "
                f"https://data.gov.ua/ and point {ENV_DATA_PATH} at the XML file."
            )
        if not candidate.exists():
            raise FileNotFoundError(f"YeDR XML not found at {candidate}")
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
        # Stream-parse with iterparse on the concatenated bytes. We accumulate
        # one RECORD at a time, never the whole document. xml.etree's iterparse
        # works on a file-like object, so we wrap the async byte stream.
        from xml.etree import ElementTree as ET

        buffer = bytearray()
        async for chunk in chunks:
            buffer.extend(chunk)
            # Process complete <RECORD>...</RECORD> blocks out of the buffer.
            while True:
                end = buffer.find(b"</RECORD>")
                if end == -1:
                    break
                start = buffer.find(b"<RECORD")
                if start == -1 or start > end:
                    # Skip junk preceding the record.
                    del buffer[: end + len(b"</RECORD>")]
                    continue
                record_bytes = bytes(buffer[start : end + len(b"</RECORD>")])
                del buffer[: end + len(b"</RECORD>")]
                try:
                    elem = ET.fromstring(record_bytes)
                except ET.ParseError as exc:
                    logger.debug("UA YeDR malformed record skipped: %s", exc)
                    continue
                dto = self._to_dto(elem)
                if dto is not None:
                    yield dto

    @staticmethod
    def _to_dto(elem) -> IngestedCompanyDTO | None:  # type: ignore[no-untyped-def]
        def t(tag: str) -> str | None:
            node = elem.find(tag)
            return node.text.strip() if node is not None and node.text else None

        edrpou = t("EDRPOU")
        name = t("NAME") or t("SHORT_NAME")
        if not edrpou or not name:
            return None
        identifiers = [{"type": "OTHER", "value": edrpou, "label": "EDRPOU"}]
        return IngestedCompanyDTO(
            country="UA",
            source_id=edrpou,
            name=name,
            status=t("STAN"),
            address=t("ADDRESS"),
            identifiers=identifiers,
            raw={
                "edrpou": edrpou,
                "name": name,
                "short_name": t("SHORT_NAME"),
                "stan": t("STAN"),
                "address": t("ADDRESS"),
            },
        )
