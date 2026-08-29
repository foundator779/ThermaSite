from __future__ import annotations

import math
from datetime import UTC, date, datetime
from enum import StrEnum
from itertools import pairwise
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class RunStatus(StrEnum):
    CREATED = "CREATED"
    INTERPRETING = "INTERPRETING"
    DISCOVERING_DATA = "DISCOVERING_DATA"
    SELECTING_DATASETS = "SELECTING_DATASETS"
    ACQUIRING_DATA = "ACQUIRING_DATA"
    VALIDATING_DATA = "VALIDATING_DATA"
    HARMONIZING_DATA = "HARMONIZING_DATA"
    PLANNING_ANALYSIS = "PLANNING_ANALYSIS"
    GENERATING_CODE = "GENERATING_CODE"
    EXECUTING = "EXECUTING"
    REPAIRING = "REPAIRING"
    VALIDATING_OUTPUT = "VALIDATING_OUTPUT"
    GENERATING_REPORT = "GENERATING_REPORT"
    PACKAGING = "PACKAGING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BriefingVideoStatus(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    QUEUED = "QUEUED"
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class IncidentAudioStatus(StrEnum):
    NOT_REQUESTED = "NOT_REQUESTED"
    QUEUED = "QUEUED"
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class GemmaAuditScope(StrEnum):
    FINDING = "FINDING"
    DISPATCH = "DISPATCH"


