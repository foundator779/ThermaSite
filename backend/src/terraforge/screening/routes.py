from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

from terraforge.auth import CurrentUser

from .catalog import CATALOG_VERSION, list_catalog
from .fortyguard import FortyGuardError
from .models import (
    CreateScreeningResponse,
    RescoreRequest,
    ResourceEstimate,
    ResourceEstimatorRequest,
    ScreeningRecord,
    ScreeningRequest,
    ScreeningStatus,
)

router = APIRouter(prefix="/api/v1")


@router.get("/site-catalog")
async def site_catalog():
    return {"version": CATALOG_VERSION, "sites": list_catalog()}


@router.post(
    "/screenings",
    response_model=CreateScreeningResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_screening(
    payload: ScreeningRequest,
    request: Request,
    user: CurrentUser,
):
    if not request.app.state.screening_service.fortyguard.ready:
        raise HTTPException(503, "FORTYGUARD_API_KEY is not configured")
    record = ScreeningRecord(request=payload, owner_id=user.id)
    await request.app.state.screenings.create(record)
    await request.app.state.screening_service.emit(
        record.id,
        "Screening Coordinator",
        "screening.created",
        "Created a durable ThermaSite screening and queued the agentic workflow.",
    )
    await request.app.state.screening_service.start(record)
    return CreateScreeningResponse(screening_id=record.id, status=record.status)


@router.get("/screenings", response_model=list[ScreeningRecord])
async def list_screenings(request: Request, user: CurrentUser):
    return await request.app.state.screenings.list(owner_id=user.id)


@router.get("/screenings/{screening_id}", response_model=ScreeningRecord)
async def get_screening(
    screening_id: UUID,
    request: Request,
    user: CurrentUser,
):
    record = await request.app.state.screenings.get(screening_id)
    if record is None or record.owner_id != user.id:
        raise HTTPException(404, "ThermaSite screening was not found")
    return record


@router.post("/screenings/{screening_id}/rescore", response_model=ScreeningRecord)
async def rescore_screening(
    screening_id: UUID,
    payload: RescoreRequest,
    request: Request,
    user: CurrentUser,
):
    record = await get_screening(screening_id, request, user)
    if record.status != ScreeningStatus.COMPLETED:
        raise HTTPException(409, "Only a completed screening can be rescored")
    return await request.app.state.screening_service.rescore(record, payload)


@router.post(
    "/screenings/{screening_id}/estimate",
    response_model=ResourceEstimate,
)
async def estimate_screening_resources(
    screening_id: UUID,
    payload: ResourceEstimatorRequest,
    request: Request,
    user: CurrentUser,
):
    record = await get_screening(screening_id, request, user)
    if record.status != ScreeningStatus.COMPLETED:
        raise HTTPException(409, "Resource estimates require a completed screening")
    if not request.app.state.screening_service.fortyguard.ready:
        raise HTTPException(503, "FORTYGUARD_API_KEY is not configured")
    try:
        return await request.app.state.screening_service.estimate_resources(record, payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except FortyGuardError as exc:
        raise HTTPException(exc.status_code or 502, str(exc)) from exc


@router.post("/screenings/{screening_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_screening(
    screening_id: UUID,
    request: Request,
    user: CurrentUser,
):
    record = await get_screening(screening_id, request, user)
    record.cancel_requested = True
    task = request.app.state.screening_service.tasks.get(screening_id)
    if task and not task.done():
        task.cancel()
    await request.app.state.screenings.save(record)
    return {"screening_id": screening_id, "status": "CANCELLING"}


@router.get("/screenings/{screening_id}/events")
async def stream_screening_events(
    screening_id: UUID,
    request: Request,
    user: CurrentUser,
):
    record = await get_screening(screening_id, request, user)
    known = 0
    last_event_id = request.headers.get("last-event-id")
    if last_event_id:
        for index, event in enumerate(record.events):
            if str(event.id) == last_event_id:
                known = index + 1
                break

    async def generate():
        nonlocal known
        while not await request.is_disconnected():
            current = await request.app.state.screenings.wait_for_events(
                screening_id, known, timeout=12
            )
            if current is None:
                break
            while known < len(current.events):
                event = current.events[known]
                known += 1
                yield f"id: {event.id}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n"
            if current.status in {
                ScreeningStatus.COMPLETED,
                ScreeningStatus.FAILED,
                ScreeningStatus.CANCELLED,
            } and known >= len(current.events):
                break
            yield ": keep-alive\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get("/screenings/{screening_id}/artifacts/{artifact_id}")
async def get_screening_artifact(
    screening_id: UUID,
    artifact_id: UUID,
    request: Request,
    user: CurrentUser,
):
    record = await get_screening(screening_id, request, user)
    artifact = next((item for item in record.artifacts if item.id == artifact_id), None)
    if artifact is None:
        raise HTTPException(404, "Screening artifact was not found")
    if artifact.uri.startswith("file://"):
        path = Path(artifact.uri.removeprefix("file://"))
        return FileResponse(
            path,
            media_type=artifact.content_type,
            filename=path.name,
            content_disposition_type="attachment",
        )
    if artifact.uri.startswith("gs://"):
        from datetime import timedelta

        from google.cloud import storage

        bucket_name, blob_name = artifact.uri.removeprefix("gs://").split("/", 1)
        url = (
            storage.Client()
            .bucket(bucket_name)
            .blob(blob_name)
            .generate_signed_url(expiration=timedelta(minutes=10), method="GET")
        )
        return RedirectResponse(url, status_code=307)
    raise HTTPException(500, "Unsupported artifact URI")
