from __future__ import annotations

import base64
import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse

from terraforge.connectors.sentinel import sample_grid
from terraforge.contracts.models import (
    CreateBriefingVideoResponse,
    CreateMonitoringMissionRequest,
    CreateMonitoringMissionResponse,
    CreateRunRequest,
    CreateRunResponse,
    EvidenceChain,
    EvidenceLink,
    EvidenceNode,
    MissionCheckStatus,
    MissionStatus,
    ModelUsageRecord,
    ModelUsageResponse,
    MonitoringAlert,
    MonitoringCadencePreset,
    MonitoringIndicatorOption,
    MonitoringMission,
    MonitoringPolicyOptions,
    RunRecord,
    RunStatus,
    RunSummary,
    UpdateMonitoringMissionRequest,
    VegetationAnalysis,
    utc_now,
)
from terraforge.knowledge import DATASETS, REGISTRY_VERSION
from terraforge.monitoring import (
    INDICATORS,
    build_thresholds,
    build_trigger_directions,
    default_indicator_keys,
)
from terraforge.observability import deliver_webhook

router = APIRouter(prefix="/api/v1")


def services(request: Request):
    return request.app.state.runs, request.app.state.coordinator, request.app.state.tasks


def verify_internal_request(request: Request) -> None:
    settings = request.app.state.settings
    if not settings.cloud_enabled:
        return
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Internal workflow authentication is required")
    try:
        from google.auth.transport.requests import Request as GoogleRequest
        from google.oauth2 import id_token

        audience = str(request.base_url).rstrip("/")
        claims = id_token.verify_oauth2_token(
            authorization.removeprefix("Bearer "), GoogleRequest(), audience=audience
        )
    except Exception as exc:
        raise HTTPException(401, "Internal workflow token was rejected") from exc
    if settings.internal_invoker_email and claims.get("email") != settings.internal_invoker_email:
        raise HTTPException(403, "Internal workflow caller is not authorized")


async def queue_monitoring_check(mission: MonitoringMission, request: Request) -> RunRecord:
    runs, coordinator, _ = services(request)
    if mission.status != MissionStatus.ACTIVE:
        raise HTTPException(409, "Monitoring mission is paused")
    if not coordinator.gemini_ready:
        raise HTTPException(503, "GOOGLE_API_KEY is not configured")
    if any(
        check.status in {MissionCheckStatus.QUEUED, MissionCheckStatus.RUNNING}
        for check in mission.checks
    ):
        raise HTTPException(409, "A monitoring check is already running")
    target_end_year = max(
        mission.last_observation_end.year if mission.last_observation_end else 0,
        utc_now().year - 1,
    )
    monitoring_query = mission.query
    if mission.rolling_window:
        monitoring_query += (
            f"\nMonitoring update: preserve the original baseline start and extend the "
            f"analysis through the latest complete calendar year, {target_end_year}."
        )
    record = RunRecord(
        user_query=monitoring_query,
        monitoring_mission_id=mission.id,
        monitoring_baseline_run_id=mission.baseline_run_id,
        study_area=mission.study_area,
    )
    claimed = await request.app.state.missions.begin_check(mission.id, record.id)
    if not claimed:
        raise HTTPException(409, "A monitoring check is already leased by another worker")
    await runs.create(record)
    await coordinator.emit(
        record.id,
        "MonitoringAgent",
        "monitoring.check.started",
        f"Started a repeatable evidence check for ‘{mission.name}’.",
        mission_id=str(mission.id),
        previous_run_id=str(mission.latest_run_id),
    )
    await request.app.state.dispatcher.enqueue(record.id, reason="monitoring.check")
    return record


@router.post("/runs", response_model=CreateRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_run(payload: CreateRunRequest, request: Request):
    runs, coordinator, _ = services(request)
    if not coordinator.gemini_ready:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "GOOGLE_API_KEY is not configured; Gemini research agents cannot run",
        )
    record = RunRecord(
        user_query=payload.query,
        demo_fault=payload.demo_fault,
        study_area=payload.study_area,
    )
    await runs.create(record)
    await coordinator.emit(
        record.id,
        "ResearchCoordinator",
        "run.created",
        "Created a durable research run and queued autonomous execution.",
    )
    await request.app.state.dispatcher.enqueue(record.id)
    return CreateRunResponse(run_id=record.id, status=RunStatus.CREATED)


