"""Celery app for background ingestion jobs.

Broker + result backend both point at `REDIS_URL` (same Redis we already use
for rate limiting and the app cache, but a separate DB index).

Run a worker with:
    celery -A packages.ingestion.celery_app worker --loglevel=INFO

Run beat (scheduled jobs) with:
    celery -A packages.ingestion.celery_app beat --loglevel=INFO

Both run as the `celery-worker` service in `docker-compose.yml`.
"""
from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

BROKER_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
# Use a different Redis logical DB for results so we don't tangle with the
# broker queue. If REDIS_URL doesn't carry a /N suffix, default to /1.
RESULT_URL = os.environ.get("CELERY_RESULT_BACKEND", BROKER_URL.rstrip("/0") + "/1"
                            if BROKER_URL.endswith("/0") else BROKER_URL)


celery_app = Celery(
    "creditlens_ingestion",
    broker=BROKER_URL,
    backend=RESULT_URL,
    include=["packages.ingestion.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Ingestion jobs are long; keep visibility high.
    broker_transport_options={"visibility_timeout": 6 * 3600},
    timezone="UTC",
)

# Beat schedule — nightly at 02:00 UTC for each source. The source path is
# the import dotted-path of the IngestionSource subclass. To toggle a source
# off, comment its entry; to add one, append a new key with a fresh crontab.
celery_app.conf.beat_schedule = {
    "ingest-be-kbo-nightly": {
        "task": "packages.ingestion.tasks.ingest_source_task",
        "schedule": crontab(hour=2, minute=0),
        "args": ("packages.ingestion.sources.be_kbo:BEKboSource",),
    },
    "ingest-ua-yedr-nightly": {
        "task": "packages.ingestion.tasks.ingest_source_task",
        "schedule": crontab(hour=2, minute=15),
        "args": ("packages.ingestion.sources.ua_yedr:UAYedrSource",),
    },
    "ingest-lv-ur-nightly": {
        "task": "packages.ingestion.tasks.ingest_source_task",
        "schedule": crontab(hour=2, minute=30),
        "args": ("packages.ingestion.sources.lv_ur:LVUrSource",),
    },
    "ingest-il-ckan-nightly": {
        "task": "packages.ingestion.tasks.ingest_source_task",
        "schedule": crontab(hour=2, minute=45),
        "args": ("packages.ingestion.sources.il_ckan:ILCkanSource",),
    },
}
