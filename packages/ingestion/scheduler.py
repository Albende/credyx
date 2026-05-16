"""Optional APScheduler entry point.

We use Celery + beat in production (see `celery_app.py`). APScheduler is
provided here as a lighter-weight alternative for local dev when running a
full Redis broker is overkill — call `start_beat()` from a script. Nothing
auto-starts on import.
"""
from __future__ import annotations

import logging

from packages.ingestion.tasks import ingest_source_task

logger = logging.getLogger(__name__)

# (cron_hour, cron_minute, source_class_path)
DEFAULT_SCHEDULE: list[tuple[int, int, str]] = [
    (2, 0, "packages.ingestion.sources.be_kbo:BEKboSource"),
    (2, 15, "packages.ingestion.sources.ua_yedr:UAYedrSource"),
    (2, 30, "packages.ingestion.sources.lv_ur:LVUrSource"),
    (2, 45, "packages.ingestion.sources.il_ckan:ILCkanSource"),
]


def start_beat(*, blocking: bool = True) -> object:
    """Boot APScheduler with the default nightly schedule.

    The scheduler is returned so callers in tests can shut it down. When
    `blocking=True` we use BlockingScheduler (suitable for `python -m`).
    """
    if blocking:
        from apscheduler.schedulers.blocking import BlockingScheduler

        scheduler = BlockingScheduler(timezone="UTC")
    else:
        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler(timezone="UTC")

    for hour, minute, source_path in DEFAULT_SCHEDULE:
        scheduler.add_job(
            ingest_source_task.delay,
            "cron",
            hour=hour,
            minute=minute,
            args=[source_path],
            id=f"ingest:{source_path}",
            replace_existing=True,
        )
        logger.info("scheduled %s at %02d:%02d UTC", source_path, hour, minute)
    scheduler.start()
    return scheduler


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    start_beat(blocking=True)
