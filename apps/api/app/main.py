"""FastAPI application entrypoint."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from apps.api.app.config import get_settings
from apps.api.app.db import init_db_if_needed
from apps.api.app.logging_setup import configure_logging
from apps.api.app.rate_limit import rate_limit_middleware
from apps.api.app.routes import router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        await init_db_if_needed()
    except Exception as exc:
        logger.warning("DB init skipped: %s — endpoints needing DB will fail.", exc)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="CreditLens API",
        version="0.1.0",
        description="B2B credit intelligence — registry data, financial filings, AI risk scoring.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(BaseHTTPMiddleware, dispatch=rate_limit_middleware)
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": "CreditLens API",
            "version": "0.1.0",
            "docs": "/docs",
            "health": "/api/healthz",
            "countries": "/api/countries",
        }

    return app


app = create_app()
