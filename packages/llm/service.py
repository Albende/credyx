"""LLM service: the only thing in the codebase that calls a model."""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from packages.llm.providers import KieAIGeminiProvider, LLMProvider
from packages.shared.models import (
    CompanyDetails,
    FinancialFiling,
    FinancialRatios,
    Recommendation,
    RiskAssessment,
)

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent / "prompts" / "credit_risk.md"

_RISK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "score",
        "recommendation",
        "recommended_credit_limit_eur",
        "reasoning",
        "key_signals",
        "red_flags",
        "confidence",
    ],
    "properties": {
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "recommendation": {"type": "string", "enum": ["APPROVE", "REVIEW", "REJECT"]},
        "recommended_credit_limit_eur": {"type": "number", "minimum": 0},
        "reasoning": {"type": "string"},
        "key_signals": {"type": "array", "items": {"type": "string"}},
        "red_flags": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}


class LLMService:
    """High-level wrapper over an LLMProvider."""

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.provider = provider or KieAIGeminiProvider()

    async def analyze_credit_risk(
        self,
        company: CompanyDetails,
        filings: list[FinancialFiling],
        ratios: list[FinancialRatios],
        *,
        pdf_text_excerpts: dict[int, str] | None = None,
    ) -> RiskAssessment:
        """Run a credit risk analysis on a company.

        Pre-computed ratios are passed in so the model never does arithmetic.
        `pdf_text_excerpts` is a year -> extracted text map for filings that
        only have a PDF (no structured XBRL/JSON).
        """
        system_prompt = _load_prompt()
        user_prompt = _build_user_prompt(company, filings, ratios, pdf_text_excerpts or {})

        try:
            raw = await self.provider.generate_json(
                system=system_prompt,
                user=user_prompt,
                schema_hint=_RISK_SCHEMA,
                temperature=0.2,
                max_output_tokens=2048,
            )
        except Exception as exc:
            logger.exception("LLM call failed: %s", exc)
            raise

        try:
            parsed = _coerce_assessment(raw, company_id=company.id, ratios=ratios)
        except Exception:
            logger.warning("First parse failed, retrying once with explicit reminder")
            retry_prompt = (
                user_prompt
                + "\n\nReturn ONLY a single JSON object matching the schema. "
                "Do not include any prose, headers, or markdown."
            )
            raw = await self.provider.generate_json(
                system=system_prompt,
                user=retry_prompt,
                schema_hint=_RISK_SCHEMA,
                temperature=0.1,
                max_output_tokens=2048,
            )
            parsed = _coerce_assessment(raw, company_id=company.id, ratios=ratios)

        parsed.model_used = self.provider.name
        return parsed


@lru_cache(maxsize=1)
def get_llm_service() -> LLMService:
    return LLMService()


def _load_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _build_user_prompt(
    company: CompanyDetails,
    filings: list[FinancialFiling],
    ratios: list[FinancialRatios],
    pdf_text_excerpts: dict[int, str],
) -> str:
    lines: list[str] = []
    lines.append("## Company")
    lines.append(f"- Name: {company.name}")
    lines.append(f"- Country: {company.country}")
    lines.append(f"- Status: {company.status or 'unknown'}")
    lines.append(f"- Legal form: {company.legal_form or 'unknown'}")
    lines.append(f"- Incorporated: {company.incorporation_date or 'unknown'}")
    lines.append(f"- Capital: {company.capital_amount} {company.capital_currency or ''}")
    if company.sic_codes or company.nace_codes:
        lines.append(
            f"- Industry codes: SIC={company.sic_codes} NACE={company.nace_codes}"
        )
    if company.directors:
        director_names = ", ".join(d.name for d in company.directors[:5])
        lines.append(f"- Directors (top 5): {director_names}")

    lines.append("\n## Pre-computed financial ratios (DO NOT recalculate)")
    if not ratios:
        lines.append("(no ratios — no structured financials were available)")
    else:
        for r in sorted(ratios, key=lambda x: x.year, reverse=True):
            parts = [f"year={r.year}"]
            for field in (
                "current_ratio",
                "quick_ratio",
                "debt_to_equity",
                "debt_to_assets",
                "roe",
                "roa",
                "gross_margin",
                "net_margin",
                "working_capital",
                "altman_z_score",
                "revenue_growth_yoy",
            ):
                val = getattr(r, field)
                if val is not None:
                    parts.append(f"{field}={val:.3f}")
            lines.append("- " + ", ".join(parts))

    lines.append("\n## Filings available")
    if not filings:
        lines.append("(none)")
    else:
        for f in filings:
            lines.append(
                f"- {f.year} {f.type.value} period_end={f.period_end} "
                f"currency={f.currency or '?'} "
                f"format={f.document_format or 'structured' if f.structured_data else 'url'}"
            )

    if pdf_text_excerpts:
        lines.append("\n## PDF excerpts (limited)")
        for year, text in sorted(pdf_text_excerpts.items(), reverse=True):
            snippet = text[:3000]
            lines.append(f"\n### {year}\n{snippet}")

    lines.append(
        "\n## Task\nProduce the credit risk assessment as a single JSON object "
        "matching the provided schema."
    )
    return "\n".join(lines)


def _coerce_assessment(
    raw: dict[str, Any],
    *,
    company_id: str,
    ratios: list[FinancialRatios],
) -> RiskAssessment:
    rec_val = str(raw.get("recommendation", "REVIEW")).upper()
    if rec_val not in {r.value for r in Recommendation}:
        rec_val = "REVIEW"
    score = int(raw.get("score", 50))
    score = max(0, min(100, score))
    confidence = float(raw.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))
    limit = float(raw.get("recommended_credit_limit_eur", 0))
    if limit < 0:
        limit = 0
    return RiskAssessment(
        company_id=company_id,
        score=score,
        recommendation=Recommendation(rec_val),
        recommended_credit_limit_eur=limit,
        reasoning=str(raw.get("reasoning", "")).strip() or "No reasoning provided.",
        key_signals=[str(s) for s in raw.get("key_signals", [])][:20],
        red_flags=[str(s) for s in raw.get("red_flags", [])][:20],
        confidence=confidence,
        ratios=ratios,
    )
