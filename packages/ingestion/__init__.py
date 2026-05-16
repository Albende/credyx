"""Bulk-data ingestion pipeline.

Some country registries don't expose a per-company search API but DO publish
periodic full dumps. This package downloads, parses, and upserts those dumps
into the `ingested_companies` table so adapters can serve `search_by_name`
locally via Postgres pg_trgm similarity.

Adding a new bulk source:
    1. Create `packages/ingestion/sources/{cc}_{registry}.py`.
    2. Subclass `IngestionSource` and implement `download` + `parse`.
    3. Register in `packages/ingestion/scheduler.py::SOURCES`.
    4. The nightly Celery beat task will then run it.
"""
from __future__ import annotations

from packages.ingestion.sources._base import IngestedCompanyDTO, IngestionSource

__all__ = ["IngestedCompanyDTO", "IngestionSource"]
