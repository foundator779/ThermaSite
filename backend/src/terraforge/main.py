from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from terraforge.api import router
from terraforge.audit import GemmaAuditService
from terraforge.auth import AuthStore
from terraforge.auth import router as auth_router
from terraforge.media import MediaService
from terraforge.observability import EventPublisher, configure_tracing
from terraforge.orchestration import ResearchCoordinator, WorkflowDispatcher
from terraforge.persistence import ArtifactStore, MediaJobStore, MissionStore, RunStore
from terraforge.screening import ScreeningService, ScreeningStore
from terraforge.screening import router as screening_router
from terraforge.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.runs = RunStore(settings)
    app.state.missions = MissionStore(settings)
    app.state.artifacts = ArtifactStore(settings)
    app.state.media_jobs = MediaJobStore(settings)
    app.state.publisher = EventPublisher(settings)
    app.state.auth = AuthStore(settings)
    await app.state.auth.initialize()
    app.state.screenings = ScreeningStore(settings)
    app.state.gemma_audits = GemmaAuditService(settings)
    app.state.media = MediaService(
        settings,
        app.state.runs,
        app.state.artifacts,
        app.state.missions,
        app.state.media_jobs,
    )
    app.state.coordinator = ResearchCoordinator(
        settings,
        app.state.runs,
        app.state.missions,
        app.state.artifacts,
        app.state.publisher,
        app.state.gemma_audits,
        app.state.media,
    )
    app.state.dispatcher = WorkflowDispatcher(settings, app.state.runs, app.state.coordinator)
    app.state.briefings = app.state.media
    app.state.tasks = app.state.dispatcher.tasks
    app.state.screening_service = ScreeningService(
        settings,
        app.state.screenings,
        app.state.artifacts,
        app.state.publisher,
    )
    if settings.terraforge_process_role in {"all", "workflow"}:
        await app.state.dispatcher.resume_stale()
    if settings.terraforge_process_role in {"all", "media"}:
        await app.state.briefings.resume_stale()
    yield
    await app.state.screening_service.shutdown()
    await app.state.briefings.shutdown()
    await app.state.dispatcher.shutdown()


app = FastAPI(
    title="ThermaSite API",
    version="0.1.0",
    description="Agentic, evidence-linked data-center site screening over REST and SSE.",
    lifespan=lifespan,
)
settings = get_settings()
configure_tracing(app, settings)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials="*" not in settings.cors_origins,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Content-Type", "Last-Event-ID", "Authorization"],
)
app.include_router(router)
app.include_router(screening_router)
app.include_router(auth_router)


def thermasite_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    visible = (
        "/api/v1/auth",
        "/api/v1/screenings",
        "/api/v1/site-catalog",
        "/api/v1/readyz",
        "/api/v1/healthz",
    )
    schema["paths"] = {
        path: contract for path, contract in schema["paths"].items() if path.startswith(visible)
    }
    app.openapi_schema = schema
    return schema


app.openapi = thermasite_openapi


@app.exception_handler(Exception)
async def unhandled_error(_: Request, exc: Exception):
    logging.getLogger("terraforge").exception("Unhandled API exception")
    message = (
        str(exc)
        if settings.terraforge_env not in {"staging", "production"}
        else "An unexpected server error occurred."
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": message,
                "retryable": False,
                "details": {},
            }
        },
    )


@app.get("/")
async def root():
    return {"service": "ThermaSite", "docs": "/docs", "health": "/api/v1/healthz"}