@router.post("/internal/workflow/dispatch")
async def dispatch_workflow(payload: dict, request: Request):
    """Authenticated Pub/Sub push target; Cloud Run IAM rejects unauthenticated callers."""
    verify_internal_request(request)
    try:
        if "message" in payload:
            encoded = payload["message"]["data"]
            message = json.loads(base64.b64decode(encoded).decode())
        else:
            message = payload
        run_id = UUID(message["run_id"])
        dispatch_id = str(message["dispatch_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "Invalid workflow dispatch envelope") from exc
    claimed = await request.app.state.dispatcher.dispatch(run_id, dispatch_id)
    if not claimed:
        record = await request.app.state.runs.get(run_id)
        if record and record.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return {
                "accepted": False,
                "terminal": True,
                "run_id": str(run_id),
                "dispatch_id": dispatch_id,
            }
        raise HTTPException(409, "Workflow lease is active; Pub/Sub should retry delivery")
    return {"accepted": claimed, "run_id": str(run_id), "dispatch_id": dispatch_id}


@router.post("/internal/media/dispatch")
async def dispatch_media(payload: dict, request: Request):
    """Authenticated Pub/Sub push target for durable Veo and Lyria jobs."""
    verify_internal_request(request)
    try:
        message = (
            json.loads(base64.b64decode(payload["message"]["data"]).decode())
            if "message" in payload
            else payload
        )
        job_id = UUID(message["job_id"])
        dispatch_id = str(message["dispatch_id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "Invalid media dispatch envelope") from exc
    accepted = await request.app.state.media.dispatch(job_id, dispatch_id)
    if not accepted:
        job = await request.app.state.media_jobs.get(job_id)
        if job and job.status.value == "COMPLETED":
            return {"accepted": False, "terminal": True, "job_id": str(job_id)}
        raise HTTPException(409, "Media job was not completed; request redelivery")
    return {"accepted": True, "job_id": str(job_id), "dispatch_id": dispatch_id}


@router.get("/runs", response_model=list[RunSummary])
async def list_runs(request: Request):
    runs, _, _ = services(request)
    records = await runs.list()
    return [
        RunSummary(
            id=record.id,
            status=record.status,
            created_at=record.created_at,
            updated_at=record.updated_at,
            user_query=record.user_query,
            current_step=record.current_step,
            progress=record.progress,
            selected_dataset_count=len(record.selected_datasets),
            artifact_count=len(record.artifacts),
            final_summary=record.final_summary,
            error=record.error,
            monitoring_mission_id=record.monitoring_mission_id,
        )
        for record in records
    ]


@router.get("/runs/{run_id}", response_model=RunRecord)
async def get_run(run_id: UUID, request: Request):
    runs, _, _ = services(request)
    record = await runs.get(run_id)
    if record is None:
        raise HTTPException(
            404,
            detail={
                "error": {
                    "code": "RUN_NOT_FOUND",
                    "message": "Research run was not found",
                    "retryable": False,
                    "details": {},
                }
            },
        )
    response = record.model_copy(deep=True)
    for artifact in response.artifacts:
        artifact.download_url = f"/api/v1/runs/{run_id}/artifacts/{artifact.id}"
    if response.vegetation:
        for layer in response.vegetation.layers:
            layer.download_url = f"/api/v1/runs/{run_id}/artifacts/{layer.artifact_id}"
    return response


@router.get("/runs/{run_id}/model-usage", response_model=ModelUsageResponse)
async def get_model_usage(run_id: UUID, request: Request):
    record = await request.app.state.runs.get(run_id)
    if record is None:
        raise HTTPException(404, "Research run was not found")
    settings = request.app.state.settings
    configured = [
        ("Gemini", settings.gemini_model, "ADK planning, scientific review, and operational decisions"),
        ("Gemma", settings.gemma_model, "Independent evidence and external-dispatch audit"),
        ("Veo", settings.veo_model, "Illustrative field video; not scientific evidence"),
        ("Lyria", settings.lyria_model, "Opt-in incident audio; not scientific evidence"),
    ]
    models = list(record.model_usage)
    for family, model, purpose in configured:
        if not any(item.family == family for item in models):
            models.append(ModelUsageRecord(family=family, model=model, purpose=purpose, status="configured"))
    return ModelUsageResponse(run_id=run_id, models=models)


@router.post(
    "/runs/{run_id}/briefing-video",
    response_model=CreateBriefingVideoResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_briefing_video(run_id: UUID, request: Request):
    runs, _, _ = services(request)
    record = await runs.get(run_id)
    if record is None:
        raise HTTPException(404, "Research run was not found")
    if record.status != RunStatus.COMPLETED or not record.final_summary:
        raise HTTPException(409, "A briefing video requires a completed research run")
    validated = record.scientific_review is not None or any(
        event.type == "scientific_validation.completed" for event in record.events
    )
    if not validated:
        raise HTTPException(409, "A briefing video requires a scientifically validated finding")
    briefing_service = request.app.state.briefings
    if not briefing_service.ready:
        raise HTTPException(503, "Veo is not configured with a Gemini API key and model")
    record = await briefing_service.enqueue(run_id)
    return CreateBriefingVideoResponse(
        run_id=record.id,
        status=record.briefing_video_status,
        model=request.app.state.settings.veo_model,
    )


@router.get(
    "/runs/{run_id}/monitoring-policy/options",
    response_model=MonitoringPolicyOptions,
)
async def get_monitoring_policy_options(run_id: UUID, request: Request):
    runs, _, _ = services(request)
    record = await runs.get(run_id)
    if record is None:
        raise HTTPException(404, "Research run was not found")
    if record.status != RunStatus.COMPLETED or not record.research_spec:
        raise HTTPException(409, "Monitoring options require a completed, validated research run")

    recommended_keys = default_indicator_keys(record.research_spec.habitat_type)
    available: list[MonitoringIndicatorOption] = []
    for key, definition in INDICATORS.items():
        value = record.metrics.get(str(definition["metric"]))
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        available.append(
            MonitoringIndicatorOption(
                key=key,
                label=str(definition["label"]),
                detail=str(definition["detail"]),
                metric=str(definition["metric"]),
                unit=str(definition["unit"]),
                step=float(definition["step"]),
                current_value=float(value),
                thresholds={
                    sensitivity: float(threshold)
                    for sensitivity, threshold in definition["thresholds"].items()
                },
                default_direction=definition["default_direction"],
                recommended=key in recommended_keys,
            )
        )
    default_keys = [item.key for item in available if item.recommended]
    if not default_keys and available:
        default_keys = [available[0].key]
        available[0].recommended = True
    return MonitoringPolicyOptions(
        run_id=record.id,
        available_indicators=available,
        cadence_presets=[
            MonitoringCadencePreset(label="Daily", days=1),
            MonitoringCadencePreset(label="Weekly", days=7),
            MonitoringCadencePreset(label="Monthly", days=30),
            MonitoringCadencePreset(label="Quarterly", days=90),
        ],
        default_indicator_keys=default_keys,
    )


@router.get("/runs/{run_id}/events")
async def stream_events(run_id: UUID, request: Request):
    runs, _, _ = services(request)
    record = await runs.get(run_id)
    if record is None:
        raise HTTPException(404, "Research run was not found")
    last_event_id = request.headers.get("last-event-id")
    known = 0
    if last_event_id:
        for index, event in enumerate(record.events):
            if str(event.id) == last_event_id:
                known = index + 1
                break

    async def generate():
        nonlocal known
        while not await request.is_disconnected():
            current = await runs.wait_for_events(run_id, known, timeout=12)
            if current is None:
                break
            while known < len(current.events):
                event = current.events[known]
                known += 1
                yield f"id: {event.id}\nevent: {event.type}\ndata: {event.model_dump_json()}\n\n"
            if current.status in {
                RunStatus.COMPLETED,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
            } and known >= len(current.events):
                break
            yield ": keep-alive\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get("/runs/{run_id}/artifacts")
async def list_artifacts(run_id: UUID, request: Request):
    record = await get_run(run_id, request)
    return record.artifacts


@router.get("/runs/{run_id}/vegetation", response_model=VegetationAnalysis)
async def get_vegetation_analysis(run_id: UUID, request: Request):
    record = await get_run(run_id, request)
    if record.vegetation is None:
        raise HTTPException(404, "Vegetation analysis is not available for this run")
    return record.vegetation


@router.get("/runs/{run_id}/vegetation/sample")
async def get_vegetation_sample(
    run_id: UUID,
    latitude: float,
    longitude: float,
    request: Request,
):
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise HTTPException(422, "Latitude or longitude is outside WGS84 bounds")
    runs, _, _ = services(request)
    record = await runs.get(run_id)
    if record is None:
        raise HTTPException(404, "Research run was not found")
    if record.vegetation is None or record.vegetation.sample_grid_artifact_id is None:
        raise HTTPException(404, "Vegetation sampling data is not available for this run")
    artifact = next(
        (
            item
            for item in record.artifacts
            if item.id == record.vegetation.sample_grid_artifact_id
        ),
        None,
    )
    if artifact is None:
        raise HTTPException(404, "Vegetation sampling artifact was not found")
    try:
        return sample_grid(
            request.app.state.artifacts.read_bytes(artifact.uri), longitude, latitude
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/runs/{run_id}/evidence", response_model=EvidenceChain)
async def get_evidence_chain(run_id: UUID, request: Request):
    runs, _, _ = services(request)
    record = await runs.get(run_id)
    if record is None:
        raise HTTPException(404, "Research run was not found")
    nodes: list[EvidenceNode] = [
        EvidenceNode(
            id="claim:final",
            kind="claim",
            label="Validated finding" if record.final_summary else "Finding pending",
            detail=record.final_summary or "A final claim has not been validated yet.",
        )
    ]
    links: list[EvidenceLink] = []
    metric_labels = {
        "regional_temperature_trend_c_per_decade": "Regional temperature trend",
        "regional_temperature_p_value": "Trend significance",
        "sea_ice_trend_mkm2_per_decade": "Sea-ice trend",
        "temperature_sea_ice_correlation": "Temperature–sea-ice association",
        "water_level_trend_ft_per_decade": "Wetland water-level trend",
        "latest_water_level_anomaly_ft": "Recent water-level anomaly",
        "dry_month_fraction_change": "Dry-month fraction change",
        "precipitation_water_level_correlation": "Precipitation–water-level association",
        "climate_source_agreement": "NOAA–NASA climate agreement",
    }
    metric_labels.update(
        {
            "regional_precipitation_trend_mm_per_decade": "Regional precipitation trend",
            "recent_temperature_anomaly_c": "Recent temperature anomaly",
            "recent_precipitation_anomaly_pct": "Recent precipitation anomaly",
            "observed_species_count": "Documented species richness",
            "recent_fire_detection_count": "Recent active-fire detections",
            "nwi_wetland_feature_count": "Intersecting NWI wetland features",
            "ecological_evidence_available_count": "Available ecological evidence roles",
            "vegetation_current_ndvi": "Current Sentinel-2 NDVI",
            "vegetation_baseline_ndvi": "Seasonal baseline NDVI",
            "vegetation_ndvi_anomaly": "NDVI seasonal anomaly",
            "vegetation_current_ndmi": "Current Sentinel-2 NDMI",
            "vegetation_baseline_ndmi": "Seasonal baseline NDMI",
            "vegetation_ndmi_anomaly": "NDMI seasonal anomaly",
            "vegetation_stressed_area_pct": "Stressed vegetation area",
            "vegetation_valid_coverage_pct": "Valid satellite coverage",
        }
    )
    for metric, label in metric_labels.items():
        value = record.metrics.get(metric)
        if not isinstance(value, (int, float)):
            continue
        node_id = f"metric:{metric}"
        nodes.append(
            EvidenceNode(
                id=node_id,
                kind="metric",
                label=label,
                detail=f"Structured execution output: {value:.4g}",
            )
        )
        links.append(
            EvidenceLink(source="claim:final", target=node_id, relationship="supported by")
        )

    for dataset in record.selected_datasets:
        node_id = f"dataset:{dataset.dataset_id}"
        nodes.append(
            EvidenceNode(
                id=node_id,
                kind="dataset",
                label=dataset.name,
                detail=f"{dataset.provider} · {dataset.data_role}",
                uri=str(dataset.documentation_url),
            )
        )
        links.append(
            EvidenceLink(
                source="transformation:harmonization",
                target=node_id,
                relationship="uses",
            )
        )

    if record.harmonization:
        harmonization = record.harmonization
        nodes.append(
            EvidenceNode(
                id="transformation:harmonization",
                kind="transformation",
                label="Cross-dataset harmonization",
                detail=(
                    f"Aligned {harmonization.paired_sample_count} observations from "
                    f"{harmonization.overlap_start} through {harmonization.overlap_end}."
                ),
                uri=harmonization.artifact_uri,
            )
        )
        for metric in metric_labels:
            if isinstance(record.metrics.get(metric), (int, float)):
                links.append(
                    EvidenceLink(
                        source=f"metric:{metric}",
                        target="transformation:harmonization",
                        relationship="computed from",
                    )
                )

    if record.vegetation:
        nodes.append(
            EvidenceNode(
                id="transformation:sentinel-vegetation",
                kind="transformation",
                label="Deterministic Sentinel-2 vegetation processing",
                detail=(
                    f"Cloud-masked {record.vegetation.current_scene_count} current and "
                    f"{record.vegetation.baseline_scene_count} same-season baseline acquisitions "
                    f"at {record.vegetation.resolution_m:g} m resolution."
                ),
            )
        )
        links.append(
            EvidenceLink(
                source="transformation:sentinel-vegetation",
                target="dataset:sentinel-2-l2a-vegetation-user-area",
                relationship="uses",
            )
        )
        for metric in metric_labels:
            if metric.startswith("vegetation_") and isinstance(record.metrics.get(metric), (int, float)):
                links.append(
                    EvidenceLink(
                        source=f"metric:{metric}",
                        target="transformation:sentinel-vegetation",
                        relationship="computed from",
                    )
                )

    code_artifact = next(
        (item for item in record.artifacts if "Repaired" in item.name),
        next((item for item in record.artifacts if item.type == "code"), None),
    )
    if code_artifact:
        nodes.append(
            EvidenceNode(
                id="code:analysis",
                kind="code",
                label=code_artifact.name,
                detail="Generated from the validated analysis plan and executed in the restricted runtime.",
                uri=f"/api/v1/runs/{run_id}/artifacts/{code_artifact.id}",
                sha256=code_artifact.sha256,
            )
        )
        for metric in metric_labels:
            if isinstance(record.metrics.get(metric), (int, float)):
                links.append(
                    EvidenceLink(
                        source=f"metric:{metric}",
                        target="code:analysis",
                        relationship="produced by",
                    )
                )

    validation = next(
        (event for event in record.events if event.type == "scientific_validation.completed"), None
    )
    if validation:
        nodes.append(
            EvidenceNode(
                id="validation:scientific",
                kind="validation",
                label="Scientific validation passed",
                detail=validation.message,
            )
        )
        links.append(
            EvidenceLink(
                source="claim:final",
                target="validation:scientific",
                relationship="checked by",
            )
        )

    for index, disagreement in enumerate(record.evidence_disagreements):
        node_id = f"validation:disagreement:{index}"
        nodes.append(
            EvidenceNode(
                id=node_id,
                kind="validation",
                label=f"Evidence disagreement · {disagreement.get('indicator', 'indicator')}",
                detail=str(disagreement.get("message", "Cross-source disagreement recorded.")),
            )
        )
        links.append(
            EvidenceLink(
                source="claim:final", target=node_id, relationship="confidence constrained by"
            )
        )

    if record.operational_impact:
        nodes.append(
            EvidenceNode(
                id="validation:operational-impact",
                kind="validation",
                label="Operational work eliminated",
                detail=(
                    f"Automated {record.operational_impact.get('workflow_steps_automated', 0)} "
                    f"workflow steps in {record.operational_impact.get('runtime_seconds', 0)} seconds; "
                    f"estimated {record.operational_impact.get('estimated_manual_hours_saved', 0)} "
                    "manual analyst hours avoided."
                ),
            )
        )
        links.append(
            EvidenceLink(
                source="claim:final",
                target="validation:operational-impact",
                relationship="produced through",
            )
        )

    bundle = next((item for item in record.artifacts if item.type == "bundle"), None)
    if bundle:
        nodes.append(
            EvidenceNode(
                id="artifact:bundle",
                kind="artifact",
                label="Reproducibility package",
                detail="Sources, hashes, transformations, code, metrics, and methods packaged together.",
                uri=f"/api/v1/runs/{run_id}/artifacts/{bundle.id}",
                sha256=bundle.sha256,
            )
        )
        links.append(
            EvidenceLink(
                source="artifact:bundle",
                target="claim:final",
                relationship="packages evidence for",
            )
        )
    return EvidenceChain(
        run_id=run_id,
        claim=record.final_summary or "Finding pending",
        nodes=nodes,
        links=links,
        validation_status="validated" if validation and record.final_summary else "incomplete",
    )


@router.get("/runs/{run_id}/artifacts/{artifact_id}")
async def get_artifact(run_id: UUID, artifact_id: UUID, request: Request):
    runs, _, _ = services(request)
    record = await runs.get(run_id)
    if record is None:
        raise HTTPException(404, "Research run was not found")
    artifact = next((item for item in record.artifacts if item.id == artifact_id), None)
    if artifact is None:
        raise HTTPException(404, "Artifact was not found")
    if artifact.uri.startswith("file://"):
        artifact_path = Path(artifact.uri.removeprefix("file://"))
        filename = artifact.name
        if artifact_path.suffix and not Path(filename).suffix:
            filename = f"{filename}{artifact_path.suffix}"
        return FileResponse(
            artifact_path,
            media_type=artifact.content_type,
            filename=filename,
            content_disposition_type="inline" if artifact.type == "video" else "attachment",
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
        return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    raise HTTPException(500, "Unsupported artifact URI")


@router.post("/runs/{run_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(run_id: UUID, request: Request):
    runs, _, tasks = services(request)
    record = await runs.get(run_id)
    if record is None:
        raise HTTPException(404, "Research run was not found")
    task = tasks.get(run_id)
    record.cancel_requested = True
    await runs.save(record)
    if task and not task.done():
        task.cancel()
        return {"run_id": run_id, "status": "CANCELLING"}
    return {"run_id": run_id, "status": "CANCELLING"}


@router.post(
    "/missions",
    response_model=CreateMonitoringMissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_monitoring_mission(payload: CreateMonitoringMissionRequest, request: Request):
    runs, _, _ = services(request)
    source = await runs.get(payload.source_run_id)
    if source is None:
        raise HTTPException(404, "Source research run was not found")
    if source.status != RunStatus.COMPLETED or not source.research_spec or not source.metrics:
        raise HTTPException(409, "Only a completed, validated research run can become a mission")
    missions = request.app.state.missions
    existing = next(
        (
            mission
            for mission in await missions.list()
            if mission.baseline_run_id == source.id and mission.status == MissionStatus.ACTIVE
        ),
        None,
    )
    if existing:
        return CreateMonitoringMissionResponse(mission_id=existing.id, status=existing.status)
    try:
        indicator_keys, thresholds = build_thresholds(
            source.research_spec.habitat_type,
            payload.sensitivity,
            payload.indicator_keys,
            source.metrics,
            payload.metric_thresholds,
        )
        trigger_directions = build_trigger_directions(
            indicator_keys,
            payload.trigger_directions,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    mission = MonitoringMission(
        name=payload.name or f"{source.research_spec.anchor_place} habitat watch",
        baseline_run_id=source.id,
        latest_run_id=source.id,
        query=source.user_query,
        region=source.research_spec.region,
        habitat=source.research_spec.habitat_type,
        objective=payload.objective,
        cadence_days=payload.cadence_days,
        sensitivity=payload.sensitivity,
        indicator_keys=indicator_keys,
        next_check_at=source.updated_at + timedelta(days=payload.cadence_days),
        metric_thresholds=thresholds,
        trigger_directions=trigger_directions,
        run_ids=[source.id],
        last_observation_end=source.research_spec.end_date,
        notification_enabled=payload.notification_enabled,
        audio_alert_enabled=payload.audio_alert_enabled,
        study_area=source.study_area,
    )
    await missions.create(mission)
    source.monitoring_mission_id = mission.id
    source.monitoring_baseline_run_id = source.id
    await runs.save(source)
    await request.app.state.coordinator.emit(
        source.id,
        "MonitoringAgent",
        "monitoring.mission.created",
        f"Converted this investigation into the active mission ‘{mission.name}’.",
        mission_id=str(mission.id),
        cadence_days=mission.cadence_days,
        sensitivity=mission.sensitivity,
        indicators=mission.indicator_keys,
        thresholds=mission.metric_thresholds,
        trigger_directions=mission.trigger_directions,
    )
    return CreateMonitoringMissionResponse(mission_id=mission.id, status=mission.status)


@router.get("/missions", response_model=list[MonitoringMission])
async def list_monitoring_missions(request: Request):
    return await request.app.state.missions.list()


@router.get("/missions/{mission_id}", response_model=MonitoringMission)
async def get_monitoring_mission(mission_id: UUID, request: Request):
    mission = await request.app.state.missions.get(mission_id)
    if mission is None:
        raise HTTPException(404, "Monitoring mission was not found")
    return mission


@router.post(
    "/missions/{mission_id}/alerts/{alert_id}/retry-delivery",
    response_model=MonitoringAlert,
)
async def retry_monitoring_alert_delivery(
    mission_id: UUID, alert_id: UUID, request: Request
):
    mission = await request.app.state.missions.get(mission_id)
    if mission is None:
        raise HTTPException(404, "Monitoring mission was not found")
    alert = next((item for item in mission.alerts if item.id == alert_id), None)
    if alert is None:
        raise HTTPException(404, "Monitoring incident was not found")
    webhook = request.app.state.settings.monitoring_webhook_url
    if alert.severity != "attention" or not mission.notification_enabled or not webhook:
        raise HTTPException(409, "This incident is not authorized for external delivery")
    run = await request.app.state.runs.get(alert.run_id)
    packet_artifact = next(
        (
            item
            for item in (run.artifacts if run else [])
            if item.id == alert.action_packet_artifact_id
        ),
        None,
    )
    packet_markdown = (
        request.app.state.artifacts.read_bytes(packet_artifact.uri).decode("utf-8")
        if packet_artifact
        else None
    )
    if run is None:
        raise HTTPException(409, "The incident research run is unavailable")
    dispatch_audit = await request.app.state.gemma_audits.audit_dispatch(
        run,
        title=alert.title,
        message=alert.message,
        field_actions=alert.field_actions,
        comparison_metrics=alert.comparison_metrics,
    )
    run.gemma_audits.append(dispatch_audit)
    await request.app.state.runs.save(run)
    if not dispatch_audit.dispatch_allowed:
        alert.delivery = {
            "status": "withheld_by_gemma",
            "message": "External delivery was withheld by the independent Gemma gate.",
            "audit_id": str(dispatch_audit.id),
        }
        await request.app.state.missions.save(mission)
        return alert
    alert.delivery = await deliver_webhook(
        webhook.get_secret_value(),
        {
            "event": "habiwatch.monitoring.incident",
            "mission_id": str(mission.id),
            "run_id": str(alert.run_id),
            "severity": alert.severity,
            "title": alert.title,
            "message": alert.message,
            "summary": run.final_summary if run else None,
            "field_tasks": [item.model_dump(mode="json") for item in alert.field_tasks],
            "action_packet": {
                "artifact_url": (
                    f"/api/v1/runs/{alert.run_id}/artifacts/{alert.action_packet_artifact_id}"
                    if alert.action_packet_artifact_id
                    else None
                ),
                "content_markdown": packet_markdown,
            },
        },
        idempotency_key=str(alert.id),
    )
    if alert.delivery.get("status") == "delivered":
        for task in alert.field_tasks:
            task.status = "dispatched"
    await request.app.state.missions.save(mission)
    return alert


@router.post(
    "/missions/{mission_id}/alerts/{alert_id}/audio/retry",
    response_model=MonitoringAlert,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_monitoring_alert_audio(mission_id: UUID, alert_id: UUID, request: Request):
    mission = await request.app.state.missions.get(mission_id)
    if mission is None:
        raise HTTPException(404, "Monitoring mission was not found")
    alert = next((item for item in mission.alerts if item.id == alert_id), None)
    if alert is None:
        raise HTTPException(404, "Monitoring incident was not found")
    if not mission.audio_alert_enabled:
        raise HTTPException(409, "AI-generated incident audio is disabled for this policy")
    if not request.app.state.media.lyria_ready:
        raise HTTPException(503, "Lyria is not configured")
    await request.app.state.media.enqueue_audio(mission.id, alert.id, alert.run_id)
    refreshed = await request.app.state.missions.get(mission.id)
    return next(item for item in refreshed.alerts if item.id == alert.id)


@router.patch("/missions/{mission_id}", response_model=MonitoringMission)
async def update_monitoring_mission(
    mission_id: UUID,
    payload: UpdateMonitoringMissionRequest,
    request: Request,
):
    missions = request.app.state.missions
    mission = await missions.get(mission_id)
    if mission is None:
        raise HTTPException(404, "Monitoring mission was not found")
    baseline = await request.app.state.runs.get(mission.baseline_run_id)
    if baseline is None or not baseline.research_spec:
        raise HTTPException(409, "Monitoring baseline run is unavailable")

    if payload.name is not None:
        mission.name = payload.name
    if payload.objective is not None:
        mission.objective = payload.objective
    if payload.cadence_days is not None:
        mission.cadence_days = payload.cadence_days
        mission.next_check_at = utc_now() + timedelta(days=payload.cadence_days)
    if payload.notification_enabled is not None:
        mission.notification_enabled = payload.notification_enabled
    if payload.audio_alert_enabled is not None:
        mission.audio_alert_enabled = payload.audio_alert_enabled
    if payload.status is not None:
        mission.status = payload.status

    sensitivity = payload.sensitivity or mission.sensitivity
    indicator_keys = (
        payload.indicator_keys if payload.indicator_keys is not None else mission.indicator_keys
    )
    if (
        payload.sensitivity is not None
        or payload.indicator_keys is not None
        or payload.metric_thresholds is not None
    ):
        try:
            indicator_keys, thresholds = build_thresholds(
                baseline.research_spec.habitat_type,
                sensitivity,
                indicator_keys,
                baseline.metrics,
                payload.metric_thresholds,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        mission.sensitivity = sensitivity
        mission.indicator_keys = indicator_keys
        mission.metric_thresholds = thresholds
    if payload.indicator_keys is not None or payload.trigger_directions is not None:
        direction_input = (
            payload.trigger_directions
            if payload.trigger_directions is not None
            else {
                key: value
                for key, value in mission.trigger_directions.items()
                if key in mission.indicator_keys
            }
        )
        try:
            mission.trigger_directions = build_trigger_directions(
                mission.indicator_keys,
                direction_input,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    await missions.save(mission)
    await request.app.state.coordinator.emit(
        mission.latest_run_id,
        "ADKOperationalActionAgent",
        "monitoring.policy.updated",
        f"Updated the monitoring policy for ‘{mission.name}’.",
        mission_status=mission.status,
        sensitivity=mission.sensitivity,
        indicators=mission.indicator_keys,
    )
    return mission


@router.post(
    "/missions/{mission_id}/check",
    response_model=CreateRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def check_monitoring_mission(mission_id: UUID, request: Request):
    mission = await request.app.state.missions.get(mission_id)
    if mission is None:
        raise HTTPException(404, "Monitoring mission was not found")
    record = await queue_monitoring_check(mission, request)
    return CreateRunResponse(run_id=record.id, status=RunStatus.CREATED)


@router.post("/missions/check-due", status_code=status.HTTP_202_ACCEPTED)
async def check_due_monitoring_missions(request: Request):
    verify_internal_request(request)
    queued: list[dict[str, str]] = []
    now = utc_now()
    for mission in await request.app.state.missions.list():
        running = any(
            check.status in {MissionCheckStatus.QUEUED, MissionCheckStatus.RUNNING}
            for check in mission.checks
        )
        if mission.status != MissionStatus.ACTIVE or mission.next_check_at > now or running:
            continue
        record = await queue_monitoring_check(mission, request)
        queued.append({"mission_id": str(mission.id), "run_id": str(record.id)})
    return {"queued": queued, "checked_at": now.isoformat()}


@router.get("/datasets")
async def datasets():
    return {"registry_version": REGISTRY_VERSION, "datasets": DATASETS}


@router.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "thermasite-api"}


@router.get("/readyz")
async def readyz(request: Request, verify_ai: bool = False):
    settings = request.app.state.settings
    coordinator = request.app.state.coordinator
    gemini_check: dict[str, object] = {
        "configured": coordinator.gemini_ready,
        "model": settings.gemini_model,
        "provider": "Gemini Developer API",
        "sdk": "Google GenAI SDK",
        "agent_framework": "Google ADK",
        "agents": ["Intake Agent", "Shortlist Agent", "Site Intelligence Agent", "Recommendation Agent"],
    }
    if verify_ai and coordinator.gemini_ready:
        try:
            gemini_check["connected_model"] = await coordinator.adk.check_connection()
            gemini_check["connection"] = "verified"
        except Exception as exc:  # noqa: BLE001 -- readiness reports provider failures
            gemini_check["connection"] = "failed"
            gemini_check["error"] = type(exc).__name__
    fortyguard_check: dict[str, object] = {
        "configured": settings.fortyguard_enabled,
        "provider": "FortyGuard Temperature API",
        "authentication": "backend api-key header",
        "aoi_limit_sq_mi": 10,
    }
    checks = {
        "api": True,
        "gemini": gemini_check,
        "fortyguard": fortyguard_check,
        "grounded_research": {
            "configured": coordinator.gemini_ready,
            "provider": "Gemini Google Search grounding",
            "cache_ttl_days": 7,
        },
        "persistence": "firestore" if settings.cloud_enabled else "local durable adapter",
        "authentication": {
            "configured": True,
            "sessions": "persistent hashed bearer sessions",
            "demo_account": True,
        },
        "artifact_storage": "cloud-storage"
        if settings.cloud_enabled
        else "local immutable adapter",
        "tracing": (
            "otlp"
            if settings.otel_exporter_otlp_endpoint
            else "cloud-trace"
            if settings.cloud_enabled
            else "local trace context"
        ),
    }
    ready = (
        coordinator.gemini_ready
        and settings.fortyguard_enabled
        and gemini_check.get("connection") != "failed"
    )
    return {
        "status": "ready" if ready else "configuration_required",
        "environment": settings.terraforge_env,
        "checks": checks,
    }
