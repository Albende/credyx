"""Tests for sanctions screening wired into the RiskEngine."""
from __future__ import annotations

from typing import Any

import pytest

from packages.adapters._global.opensanctions import OpenSanctionsClient, SanctionHit
from packages.llm.service import LLMService
from packages.risk.engine import RiskEngine
from packages.shared.models import (
    CompanyDetails,
    Director,
    Recommendation,
    RegistryIdentifier,
    RiskAssessment,
)


class _FakeSanctions(OpenSanctionsClient):
    """OpenSanctionsClient with deterministic, in-memory responses keyed by name."""

    def __init__(self, hits_by_name: dict[str, list[SanctionHit]]) -> None:
        self._hits = hits_by_name
        self.calls: list[dict[str, Any]] = []

    async def screen(  # type: ignore[override]
        self,
        *,
        name: str,
        country: str | None = None,
        identifiers: list[str] | None = None,
        schema: str = "Company",
        limit: int = 5,
    ) -> list[SanctionHit]:
        self.calls.append(
            {"name": name, "country": country, "identifiers": identifiers, "schema": schema}
        )
        return list(self._hits.get(name, []))


class _FakeLLM(LLMService):
    """LLMService that returns a pre-baked APPROVE assessment."""

    def __init__(self, recommendation: Recommendation = Recommendation.APPROVE) -> None:
        self._recommendation = recommendation
        self.captured_sanctions_context: str | None = None

    async def analyze_credit_risk(  # type: ignore[override]
        self,
        company: CompanyDetails,
        filings: list[Any],
        ratios: list[Any],
        *,
        pdf_text_excerpts: dict[int, str] | None = None,
        sanctions_context: str | None = None,
    ) -> RiskAssessment:
        self.captured_sanctions_context = sanctions_context
        return RiskAssessment(
            company_id=company.id,
            score=80,
            recommendation=self._recommendation,
            recommended_credit_limit_eur=100_000.0,
            reasoning="Looks healthy.",
            key_signals=["solvent"],
            red_flags=[],
            confidence=0.85,
            ratios=ratios,
            model_used="fake",
        )


def _company(name: str = "ACME Ltd", directors: list[Director] | None = None) -> CompanyDetails:
    return CompanyDetails(
        id="C1",
        name=name,
        country="GB",
        identifiers=[RegistryIdentifier(type="COMPANY_NUMBER", value="12345678")],  # type: ignore[arg-type]
        directors=directors or [],
    )


def _hit(name: str, score: float, datasets: list[str] | None = None) -> SanctionHit:
    return SanctionHit(
        id=f"id-{name.replace(' ', '-').lower()}",
        score=score,
        name=name,
        schema_type="Person",
        datasets=datasets or ["us_ofac_sdn"],
        properties={},
        source_url=f"https://www.opensanctions.org/entities/id-{name}/",
    )


@pytest.mark.asyncio
async def test_sanctioned_director_forces_reject_and_red_flag() -> None:
    director = Director(name="Vladimir Putin", role="CEO")
    company = _company(directors=[director])
    sanctions = _FakeSanctions(
        {
            "ACME Ltd": [],
            "Vladimir Putin": [_hit("Vladimir Putin", 0.96, ["us_ofac_sdn", "eu_fsf"])],
        }
    )
    engine = RiskEngine(llm=_FakeLLM(Recommendation.APPROVE), sanctions=sanctions)

    assessment = await engine.analyze(company, filings=[])

    assert assessment.recommendation == Recommendation.REJECT
    assert assessment.recommended_credit_limit_eur == 0.0
    assert assessment.score <= 10
    assert any("SANCTIONS:" in flag and "Vladimir Putin" in flag for flag in assessment.red_flags)
    assert any("us_ofac_sdn" in flag for flag in assessment.red_flags)


@pytest.mark.asyncio
async def test_sanctioned_company_name_forces_reject() -> None:
    company = _company(name="Rosneft Oil Company")
    sanctions = _FakeSanctions(
        {"Rosneft Oil Company": [_hit("Rosneft", 0.91, ["us_ofac_sdn"])]}
    )
    engine = RiskEngine(llm=_FakeLLM(Recommendation.APPROVE), sanctions=sanctions)

    assessment = await engine.analyze(company, filings=[])

    assert assessment.recommendation == Recommendation.REJECT


@pytest.mark.asyncio
async def test_clean_company_keeps_llm_recommendation() -> None:
    company = _company(directors=[Director(name="Jane Doe")])
    sanctions = _FakeSanctions({})  # no hits anywhere
    fake_llm = _FakeLLM(Recommendation.APPROVE)
    engine = RiskEngine(llm=fake_llm, sanctions=sanctions)

    assessment = await engine.analyze(company, filings=[])

    assert assessment.recommendation == Recommendation.APPROVE
    assert assessment.recommended_credit_limit_eur == 100_000.0
    assert all("SANCTIONS:" not in flag for flag in assessment.red_flags)
    assert fake_llm.captured_sanctions_context is None


@pytest.mark.asyncio
async def test_possible_match_flagged_but_not_rejected() -> None:
    company = _company(directors=[Director(name="John Smith")])
    sanctions = _FakeSanctions(
        {"John Smith": [_hit("John Smith Jr.", 0.71, ["wd_peps"])]}
    )
    engine = RiskEngine(llm=_FakeLLM(Recommendation.APPROVE), sanctions=sanctions)

    assessment = await engine.analyze(company, filings=[])

    assert assessment.recommendation == Recommendation.APPROVE
    assert any("SANCTIONS_POSSIBLE" in flag for flag in assessment.red_flags)


@pytest.mark.asyncio
async def test_screening_failure_drops_confidence_but_does_not_block() -> None:
    class _BrokenSanctions(OpenSanctionsClient):
        async def screen(self, **_kwargs: Any) -> list[SanctionHit]:  # type: ignore[override]
            raise RuntimeError("upstream down")

    fake_llm = _FakeLLM(Recommendation.APPROVE)
    engine = RiskEngine(llm=fake_llm, sanctions=_BrokenSanctions())

    assessment = await engine.analyze(_company(), filings=[])

    assert assessment.recommendation == Recommendation.APPROVE
    assert assessment.confidence == pytest.approx(0.65, abs=1e-3)
    assert any("SANCTIONS_SCREENING_UNAVAILABLE" in flag for flag in assessment.red_flags)


@pytest.mark.asyncio
async def test_engine_screens_company_and_each_unique_director() -> None:
    directors = [
        Director(name="Alice"),
        Director(name="Bob"),
        Director(name="Alice"),  # duplicate — should not be screened twice
    ]
    company = _company(directors=directors)
    sanctions = _FakeSanctions({})
    engine = RiskEngine(llm=_FakeLLM(), sanctions=sanctions)

    await engine.analyze(company, filings=[])

    names_called = [c["name"] for c in sanctions.calls]
    assert names_called.count("Alice") == 1
    assert names_called.count("Bob") == 1
    assert "ACME Ltd" in names_called
    assert {c["schema"] for c in sanctions.calls if c["name"] != "ACME Ltd"} == {"Person"}
