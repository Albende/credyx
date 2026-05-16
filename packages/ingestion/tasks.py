"""Celery tasks driving the ingestion pipeline.

The only public task is `ingest_source_task` which takes the import path of
an `IngestionSource` subclass (e.g. `"packages.ingestion.sources.be_kbo:BEKboSource"`),
runs its `run()` coroutine, and returns the row count + duration.
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import time
from typing import Any

from apps.api.app.db import get_sessionmaker
from packages.ingestion.celery_app import celery_app
from packages.ingestion.sources._base import IngestionSource

logger = logging.getLogger(__name__)


def _resolve(path: str) -> type[IngestionSource]:
    """Load `module.path:ClassName` -> class object."""
    if ":" not in path:
        raise ValueError(f"Expected 'module:ClassName', got {path!r}")
    module_name, class_name = path.split(":", 1)
    module = importlib.import_module(module_name)
    cls = getattr(module, class_name)
    if not isinstance(cls, type) or not issubclass(cls, IngestionSource):
        raise TypeError(f"{path} is not an IngestionSource subclass")
    return cls


async def _run_one(cls: type[IngestionSource]) -> int:
    sm = get_sessionmaker()
    async with sm() as session:
        source = cls()
        return await source.run(session)


@celery_app.task(name="packages.ingestion.tasks.ingest_source_task")
def ingest_source_task(source_class_path: str) -> dict[str, Any]:
    """Run a source ingestion.

    Returns: ``{"source": ..., "count": N, "duration_ms": ...}``.
    On failure: ``{"source": ..., "error": "..."}`` with the exception re-raised
    so Celery records it as failed.
    """
    started = time.monotonic()
    cls = _resolve(source_class_path)
    try:
        count = asyncio.run(_run_one(cls))
    except Exception as exc:
        logger.exception("ingestion failed for %s", source_class_path)
        raise exc
    duration_ms = int((time.monotonic() - started) * 1000)
    result = {"source": source_class_path, "count": count, "duration_ms": duration_ms}
    logger.info("ingestion done: %s", result)
    return result
