"""Unit tests: parse a 3-row BE KBO CSV fixture and validate DTO output."""
from __future__ import annotations

from pathlib import Path

import pytest

from packages.ingestion.sources._base import IngestedCompanyDTO
from packages.ingestion.sources.be_kbo import BEKboSource

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.asyncio
async def test_be_kbo_parses_three_row_csv() -> None:
    source = BEKboSource(data_path=FIXTURES / "enterprise.csv")
    dtos: list[IngestedCompanyDTO] = []
    async for dto in source.parse(source.download()):
        dtos.append(dto)

    assert len(dtos) == 3
    assert all(d.country == "BE" for d in dtos)
    assert all(d.source_id for d in dtos)
    assert all(isinstance(d, IngestedCompanyDTO) for d in dtos)

    by_id = {d.source_id: d for d in dtos}
    acme = by_id["0123.456.789"]
    assert acme.name == "Acme Brussels SA"
    assert acme.status == "AC"
    assert acme.identifiers == [{"type": "VAT", "value": "BE0123456789"}]
    assert acme.name_normalized == "acme brussels sa"
    # raw must preserve the original row for audit.
    assert acme.raw["JuridicalForm"] == "015"


@pytest.mark.asyncio
async def test_be_kbo_missing_path_raises() -> None:
    source = BEKboSource(data_path=Path("/does/not/exist.csv"))
    with pytest.raises(FileNotFoundError):
        async for _ in source.download():
            pass


@pytest.mark.asyncio
async def test_be_kbo_falls_back_to_enterprise_number_when_no_denominations(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "enterprise.csv"
    csv_path.write_text(
        "EnterpriseNumber,Status,JuridicalSituation,TypeOfEnterprise,JuridicalForm,StartDate\n"
        "0111.222.333,AC,000,2,015,01-01-2020\n",
        encoding="utf-8",
    )
    source = BEKboSource(data_path=csv_path)
    dtos = [d async for d in source.parse(source.download())]
    assert len(dtos) == 1
    assert dtos[0].name == "0111.222.333"
