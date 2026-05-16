"""Belgium — KBO/BCE Open Data bulk dump.

Source: https://kbopub.economie.fgov.be/kbo-open-data/

The KBO open-data download requires a free FOD Economie account and the dump
is delivered as a zip of CSVs. For the MVP we don't try to log in and unzip
on the fly; the operator downloads the monthly dump manually, unzips it, and
points `BE_KBO_DATA_PATH` at the directory containing the CSVs (or directly
at `enterprise.csv`).

Expected file: `enterprise.csv` with columns
    EnterpriseNumber,Status,JuridicalSituation,TypeOfEnterprise,JuridicalForm,StartDate

If a companion `denomination.csv` sits next to it we also read names from it
(KBO splits the enterprise number / status from the trade names). When that
file is absent we fall back to the EnterpriseNumber itself as the name so the
row is still searchable by its VAT-style identifier.
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

ENV_DATA_PATH = "BE_KBO_DATA_PATH"
CHUNK_SIZE = 64 * 1024  # 64 KB stream chunks


class BEKboSource(IngestionSource):
    country_code = "BE"
    name = "be_kbo"
    schedule = "monthly"

    def __init__(self, data_path: str | os.PathLike[str] | None = None) -> None:
        self._explicit_path = Path(data_path) if data_path is not None else None

    def _resolve_enterprise_csv(self) -> Path:
        candidate = self._explicit_path or Path(os.environ.get(ENV_DATA_PATH, ""))
        if not candidate or str(candidate) == ".":
            raise FileNotFoundError(
                f"{ENV_DATA_PATH} is not set. Download the KBO open-data dump "
                "from https://kbopub.economie.fgov.be/kbo-open-data/ and point "
                f"{ENV_DATA_PATH} at the extracted enterprise.csv (or the dir)."
            )
        if candidate.is_dir():
            candidate = candidate / "enterprise.csv"
        if not candidate.exists():
            raise FileNotFoundError(f"KBO enterprise.csv not found at {candidate}")
        return candidate

    def _load_denominations(self, enterprise_csv: Path) -> dict[str, str]:
        """Best-effort: build {EnterpriseNumber: name} from denomination.csv."""
        denom = enterprise_csv.parent / "denomination.csv"
        if not denom.exists():
            return {}
        out: dict[str, str] = {}
        with denom.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                num = (row.get("EnterpriseNumber") or row.get("EntityNumber") or "").strip()
                name = (row.get("Denomination") or "").strip()
                if not num or not name:
                    continue
                # Prefer Language='2' (French) > '1' (Dutch) > anything else; keep first seen otherwise.
                lang = (row.get("Language") or "").strip()
                existing = out.get(num)
                if existing is None or lang in {"1", "2"}:
                    out[num] = name
        return out

    async def download(self, *, since: datetime | None = None) -> AsyncIterator[bytes]:
        path = self._resolve_enterprise_csv()
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(CHUNK_SIZE)
                if not chunk:
                    return
                yield chunk

    async def parse(
        self, chunks: AsyncIterator[bytes]
    ) -> AsyncIterator[IngestedCompanyDTO]:
        # Build name lookup once before consuming the stream.
        try:
            denoms = self._load_denominations(self._resolve_enterprise_csv())
        except FileNotFoundError:
            denoms = {}

        buffer = ""
        async for chunk in chunks:
            buffer += chunk.decode("utf-8", errors="replace")
            # Split on the last newline; keep the unterminated tail for next iter.
            last_nl = buffer.rfind("\n")
            if last_nl == -1:
                continue
            block, buffer = buffer[: last_nl + 1], buffer[last_nl + 1 :]
            for dto in self._parse_block(block, denoms, expect_header=False):
                yield dto
        if buffer.strip():
            for dto in self._parse_block(buffer, denoms, expect_header=False):
                yield dto

    def _parse_block(
        self, block: str, denoms: dict[str, str], *, expect_header: bool
    ) -> list[IngestedCompanyDTO]:
        # `block` may contain the CSV header on the very first call; DictReader
        # handles that transparently when we pass the header in fieldnames=None
        # for the first block and fixed fieldnames thereafter. Simplest correct
        # approach: re-detect by sniffing the first line of `block`.
        out: list[IngestedCompanyDTO] = []
        reader: csv.DictReader[str]
        first_line = block.split("\n", 1)[0].strip()
        if first_line.lower().startswith("enterprisenumber"):
            reader = csv.DictReader(io.StringIO(block))
        else:
            reader = csv.DictReader(
                io.StringIO(block),
                fieldnames=[
                    "EnterpriseNumber",
                    "Status",
                    "JuridicalSituation",
                    "TypeOfEnterprise",
                    "JuridicalForm",
                    "StartDate",
                ],
            )
        for row in reader:
            num = (row.get("EnterpriseNumber") or "").strip()
            if not num:
                continue
            name = denoms.get(num) or num
            identifiers = [{"type": "VAT", "value": f"BE{num.replace('.', '')}"}]
            out.append(
                IngestedCompanyDTO(
                    country="BE",
                    source_id=num,
                    name=name,
                    status=(row.get("Status") or None),
                    address=None,
                    identifiers=identifiers,
                    raw={k: v for k, v in row.items() if v},
                )
            )
        return out
