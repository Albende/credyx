"""Credit risk engine.

Composition of (1) deterministic ratio calculation and (2) the LLM service.
The LLM never does arithmetic — it gets pre-computed ratios as context.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from packages.llm.service import LLMService, get_llm_service
from packages.risk.ratios import compute_ratios
from packages.shared.models import CompanyDetails, FinancialFiling, RiskAssessment

logger = logging.getLogger(__name__)


class RiskEngine:
    def __init__(self, llm: LLMService | None = None) -> None:
        self.llm = llm or get_llm_service()

    async def analyze(
        self,
        company: CompanyDetails,
        filings: list[FinancialFiling],
        *,
        pdf_text_excerpts: dict[int, str] | None = None,
    ) -> RiskAssessment:
        ratios = compute_ratios(filings)
        logger.info(
            "Risk analysis: company=%s filings=%d ratios=%d",
            company.id, len(filings), len(ratios),
        )
        assessment = await self.llm.analyze_credit_risk(
            company, filings, ratios, pdf_text_excerpts=pdf_text_excerpts
        )
        return assessment


@lru_cache(maxsize=1)
def get_risk_engine() -> RiskEngine:
    return RiskEngine()
