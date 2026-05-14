"""HTTP routes for CreditLens API."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.cache import (
    get_cached_company,
    get_cached_filings,
    upsert_company,
    upsert_filings,
)
from apps.api.app.db import Company as CompanyRow
from apps.api.app.db import IngestionJob
from apps.api.app.db import RiskAssessment as RiskAssessmentRow
from apps.api.app.db import get_session
from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters.registry import get_adapter, get_adapter_registry
from packages.risk import get_risk_engine
from packages.shared.models import (
    AdapterStatus,
    CompanyDetails,
    FinancialFiling as FinancialFilingDTO,
    IdentifierType,
    RiskAssessment as RiskAssessmentDTO,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/countries")
async def list_countries() -> dict[str, Any]:
    """List supported countries with adapter health."""
    registry = get_adapter_registry()
    items: list[dict[str, Any]] = []
    # Run health checks concurrently. Some may be slow; cap concurrency.
    sem = asyncio.Semaphore(10)

    async def probe(cc: str, adapter) -> dict[str, Any]:
        async with sem:
            try:
                health = await asyncio.wait_for(adapter.health_check(), timeout=8.0)
            except Exception as exc:
                return {
                    "country_code": cc,
                    "name": getattr(adapter, "country_name", cc),
                    "status": AdapterStatus.ERROR.value,
                    "capabilities": {"search": False, "lookup": False, "financials": False},
                    "notes": f"health probe failed: {exc}",
                }
            return health.model_dump(mode="json")

    # Dedupe — UK/GB share an instance.
    seen_ids: set[int] = set()
    tasks = []
    for cc, adapter in registry.items():
        if id(adapter) in seen_ids:
            continue
        seen_ids.add(id(adapter))
        tasks.append(probe(cc, adapter))
    items = await asyncio.gather(*tasks)
    items.sort(key=lambda x: x["country_code"])
    return {"countries": items}


@router.get("/search")
async def search_companies(
    country: str = Query(..., min_length=2, max_length=2),
    name: str = Query(..., min_length=2),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    adapter = get_adapter(country)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"No adapter for country {country}")
    try:
        results = await adapter.search_by_name(name, limit=limit)
    except AdapterNotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc))
    except InvalidIdentifierError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "country": country.upper(),
        "query": name,
        "results": [r.model_dump(mode="json") for r in results],
    }


class CompanyResponse(BaseModel):
    cached: bool
    last_fetched_at: datetime | None
    details: CompanyDetails


@router.get("/companies/{country}/{identifier}", response_model=CompanyResponse)
async def get_company(
    country: str,
    identifier: str,
    id_type: str | None = Query(None, description="Override identifier type (defaults to adapter primary)"),
    force_refresh: bool = Query(False),
    session: AsyncSession = Depends(get_session),
) -> CompanyResponse:
    adapter = get_adapter(country)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"No adapter for country {country}")

    cached_row = await get_cached_company(session, country, identifier, force_refresh=force_refresh)
    if cached_row:
        return CompanyResponse(
            cached=True,
            last_fetched_at=cached_row.last_fetched_at,
            details=CompanyDetails.model_validate(cached_row.registry_data),
        )

    id_type_enum = _resolve_id_type(adapter, id_type)
    try:
        details = await adapter.lookup_by_identifier(id_type_enum, identifier)
    except AdapterNotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc))
    except InvalidIdentifierError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not details:
        raise HTTPException(status_code=404, detail="Company not found")

    await upsert_company(session, details)
    return CompanyResponse(cached=False, last_fetched_at=datetime.now(timezone.utc), details=details)


@router.get("/companies/{country}/{identifier}/financials")
async def get_company_financials(
    country: str,
    identifier: str,
    years: int = Query(5, ge=1, le=20),
    force_refresh: bool = Query(False),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    adapter = get_adapter(country)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"No adapter for country {country}")

    # Ensure company row exists so we can attach filings.
    cached = await get_cached_company(session, country, identifier)
    if not cached:
        id_type_enum = _resolve_id_type(adapter, None)
        try:
            details = await adapter.lookup_by_identifier(id_type_enum, identifier)
        except AdapterNotImplementedError as exc:
            raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc))
        if not details:
            raise HTTPException(status_code=404, detail="Company not found")
        cached = await upsert_company(session, details)

    if not force_refresh:
        rows = await get_cached_filings(session, cached.id)
        if rows:
            return {
                "country": country.upper(),
                "company_id": str(cached.id),
                "filings": [_filing_row_to_dict(r) for r in rows],
                "cached": True,
            }
    try:
        filings = await adapter.fetch_financials(identifier, years=years)
    except AdapterNotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc))
    await upsert_filings(session, cached.id, filings)
    return {
        "country": country.upper(),
        "company_id": str(cached.id),
        "filings": [f.model_dump(mode="json") for f in filings],
        "cached": False,
    }


class RiskAnalysisStartResponse(BaseModel):
    job_id: UUID
    status: str


@router.post("/companies/{country}/{identifier}/risk-analysis", response_model=RiskAnalysisStartResponse)
async def start_risk_analysis(
    country: str,
    identifier: str,
    session: AsyncSession = Depends(get_session),
) -> RiskAnalysisStartResponse:
    adapter = get_adapter(country)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"No adapter for country {country}")

    # Resolve company.
    cached = await get_cached_company(session, country, identifier)
    if not cached:
        id_type_enum = _resolve_id_type(adapter, None)
        try:
            details = await adapter.lookup_by_identifier(id_type_enum, identifier)
        except AdapterNotImplementedError as exc:
            raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc))
        if not details:
            raise HTTPException(status_code=404, detail="Company not found")
        cached = await upsert_company(session, details)

    job = IngestionJob(
        kind="risk_analysis",
        status="queued",
        payload={"country": country.upper(), "identifier": identifier, "company_id": str(cached.id)},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    # Inline async kickoff. In production Celery handles this — see
    # apps/api/app/workers.py — but for MVP we just spawn a task.
    asyncio.create_task(_run_risk_job(job.id))

    return RiskAnalysisStartResponse(job_id=job.id, status="queued")


@router.get("/jobs/{job_id}")
async def get_job(job_id: UUID, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    row = (
        await session.execute(select(IngestionJob).where(IngestionJob.id == job_id))
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": str(row.id),
        "kind": row.kind,
        "status": row.status,
        "payload": row.payload,
        "result": row.result,
        "error": row.error,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _resolve_id_type(adapter, override: str | None) -> IdentifierType:
    if override:
        try:
            return IdentifierType(override.upper())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Unknown id_type {override}") from exc
    if adapter.primary_identifier:
        return adapter.primary_identifier
    if adapter.identifier_types:
        return adapter.identifier_types[0]
    return IdentifierType.OTHER


def _filing_row_to_dict(r) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "year": r.year,
        "type": r.type,
        "period_end": r.period_end.isoformat() if r.period_end else None,
        "currency": r.currency,
        "structured_data": r.structured_data,
        "document_url": r.document_url,
        "document_format": r.document_format,
        "source_url": r.source_url,
        "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None,
    }


async def _run_risk_job(job_id: UUID) -> None:
    """In-process job runner. Loads filings from DB, runs the engine, writes back."""
    from apps.api.app.db import get_sessionmaker

    sm = get_sessionmaker()
    async with sm() as session:
        job = (
            await session.execute(select(IngestionJob).where(IngestionJob.id == job_id))
        ).scalar_one_or_none()
        if not job:
            return
        job.status = "running"
        await session.commit()

        try:
            company_id = UUID(job.payload["company_id"])
            country = job.payload["country"]
            identifier = job.payload["identifier"]

            company_row = (
                await session.execute(select(CompanyRow).where(CompanyRow.id == company_id))
            ).scalar_one_or_none()
            if not company_row:
                raise RuntimeError("company missing")
            details = CompanyDetails.model_validate(company_row.registry_data)

            adapter = get_adapter(country)
            if adapter is None:
                raise RuntimeError(f"no adapter for {country}")

            filing_rows = await get_cached_filings(session, company_row.id)
            if not filing_rows:
                try:
                    fetched = await adapter.fetch_financials(identifier, years=5)
                    await upsert_filings(session, company_row.id, fetched)
                    filing_rows = await get_cached_filings(session, company_row.id)
                except AdapterNotImplementedError:
                    filing_rows = []

            filings: list[FinancialFilingDTO] = []
            for fr in filing_rows:
                filings.append(
                    FinancialFilingDTO(
                        company_id=str(company_row.id),
                        year=fr.year,
                        type=fr.type,  # type: ignore[arg-type]
                        period_end=fr.period_end.date() if fr.period_end else None,
                        currency=fr.currency,
                        structured_data=fr.structured_data,
                        document_url=fr.document_url,
                        document_format=fr.document_format,
                        source_url=fr.source_url,
                    )
                )

            engine = get_risk_engine()
            assessment = await engine.analyze(details, filings)

            session.add(
                RiskAssessmentRow(
                    company_id=company_row.id,
                    score=assessment.score,
                    recommendation=assessment.recommendation.value,
                    recommended_limit_eur=assessment.recommended_credit_limit_eur,
                    reasoning=assessment.reasoning,
                    key_signals=assessment.key_signals,
                    red_flags=assessment.red_flags,
                    confidence=assessment.confidence,
                    ratios=[r.model_dump() for r in assessment.ratios],
                    model_used=assessment.model_used,
                )
            )
            job.status = "done"
            job.result = json.loads(assessment.model_dump_json())
            await session.commit()
        except Exception as exc:
            logger.exception("Risk job failed")
            job.status = "error"
            job.error = str(exc)[:1000]
            await session.commit()