class GemmaAuditVerdict(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"
    ERROR = "ERROR"


class MediaJobType(StrEnum):
    VEO_FIELD_BRIEFING = "VEO_FIELD_BRIEFING"
    LYRIA_INCIDENT_AUDIO = "LYRIA_INCIDENT_AUDIO"


class MediaJobStatus(StrEnum):
    QUEUED = "QUEUED"
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MissionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class MissionCheckStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MonitoringSensitivity(StrEnum):
    HIGH = "HIGH"
    BALANCED = "BALANCED"
    IMPORTANT_ONLY = "IMPORTANT_ONLY"


class MonitoringTriggerDirection(StrEnum):
    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    EITHER = "EITHER"


class WorkflowOperationStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class GeometrySpec(BaseModel):
    type: Literal["Point", "Polygon", "BBox"]
    coordinates: Any
    label: str | None = None


class StudyArea(BaseModel):
    shape: Literal["circle", "polygon"]
    geometry: GeometrySpec
    center: tuple[float, float]
    bbox: tuple[float, float, float, float]
    area_sq_mi: float = Field(gt=0, le=150)
    radius_miles: float | None = Field(default=None, gt=0)
    label: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def validate_geometry(self):
        if self.geometry.type != "Polygon":
            raise ValueError("A study area must be represented by a polygon geometry")
        if self.shape == "circle" and self.radius_miles is None:
            raise ValueError("Circle study areas require a radius")
        west, south, east, north = self.bbox
        if west >= east or south >= north:
            raise ValueError("Study area bounding box is invalid")
        longitude, latitude = self.center
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError("Study area center is outside WGS84 bounds")
        try:
            ring = self.geometry.coordinates[0]
            points = [
                (math.radians(float(point[0])), math.radians(float(point[1]))) for point in ring
            ]
        except (IndexError, TypeError, ValueError) as exc:
            raise ValueError("Study area polygon coordinates are invalid") from exc
        if len(points) < 4 or points[0] != points[-1]:
            raise ValueError(
                "Study area polygon must be a closed ring with at least three vertices"
            )
        radius = 6_378_137.0
        area_m2 = abs(
            sum(
                (longitude_two - longitude_one)
                * (2 + math.sin(latitude_one) + math.sin(latitude_two))
                for (longitude_one, latitude_one), (longitude_two, latitude_two) in pairwise(points)
            )
            * radius
            * radius
            / 2
        )
        computed_area_sq_mi = area_m2 / 2_589_988.110336
        if computed_area_sq_mi > 150.05:
            raise ValueError("Study area may not exceed 150 square miles")
        tolerance = max(0.25, computed_area_sq_mi * 0.05)
        if abs(computed_area_sq_mi - self.area_sq_mi) > tolerance:
            raise ValueError("Submitted study area does not match its polygon geometry")
        if self.shape == "circle" and self.radius_miles:
            radius_area = math.pi * self.radius_miles**2
            if abs(radius_area - self.area_sq_mi) > max(0.25, radius_area * 0.03):
                raise ValueError("Circle radius does not match its submitted area")
        return self


class ResearchSpecification(BaseModel):
    question: str
    variables: list[str]
    derived_metrics: list[str]
    anchor_place: str
    region: str
    start_date: date
    end_date: date
    analysis_intent: str
    required_data_roles: list[str]
    causal_claim_allowed: bool = False
    research_geometry: GeometrySpec
    habitat_type: str = "arctic_coastal"


class DatasetCandidate(BaseModel):
    dataset_id: str
    name: str
    provider: str
    match_score: float = Field(ge=0, le=1)
    variable_match: bool
    temporal_fit: bool
    spatial_fit: bool
    access_type: str
    temporal_resolution: str
    spatial_resolution: str
    rationale: str
    data_role: str
    documentation_url: HttpUrl
    warnings: list[str] = Field(default_factory=list)
    footprint: dict[str, Any] | None = None


class DatasetRequest(BaseModel):
    dataset_id: str
    variables: list[str]
    start_date: date
    end_date: date
    geometry: GeometrySpec
    resolution: str | None = None


class AcquiredFile(BaseModel):
    filename: str
    uri: str
    sha256: str
    size_bytes: int
    content_type: str


class AcquisitionResult(BaseModel):
    dataset_id: str
    provider: str
    source_request: dict[str, Any]
    files: list[AcquiredFile]
    metadata: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    derived_artifacts: list[ArtifactRecord] = Field(default_factory=list)
    vegetation_analysis: VegetationAnalysis | None = None


class DataValidationReport(BaseModel):
    dataset_id: str
    valid: bool
    temporal_coverage: tuple[date, date] | None = None
    missing_rate: float = 0
    units: str | None = None
    row_count: int = 0
    checks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class HarmonizationReport(BaseModel):
    valid: bool
    overlap_start: date
    overlap_end: date
    temporal_aggregation: str
    seasonal_definition: str = "DJF/MAM/JJA/SON; December assigned to following winter year"
    spatial_definitions: dict[str, str]
    join_keys: list[str]
    dropped_observations: dict[str, int]
    paired_sample_count: int
    artifact_uri: str


class AnalysisStep(BaseModel):
    id: str
    operation: str
    inputs: list[str]
    output: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class AnalysisPlan(BaseModel):
    version: str = "1.0"
    steps: list[AnalysisStep]
    expected_artifacts: list[str]
    significance_alpha: float = 0.05


class ExecutionRequest(BaseModel):
    run_id: UUID
    code_uri: str
    input_uris: list[str]
    output_prefix: str
    timeout_seconds: int = 180


class ExecutionResult(BaseModel):
    status: Literal["success", "failed"]
    attempt: int
    metrics: dict[str, float | int | str | bool] = Field(default_factory=dict)
    summary_fields: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error_class: str | None = None
    stderr_excerpt: str | None = None


class ScientificValidationReport(BaseModel):
    valid: bool
    checks: list[str]
    warnings: list[str] = Field(default_factory=list)


class ArtifactRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: str
    name: str
    uri: str
    sha256: str
    content_type: str
    size_bytes: int
    created_by: str
    download_url: str | None = None


class GemmaEvidenceAudit(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    scope: GemmaAuditScope
    verdict: GemmaAuditVerdict
    dispatch_allowed: bool = False
    unsupported_claims: list[str] = Field(default_factory=list, max_length=8)
    privacy_concerns: list[str] = Field(default_factory=list, max_length=8)
    action_constraints: list[str] = Field(default_factory=list, max_length=8)
    rationale: str = Field(min_length=1, max_length=1200)
    model: str
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime = Field(default_factory=utc_now)
    input_sha256: str
    output_sha256: str
    error: str | None = None


class ModelUsageRecord(BaseModel):
    family: Literal["Gemini", "Gemma", "Veo", "Lyria"]
    model: str
    purpose: str
    status: Literal["configured", "completed", "failed", "queued", "generating"]
    invocation_count: int = Field(default=0, ge=0)
    last_used_at: datetime | None = None
    artifact_ids: list[UUID] = Field(default_factory=list)


class MediaJob(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    job_type: MediaJobType
    status: MediaJobStatus = MediaJobStatus.QUEUED
    model: str
    run_id: UUID
    mission_id: UUID | None = None
    alert_id: UUID | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    attempt_count: int = Field(default=0, ge=0)
    lease_expires_at: datetime | None = None
    dispatch_id: str | None = None
    provider_operation_name: str | None = None
    prompt: str
    prompt_sha256: str
    artifact_id: UUID | None = None
    error: str | None = None


class RasterLegendStop(BaseModel):
    value: float
    label: str
    color: str


class MapRasterLayer(BaseModel):
    id: str
    label: str
    metric: Literal["ndvi", "ndmi", "stress"]
    period: Literal["current", "baseline", "anomaly"]
    artifact_id: UUID
    bounds: tuple[float, float, float, float]
    unit: str
    legend: list[RasterLegendStop]
    opacity: float = Field(default=0.72, ge=0, le=1)
    resolution_m: float = Field(gt=0)
    scientific_resolution_m: float = Field(default=20, gt=0)
    display_width_px: int | None = Field(default=None, gt=0)
    display_height_px: int | None = Field(default=None, gt=0)
    download_url: str | None = None


class VegetationPeriod(BaseModel):
    start: date
    end: date


class VegetationAnalysis(BaseModel):
    status: Literal["available", "insufficient"]
    source: str = "Copernicus Sentinel-2 Level-2A via Earth Search"
    attribution: str = "Contains modified Copernicus Sentinel data"
    resolution_m: float = 20
    current_period: VegetationPeriod
    baseline_period: VegetationPeriod
    current_scene_count: int = 0
    baseline_scene_count: int = 0
    valid_coverage_pct: float = 0
    observation_age_days: int | None = None
    latest_observation_date: date | None = None
    median_ndvi: float | None = None
    baseline_median_ndvi: float | None = None
    ndvi_anomaly: float | None = None
    median_ndmi: float | None = None
    baseline_median_ndmi: float | None = None
    ndmi_anomaly: float | None = None
    stressed_area_pct: float | None = None
    stressed_area_sq_mi: float | None = None
    confidence: float = Field(default=0, ge=0, le=1)
    scene_ids: list[str] = Field(default_factory=list)
    layers: list[MapRasterLayer] = Field(default_factory=list)
    sample_grid_artifact_id: UUID | None = None
    time_series: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class RunEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    timestamp: datetime = Field(default_factory=utc_now)
    agent: str
    type: str
    message: str
    status: Literal["pending", "active", "success", "warning", "error"] = "success"
    payload: dict[str, Any] = Field(default_factory=dict)


class ProvenanceManifest(BaseModel):
    run_id: UUID
    research_question: str
    created_at: datetime
    knowledge_registry_version: str
    datasets: list[dict[str, Any]]
    transformations: list[dict[str, Any]]
    analysis: dict[str, Any]
    artifacts: list[dict[str, Any]]
    software: dict[str, Any]


class CreateRunRequest(BaseModel):
    query: str = Field(min_length=12, max_length=4000)
    study_area: StudyArea | None = None
    demo_fault: bool = False


class CreateRunResponse(BaseModel):
    run_id: UUID
    status: RunStatus


class CreateBriefingVideoResponse(BaseModel):
    run_id: UUID
    status: BriefingVideoStatus
    model: str


class RunSummary(BaseModel):
    id: UUID
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    user_query: str
    current_step: str
    progress: int
    selected_dataset_count: int = 0
    artifact_count: int = 0
    final_summary: str | None = None
    error: dict[str, Any] | None = None
    monitoring_mission_id: UUID | None = None


class RunRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    status: RunStatus = RunStatus.CREATED
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    user_query: str
    agent_decision: dict[str, Any] | None = None
    research_spec: ResearchSpecification | None = None
    dataset_candidates: list[DatasetCandidate] = Field(default_factory=list)
    selected_datasets: list[DatasetCandidate] = Field(default_factory=list)
    current_step: str = "created"
    progress: int = 0
    repair_attempts: int = 0
    final_summary: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    chart_data: dict[str, Any] = Field(default_factory=dict)
    harmonization: HarmonizationReport | None = None
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    events: list[RunEvent] = Field(default_factory=list)
    error: dict[str, Any] | None = None
    monitoring_mission_id: UUID | None = None
    monitoring_baseline_run_id: UUID | None = None
    workflow_dispatch_id: str | None = None
    workflow_attempt: int = 0
    workflow_lease_expires_at: datetime | None = None
    workflow_checkpoints: dict[str, WorkflowOperationStatus] = Field(default_factory=dict)
    workflow_started_at: datetime | None = None
    workflow_completed_at: datetime | None = None
    trace_id: str | None = None
    operational_impact: dict[str, float | int | str] = Field(default_factory=dict)
    confidence: float | None = None
    evidence_disagreements: list[dict[str, Any]] = Field(default_factory=list)
    scientific_review: dict[str, Any] | None = None
    operational_action: dict[str, Any] | None = None
    demo_fault: bool = False
    cancel_requested: bool = False
    study_area: StudyArea | None = None
    briefing_video_status: BriefingVideoStatus = BriefingVideoStatus.NOT_REQUESTED
    briefing_video_error: str | None = None
    briefing_video_artifact_id: UUID | None = None
    briefing_video_model: str | None = None
    briefing_video_operation_name: str | None = None
    gemma_audits: list[GemmaEvidenceAudit] = Field(default_factory=list)
    model_usage: list[ModelUsageRecord] = Field(default_factory=list)
    vegetation: VegetationAnalysis | None = None


class CreateMonitoringMissionRequest(BaseModel):
    source_run_id: UUID
    name: str | None = Field(default=None, min_length=3, max_length=120)
    objective: str = Field(
        default="Notify me when authoritative evidence indicates a meaningful habitat change.",
        min_length=12,
        max_length=500,
    )
    cadence_days: int = Field(default=30, ge=1, le=365)
    sensitivity: MonitoringSensitivity = MonitoringSensitivity.BALANCED
    indicator_keys: list[str] = Field(default_factory=list, max_length=12)
    metric_thresholds: dict[str, float] = Field(default_factory=dict)
    trigger_directions: dict[str, MonitoringTriggerDirection] = Field(default_factory=dict)
    notification_enabled: bool = True
    audio_alert_enabled: bool = False


class UpdateMonitoringMissionRequest(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=120)
    objective: str | None = Field(default=None, min_length=12, max_length=500)
    cadence_days: int | None = Field(default=None, ge=1, le=365)
    sensitivity: MonitoringSensitivity | None = None
    indicator_keys: list[str] | None = Field(default=None, max_length=12)
    metric_thresholds: dict[str, float] | None = None
    trigger_directions: dict[str, MonitoringTriggerDirection] | None = None
    notification_enabled: bool | None = None
    audio_alert_enabled: bool | None = None
    status: MissionStatus | None = None


class MetricComparison(BaseModel):
    metric: str
    previous_value: float
    current_value: float
    absolute_delta: float
    threshold: float
    direction: MonitoringTriggerDirection = MonitoringTriggerDirection.EITHER
    meaningful: bool


class FieldInspectionTask(BaseModel):
    id: str
    title: str
    instructions: str
    priority: Literal["routine", "priority", "urgent"] = "priority"
    coordinates: tuple[float, float] | None = None
    status: Literal["prepared", "dispatched", "completed"] = "prepared"


class MonitoringAlert(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=utc_now)
    severity: Literal["info", "attention"] = "attention"
    title: str
    message: str
    run_id: UUID
    metric: str | None = None
    comparison_metrics: list[str] = Field(default_factory=list)
    field_actions: list[str] = Field(default_factory=list)
    field_tasks: list[FieldInspectionTask] = Field(default_factory=list)
    action_packet_artifact_id: UUID | None = None
    audio_status: IncidentAudioStatus = IncidentAudioStatus.NOT_REQUESTED
    audio_job_id: UUID | None = None
    audio_artifact_id: UUID | None = None
    audio_model: str | None = None
    audio_error: str | None = None
    acknowledged: bool = False
    delivery: dict[str, Any] | None = None


class MissionCheck(BaseModel):
    run_id: UUID
    status: MissionCheckStatus = MissionCheckStatus.QUEUED
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
    meaningful_change: bool | None = None
    comparisons: list[MetricComparison] = Field(default_factory=list)
    summary: str | None = None
    error: str | None = None


class MonitoringMission(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    status: MissionStatus = MissionStatus.ACTIVE
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    baseline_run_id: UUID
    latest_run_id: UUID
    query: str
    region: str
    habitat: str = "Climate-sensitive habitat"
    objective: str = "Notify me when authoritative evidence indicates a meaningful habitat change."
    cadence_days: int = 30
    sensitivity: MonitoringSensitivity = MonitoringSensitivity.BALANCED
    indicator_keys: list[str] = Field(default_factory=list)
    next_check_at: datetime
    metric_thresholds: dict[str, float]
    trigger_directions: dict[str, MonitoringTriggerDirection] = Field(default_factory=dict)
    run_ids: list[UUID] = Field(default_factory=list)
    checks: list[MissionCheck] = Field(default_factory=list)
    alerts: list[MonitoringAlert] = Field(default_factory=list)
    rolling_window: bool = True
    last_observation_end: date | None = None
    check_lease_expires_at: datetime | None = None
    notification_enabled: bool = False
    audio_alert_enabled: bool = False
    study_area: StudyArea | None = None


class ModelUsageResponse(BaseModel):
    run_id: UUID
    models: list[ModelUsageRecord]


class CreateMonitoringMissionResponse(BaseModel):
    mission_id: UUID
    status: MissionStatus


class MonitoringCadencePreset(BaseModel):
    label: str
    days: int = Field(ge=1, le=365)


class MonitoringIndicatorOption(BaseModel):
    key: str
    label: str
    detail: str
    metric: str
    unit: str
    step: float = Field(gt=0)
    current_value: float
    thresholds: dict[MonitoringSensitivity, float]
    default_direction: MonitoringTriggerDirection
    recommended: bool = False


class MonitoringPolicyOptions(BaseModel):
    run_id: UUID
    available_indicators: list[MonitoringIndicatorOption]
    cadence_presets: list[MonitoringCadencePreset]
    default_indicator_keys: list[str]
    default_cadence_days: int = 30
    default_sensitivity: MonitoringSensitivity = MonitoringSensitivity.BALANCED


class EvidenceNode(BaseModel):
    id: str
    kind: Literal["claim", "metric", "dataset", "transformation", "code", "validation", "artifact"]
    label: str
    detail: str
    uri: str | None = None
    sha256: str | None = None


class EvidenceLink(BaseModel):
    source: str
    target: str
    relationship: str


class EvidenceChain(BaseModel):
    run_id: UUID
    claim: str
    nodes: list[EvidenceNode]
    links: list[EvidenceLink]
    validation_status: Literal["validated", "incomplete"]


AcquisitionResult.model_rebuild()
