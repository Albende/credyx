"""HTTP routes for Credyx API."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.app.cache import (
    get_cached_company,
    get_cached_filings,
    upsert_company,
    upsert_filings,
)
from apps.api.app.db import Company as CompanyRow
from apps.api.app.db import IngestionJob
from apps.api.app.db import PDFTextCache
from apps.api.app.db import RiskAssessment as RiskAssessmentRow
from apps.api.app.auth import current_user
from apps.api.app.db import UsageWindow, User, get_session
from apps.api.app.feature_gate import consume_quota, plan_features, requires_feature
from packages.adapters._base.errors import (
    AdapterNotImplementedError,
    InvalidIdentifierError,
)
from packages.adapters._global.gleif import GLEIFClient
from packages.adapters._global.opensanctions import (
    OpenSanctionsClient,
    SanctionHit,
)
from packages.adapters.registry import get_adapter, get_adapter_registry
from packages.parsers.pdf import PDFExtractError, extract_from_url
from packages.risk import get_risk_engine
from packages.shared.models import (
    AdapterStatus,
    CompanyDetails,
    FinancialFiling as FinancialFilingDTO,
    IdentifierType,
    RiskAssessment as RiskAssessmentDTO,
)

PDF_TEXT_CAP = 50_000

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.get("/countries")
async def list_countries(probe: bool = Query(False)) -> dict[str, Any]:
    """List supported countries.

    Static metadata by default (<100ms). Pass `?probe=true` for live health
    checks across all adapters (~30s).
    """
    registry = get_adapter_registry()

    if not probe:
        seen_ids: set[int] = set()
        items: list[dict[str, Any]] = []
        for cc, adapter in registry.items():
            if id(adapter) in seen_ids:
                continue
            seen_ids.add(id(adapter))
            is_real = type(adapter).__name__ != "NotImplementedAdapter"
            api_key_env = getattr(adapter, "api_key_env", None)
            api_key_present = (
                bool(os.getenv(api_key_env)) if api_key_env else not getattr(adapter, "requires_api_key", False)
            )
            items.append({
                "country_code": cc,
                "name": getattr(adapter, "country_name", cc),
                "status": "ok" if is_real else "not_implemented",
                "capabilities": {"search": is_real, "lookup": is_real, "financials": is_real},
                "requires_api_key": getattr(adapter, "requires_api_key", False),
                "api_key_present": api_key_present,
                "rate_limit_per_minute": getattr(adapter, "rate_limit_per_minute", None),
                "notes": None,
            })
        items.sort(key=lambda x: x["country_code"])
        return {"countries": items}

    sem = asyncio.Semaphore(10)

    async def _probe(cc: str, adapter) -> dict[str, Any]:
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

    seen_ids = set()
    tasks = []
    for cc, adapter in registry.items():
        if id(adapter) in seen_ids:
            continue
        seen_ids.add(id(adapter))
        tasks.append(_probe(cc, adapter))
    items = await asyncio.gather(*tasks)
    items.sort(key=lambda x: x["country_code"])
    return {"countries": items}


@router.get("/search")
async def search_companies(
    country: str = Query(..., min_length=2, max_length=2),
    name: str = Query(..., min_length=2),
    limit: int = Query(10, ge=1, le=50),
    fallback: bool = Query(True, description="Fall back to GLEIF if national adapter has no name search"),
    _quota: None = Depends(consume_quota("searches", UsageWindow.day)),
) -> dict[str, Any]:
    adapter = get_adapter(country)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"No adapter for country {country}")

    results = []
    adapter_unavailable_reason: str | None = None
    source = "adapter"
    try:
        results = await adapter.search_by_name(name, limit=limit)
    except AdapterNotImplementedError as exc:
        adapter_unavailable_reason = str(exc)
    except InvalidIdentifierError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not results and fallback:
        try:
            gleif = GLEIFClient()
            results = await gleif.search_by_name(name=name, country=country.upper(), limit=limit)
            if results:
                source = "gleif"
        except Exception as exc:
            logger.warning("GLEIF fallback failed: %s", exc)

    if not results and adapter_unavailable_reason:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=adapter_unavailable_reason,
        )

    return {
        "country": country.upper(),
        "query": name,
        "source": source,
        "results": [r.model_dump(mode="json") for r in results],
    }


@router.get("/search/global")
async def search_global(
    name: str = Query(..., min_length=2),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    """Search GLEIF globally without country filter — covers ~2M+ entities worldwide."""
    gleif = GLEIFClient()
    results = await gleif.search_by_name(name=name, limit=limit)
    return {
        "query": name,
        "source": "gleif",
        "results": [r.model_dump(mode="json") for r in results],
    }


class CompanyResponse(BaseModel):
    cached: bool
    last_fetched_at: datetime | None
    details: CompanyDetails


_LEI_RE = __import__("re").compile(r"^[A-Z0-9]{18}\d{2}$")


@router.get("/companies/{country}/{identifier}", response_model=CompanyResponse)
async def get_company(
    country: str,
    identifier: str,
    id_type: str | None = Query(None, description="Override identifier type (defaults to adapter primary)"),
    force_refresh: bool = Query(False),
    session: AsyncSession = Depends(get_session),
    _quota: None = Depends(consume_quota("company_lookups", UsageWindow.day)),
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

    if _LEI_RE.match(identifier):
        details = await GLEIFClient().lookup_by_lei(identifier)
        if not details:
            raise HTTPException(status_code=404, detail=f"LEI {identifier} not found in GLEIF")
        await upsert_company(session, details)
        return CompanyResponse(cached=False, last_fetched_at=datetime.now(timezone.utc), details=details)

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
    with_text: bool = Query(
        False,
        description=(
            "Download PDF filings and extract their text into "
            "structured_data['pdf_text_excerpts']. Slow."
        ),
    ),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(current_user),
    _quota: None = Depends(consume_quota("financial_lookups", UsageWindow.month)),
) -> dict[str, Any]:
    if with_text:
        if not plan_features(_user).get("pdf_extraction", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "feature_unavailable",
                    "feature": "pdf_extraction",
                    "upgrade_url": "/pricing",
                },
            )
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

    if not force_refresh and not with_text:
        rows = await get_cached_filings(session, cached.id)
        if rows:
            return {
                "country": country.upper(),
                "company_id": str(cached.id),
                "filings": [_filing_row_to_dict(r) for r in rows],
                "cached": True,
            }

    try:
        if with_text and hasattr(adapter, "fetch_financials_with_text"):
            filings = await adapter.fetch_financials_with_text(identifier, years=years)
        else:
            filings = await adapter.fetch_financials(identifier, years=years)
    except AdapterNotImplementedError as exc:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail=str(exc))

    if with_text:
        await _attach_pdf_text_to_filings(session, filings)

    await upsert_filings(session, cached.id, filings)
    return {
        "country": country.upper(),
        "company_id": str(cached.id),
        "filings": [f.model_dump(mode="json") for f in filings],
        "cached": False,
        "with_text": with_text,
    }


async def _attach_pdf_text_to_filings(
    session: AsyncSession,
    filings: list[FinancialFilingDTO],
    *,
    concurrency: int = 3,
) -> None:
    """Fill `structured_data['pdf_text_excerpts']` for each PDF filing.

    Uses the `pdf_text_cache` table to avoid re-downloading the same URL.
    Failures are logged and the filing is left untouched.
    """
    targets = [
        f for f in filings
        if f.document_url and (f.document_format or "").lower() == "pdf"
        and not (f.structured_data or {}).get("pdf_text_excerpts")
    ]
    if not targets:
        return

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _attach(filing: FinancialFilingDTO) -> None:
        url = filing.document_url
        if not url:
            return
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
        cached_row = (
            await session.execute(
                select(PDFTextCache).where(PDFTextCache.url_hash == url_hash)
            )
        ).scalar_one_or_none()
        if cached_row:
            text = cached_row.text
        else:
            async with sem:
                try:
                    text = await extract_from_url(url)
                except PDFExtractError as exc:
                    logger.warning("PDF extract failed for %s: %s", url, exc)
                    return
                except Exception as exc:
                    logger.warning("PDF download/parse failed for %s: %s", url, exc)
                    return
            await session.execute(
                pg_insert(PDFTextCache)
                .values(
                    url_hash=url_hash,
                    url=url[:2048],
                    text=text,
                    extracted_at=datetime.now(timezone.utc),
                )
                .on_conflict_do_update(
                    index_elements=[PDFTextCache.url_hash],
                    set_={
                        "text": text,
                        "url": url[:2048],
                        "extracted_at": datetime.now(timezone.utc),
                    },
                )
            )
        base = dict(filing.structured_data or {})
        base["pdf_text_excerpts"] = text[:PDF_TEXT_CAP]
        filing.structured_data = base

    await asyncio.gather(*(_attach(f) for f in targets))
    await session.commit()


class RiskAnalysisStartResponse(BaseModel):
    job_id: UUID
    status: str


@router.post("/companies/{country}/{identifier}/risk-analysis", response_model=RiskAnalysisStartResponse)
async def start_risk_analysis(
    country: str,
    identifier: str,
    session: AsyncSession = Depends(get_session),
    _feature: None = Depends(requires_feature("risk_analysis")),
    _quota: None = Depends(consume_quota("risk_analyses", UsageWindow.month)),
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


class ScreenRequest(BaseModel):
    name: str = Field(..., min_length=1)
    country: str | None = None
    identifiers: list[str] | None = None
    schema_: str = Field("Company", alias="schema")
    limit: int = Field(5, ge=1, le=25)

    model_config = {"populate_by_name": True}


@router.post("/screen", response_model=list[SanctionHit])
async def screen_entity(body: ScreenRequest) -> list[SanctionHit]:
    """Standalone OpenSanctions screening.

    Used by the UI for ad-hoc lookups; the risk engine has its own inline
    screening path on every /risk-analysis run.
    """
    client = OpenSanctionsClient()
    return await client.screen(
        name=body.name,
        country=body.country,
        identifiers=body.identifiers,
        schema=body.schema_,
        limit=body.limit,
    )


@router.get("/pl/msig/slice/{msig_id}")
async def pl_msig_slice(
    msig_id: int,
    krs: str = Query(..., min_length=10, max_length=10),
    user: User = Depends(current_user),
):
    """Extract just the company-specific pages from an MSiG gazette PDF.

    The Polish Monitor Sądowy i Gospodarczy bundles 200-page issues containing
    hundreds of company announcements. We pull the entry's `numberOfNotice`
    + start page from MSiG Detalis, download the full gazette PDF, then carve
    out only the pages between this notice's "Poz. <N>." header and the next
    "Poz. <N+1>." (the typical company announcement is 1-5 pages).

    Returns a slim PDF named for the company's KRS + monitor issue.
    """
    import httpx
    import re
    from io import BytesIO
    from fastapi.responses import StreamingResponse

    detail_url = "https://wyszukiwarka-msig.ms.gov.pl/api/Monitor/Detalis"
    download_url = "https://wyszukiwarka-msig.ms.gov.pl/api/Monitor/Download"
    async with httpx.AsyncClient(timeout=30.0, headers={"Accept": "application/json"}) as client:
        try:
            det = (await client.get(detail_url, params={"Id": msig_id})).json()
        except Exception as exc:
            raise HTTPException(502, f"MSiG detail fetch failed: {exc}") from exc
        if not det or det.get("krs") != krs:
            raise HTTPException(404, "MSiG entry not found or KRS mismatch")
        notice = str(det.get("numberOfNotice") or "")
        start_page = int(det.get("page") or 1)
        monitor = str(det.get("monitorNumber") or "")
        pdf_resp = await client.get(download_url, params={"id": msig_id})
        if pdf_resp.status_code != 200:
            raise HTTPException(502, f"MSiG PDF download returned {pdf_resp.status_code}")
        pdf_bytes = pdf_resp.content

    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(BytesIO(pdf_bytes))
    total = len(reader.pages)
    # Page index: MSiG `page` is 1-based and refers to the page WHERE the
    # notice STARTS. The PDF's first page is usually a TOC; the printed page
    # number normally equals the PDF page number for these gazettes.
    idx = max(0, min(start_page - 1, total - 1))
    # Scan forward for the next "Poz. <N+1>." to find the end of this notice.
    end_idx = idx
    try:
        next_notice_num = int(notice) + 1 if notice.isdigit() else None
    except (TypeError, ValueError):
        next_notice_num = None
    next_marker = re.compile(rf"\bPoz\.\s*{next_notice_num}\b") if next_notice_num else None
    for i in range(idx, min(idx + 8, total)):  # at most 8 pages per notice
        if i == idx:
            end_idx = i
            continue
        try:
            text = reader.pages[i].extract_text() or ""
        except Exception:
            text = ""
        if next_marker and next_marker.search(text):
            break
        end_idx = i

    writer = PdfWriter()
    for i in range(idx, end_idx + 1):
        writer.add_page(reader.pages[i])
    out = BytesIO()
    writer.write(out)
    out.seek(0)

    safe_monitor = re.sub(r"[^A-Za-z0-9._-]", "_", monitor) or str(msig_id)
    filename = f"krs_{krs}_msig_{safe_monitor}_poz_{notice or msig_id}.pdf"

    return StreamingResponse(
        out,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, max-age=86400",
        },
    )


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

            # Download every available filed report and extract its text so
            # the model analyzes the actual documents, not just structured
            # line items. Cached in pdf_text_cache across runs.
            try:
                await _attach_pdf_text_to_filings(session, filings)
            except Exception as exc:
                logger.warning("PDF text attach failed for job %s: %s", job_id, exc)
            pdf_text_excerpts = {
                f.year: (f.structured_data or {})["pdf_text_excerpts"]
                for f in filings
                if (f.structured_data or {}).get("pdf_text_excerpts")
            }

            engine = get_risk_engine()
            assessment = await engine.analyze(
                details, filings, pdf_text_excerpts=pdf_text_excerpts or None
            )

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
