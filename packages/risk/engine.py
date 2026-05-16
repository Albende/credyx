"""Credit risk engine.

Composition of (1) deterministic ratio calculation, (2) sanctions/PEP screening,
and (3) the LLM service. The LLM never does arithmetic — it gets pre-computed
ratios as context. Sanctions hits force a REJECT before the LLM weighs in.
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from packages.adapters._global.opensanctions import (
    HIGH_CONFIDENCE_THRESHOLD,
    POSSIBLE_MATCH_THRESHOLD,
    OpenSanctionsClient,
    SanctionHit,
)
from packages.llm.service import LLMService, get_llm_service
from packages.risk.ratios import compute_ratios_series
from packages.shared.models import (
    CompanyDetails,
    FinancialFiling,
    Recommendation,
    RiskAssessment,
)

logger = logging.getLogger(__name__)


class RiskEngine:
    def __init__(
        self,
        llm: LLMService | None = None,
        sanctions: OpenSanctionsClient | None = None,
    ) -> None:
        self.llm = llm or get_llm_service()
        self.sanctions = sanctions or OpenSanctionsClient()

    async def analyze(
        self,
        company: CompanyDetails,
        filings: list[FinancialFiling],
        *,
        pdf_text_excerpts: dict[int, str] | None = None,
    ) -> RiskAssessment:
        ratios = compute_ratios_series(filings)
        logger.info(
            "Risk analysis: company=%s filings=%d ratios=%d",
            company.id, len(filings), len(ratios),
        )

        screen_hits, screen_failed = await self._screen_all(company)
        sanctions_context = self._build_sanctions_context(screen_hits) if screen_hits else None

        assessment = await self.llm.analyze_credit_risk(
            company,
            filings,
            ratios,
            pdf_text_excerpts=pdf_text_excerpts,
            sanctions_context=sanctions_context,
        )
        assessment.ratios = ratios

        high_hits = [h for h in screen_hits if h.score >= HIGH_CONFIDENCE_THRESHOLD]
        possible_hits = [
            h for h in screen_hits
            if POSSIBLE_MATCH_THRESHOLD <= h.score < HIGH_CONFIDENCE_THRESHOLD
        ]

        for h in high_hits:
            assessment.red_flags.append(
                f"SANCTIONS: matches '{h.name}' on {{{', '.join(h.datasets)}}} (score {h.score:.2f})"
            )
        for h in possible_hits:
            assessment.red_flags.append(
                f"SANCTIONS_POSSIBLE: '{h.name}' on {{{', '.join(h.datasets)}}} (score {h.score:.2f})"
            )

        if high_hits:
            assessment.recommendation = Recommendation.REJECT
            assessment.score = min(assessment.score, 10)
            assessment.recommended_credit_limit_eur = 0.0

        if screen_failed:
            assessment.red_flags.append(
                "SANCTIONS_SCREENING_UNAVAILABLE: confidence reduced by 0.2"
            )
            assessment.confidence = max(0.0, assessment.confidence - 0.2)

        return assessment

    async def _screen_all(
        self, company: CompanyDetails
    ) -> tuple[list[SanctionHit], bool]:
        director_names: list[str] = []
        seen: set[str] = set()
        for d in company.directors:
            n = (d.name or "").strip()
            if n and n not in seen:
                seen.add(n)
                director_names.append(n)

        sem = asyncio.Semaphore(5)

        async def _screen_one(name: str, schema: str) -> list[SanctionHit]:
            async with sem:
                return await self.sanctions.screen(
                    name=name, country=company.country, schema=schema
                )

        tasks = [_screen_one(company.name, "Company")]
        tasks.extend(_screen_one(n, "Person") for n in director_names)

        try:
            results = await asyncio.gather(*tasks)
        except Exception as exc:
            logger.warning("Sanctions screening failed: %s", exc)
            return [], True

        hits: list[SanctionHit] = []
        for r in results:
            hits.extend(r)
        return hits, False

    @staticmethod
    def _build_sanctions_context(hits: list[SanctionHit]) -> str:
        lines = ["Sanctions/PEP screening hits:"]
        for h in hits:
            lines.append(
                f"  - {h.name} (score {h.score:.2f}, datasets: {', '.join(h.datasets)})"
            )
        return "\n".join(lines)


@lru_cache(maxsize=1)
def get_risk_engine() -> RiskEngine:
    return RiskEngine()
