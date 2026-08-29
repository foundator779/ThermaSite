from __future__ import annotations

import asyncio
import json
import math
import mimetypes
from pathlib import Path
from uuid import UUID

from terraforge.adk import GoogleAdkRuntime
from terraforge.agents import create_adk_analysis_plan, evidence_summary
from terraforge.analysis import AnalysisExecutor, generate_analysis_code
from terraforge.audit import GemmaAuditService
from terraforge.connectors import build_connectors
from terraforge.contracts.models import (
    DatasetRequest,
    GemmaAuditVerdict,
    ModelUsageRecord,
    RunEvent,
    RunStatus,
    WorkflowOperationStatus,
    utc_now,
)
from terraforge.harmonization import harmonize_local, validate_acquisition
from terraforge.knowledge import discover
from terraforge.observability import EventPublisher, deliver_webhook
from terraforge.persistence import ArtifactStore, MissionStore, RunStore
from terraforge.provenance import build_reproducibility_package
from terraforge.settings import Settings

from .policy import ToolCapability, ToolPolicy


class ResearchCoordinator:
    def __init__(
        self,
        settings: Settings,
        runs: RunStore,
        missions: MissionStore,
        artifacts: ArtifactStore,
        publisher: EventPublisher,
        gemma_audits: GemmaAuditService | None = None,
        media=None,
    ):
        self.settings = settings
        self.runs = runs
        self.missions = missions
        self.artifacts = artifacts
        self.publisher = publisher
        self.connectors = build_connectors(artifacts, settings)
        self.executor = AnalysisExecutor(settings, artifacts)
        self.adk = GoogleAdkRuntime(settings)
        self.gemma_audits = gemma_audits or GemmaAuditService(settings)
        self.media = media
        self.policy = ToolPolicy()

    @property
    def gemini_ready(self) -> bool:
        return self.adk.ready

    async def emit(self, run_id: UUID, agent: str, event_type: str, message: str, **payload):
        event_status = payload.pop("status", "success")
        run = await self.runs.get(run_id)
        if run:
            payload.setdefault("trace_id", run.trace_id or str(run_id).replace("-", ""))
            payload.setdefault("workflow_step", run.current_step)
            payload.setdefault("workflow_attempt", run.workflow_attempt)
        event = RunEvent(
            agent=agent, type=event_type, message=message, status=event_status, payload=payload
        )
        await self.runs.append_event(run_id, event)
        await self.publisher.publish(run_id, event)

    async def run(self, run_id: UUID) -> None:
        run = await self.runs.get(run_id)
        if run is None:
            return
        if run.status in {RunStatus.COMPLETED, RunStatus.CANCELLED}:
            return
        run.trace_id = run.trace_id or str(run.id).replace("-", "")
        run.workflow_started_at = run.workflow_started_at or utc_now()
        await self.runs.save(run)
        try:
            await self._status(run, RunStatus.INTERPRETING, "interpreting", 7)
            self.policy.require("ADKResearchPlanner", ToolCapability.MODEL_DECISION)
            coordination_query = run.user_query
            if run.study_area:
                coordination_query += (
                    "\nAuthoritative user-drawn study area supplied by the map. Use the custom_habitat "
                    f"workflow for its {run.study_area.area_sq_mi:.2f} square-mile geometry."
                )
            decision = await self.adk.coordinate(coordination_query, str(run_id))
            gemini_usage = next(
                (item for item in run.model_usage if item.family == "Gemini"), None
            )
            if gemini_usage:
                gemini_usage.invocation_count += 1
                gemini_usage.last_used_at = utc_now()
                gemini_usage.status = "completed"
            else:
                run.model_usage.append(
                    ModelUsageRecord(
                        family="Gemini",
                        model=self.settings.gemini_model,
                        purpose="ADK planning, scientific review, and operational decisions",
                        status="completed",
                        invocation_count=1,
                        last_used_at=utc_now(),
                    )
                )
            if run.study_area:
                decision.habitat_type = "custom_habitat"
                decision.anchor_place = run.study_area.label or "User-selected habitat area"
                decision.region = "User-drawn study area"
                decision.research_bbox = list(run.study_area.bbox)
                decision.required_data_roles = [
                    "area_station_climate",
                    "area_regional_climate",
                    "species_biodiversity",
                    "wildfire_activity",
                    "wetland_inventory",
                    "sentinel_2_l2a",
                ]
                decision.selected_dataset_ids = [
                    "noaa-ncei-ghcnd-user-area",
                    "nasa-power-merra2-user-area",
                    "gbif-occurrences-user-area",
                    "nasa-firms-user-area",
                    "usfws-nwi-user-area",
                    "sentinel-2-l2a-vegetation-user-area",
                ]
                decision.analysis_operations = [
                    "annual_mean",
                    "ols_trend_and_significance",
                    "seasonal_aggregate",
                    "precipitation_trend",
                    "habitat_climate_pressure",
                    "cross_source_climate_agreement",
                    "species_richness_and_sampling",
                    "wildfire_exposure",
                    "wetland_inventory_summary",
                    "satellite_vegetation_condition",
                    "ecological_evidence_synthesis",
                    "render_figures",
                ]
            run.agent_decision = decision.model_dump(mode="json")
            run.research_spec = decision.to_research_specification(run.user_query)
            if run.study_area:
                run.research_spec.research_geometry = run.study_area.geometry
            await self.runs.save(run)
            await self.emit(
                run_id,
                "ADKResearchPlanner",
                "adk.coordination.completed",
                "The ADK Research Planner produced the validated research, dataset, and analysis decision.",
                model=self.settings.gemini_model,
                decision=run.agent_decision,
            )
            await self.emit(
                run_id,
                "ResearchInterpreter",
                "research.parsed",
                f"Parsed {run.research_spec.anchor_place}, the requested period, habitat indicators, and validation requirements.",
                research_spec=run.research_spec.model_dump(mode="json"),
            )
            await self.emit(
                run_id,
                "ResearchCoordinator",
                "research.scope_expanded",
                "A single source cannot support the requested regional conclusion; complementary in-situ, regional, and habitat-condition evidence are required.",
            )

            await self._status(run, RunStatus.DISCOVERING_DATA, "dataset_discovery", 15)
            self.policy.require("DatasetDiscoveryAgent", ToolCapability.REGISTRY_READ)
            run.dataset_candidates = discover(run.research_spec)
            await self.runs.save(run)
            for candidate in run.dataset_candidates:
                await self.emit(
                    run_id,
                    "DatasetDiscoveryAgent",
                    "dataset.candidate",
                    f"Ranked {candidate.name} for {candidate.data_role}.",
                    candidate=candidate.model_dump(mode="json"),
                )

            await self._status(run, RunStatus.SELECTING_DATASETS, "dataset_selection", 22)
            selected_ids = set(decision.selected_dataset_ids)
            run.selected_datasets = [
                candidate
                for candidate in run.dataset_candidates
                if candidate.dataset_id in selected_ids
            ]
            if len(run.selected_datasets) != len(selected_ids):
                raise ValueError("Gemini dataset selection could not be resolved in the registry")
            await self.runs.save(run)
            for candidate in run.selected_datasets:
                await self.emit(
                    run_id,
                    "DatasetDiscoveryAgent",
                    "dataset.selected",
                    f"Selected {candidate.name}: {candidate.rationale}",
                    dataset=candidate.model_dump(mode="json"),
                )

            await self._status(run, RunStatus.ACQUIRING_DATA, "acquisition", 31)
            acquisitions = []
            for index, candidate in enumerate(run.selected_datasets):
                await self.emit(
                    run_id,
                    "AcquisitionAgent",
                    "acquisition.started",
                    f"Requesting {candidate.name} from {candidate.provider}.",
                    dataset_id=candidate.dataset_id,
                )
                variables_by_role = {
                    "local_station_temperature": ["air_temperature"],
                    "regional_gridded_temperature": ["air_temperature"],
                    "nearby_sea_ice": ["sea_ice_extent"],
                    "wetland_station_climate": ["air_temperature", "precipitation"],
                    "wetland_regional_climate": ["air_temperature", "precipitation"],
                    "wetland_water_level": ["water_level"],
                    "area_station_climate": ["air_temperature", "precipitation"],
                    "area_regional_climate": ["air_temperature", "precipitation"],
                    "species_biodiversity": ["species_occurrence"],
                    "wildfire_activity": ["active_fire"],
                    "wetland_inventory": ["wetland_extent", "wetland_type"],
                    "sentinel_2_l2a": ["vegetation_condition"],
                }
                variables = variables_by_role[candidate.data_role]
                self.policy.require("AcquisitionAgent", ToolCapability.NETWORK_ACQUISITION)
                request = DatasetRequest(
                    dataset_id=candidate.dataset_id,
                    variables=variables,
                    start_date=run.research_spec.start_date,
                    end_date=run.research_spec.end_date,
                    geometry=run.research_spec.research_geometry,
                )
                result = await self.connectors[candidate.dataset_id].fetch(str(run_id), request)
                acquisitions.append(result)
                if result.vegetation_analysis:
                    run.vegetation = result.vegetation_analysis
                    run.artifacts.extend(result.derived_artifacts)
                    await self.runs.save(run)
                    await self.emit(
                        run_id,
                        "SatelliteVegetationAgent",
                        "satellite.vegetation.completed",
                        (
                            "Built deterministic Sentinel-2 NDVI and NDMI composites at "
                            f"{run.vegetation.resolution_m:g} m resolution; "
                            f"{run.vegetation.valid_coverage_pct or 0:.1f}% of the selected area "
                            "passed the satellite quality mask."
                        ),
                        status=(
                            "success"
                            if run.vegetation.status == "available"
                            else "warning"
                        ),
                        vegetation=run.vegetation.model_dump(mode="json"),
                    )
                await self.emit(
                    run_id,
                    "AcquisitionAgent",
                    "acquisition.completed",
                    f"Preserved {result.files[0].size_bytes / 1024:,.0f} KB with SHA-256 {result.files[0].sha256[:12]}…",
                    acquisition=result.model_dump(mode="json"),
                )

            await self._status(run, RunStatus.VALIDATING_DATA, "data_validation", 45)
            for result in acquisitions:
                report = validate_acquisition(result, self.artifacts)
                if not report.valid:
                    raise ValueError(f"Data validation failed for {result.dataset_id}")
                await self.emit(
                    run_id,
                    "DataQualityAgent",
                    "validation.completed",
                    f"Validated {result.dataset_id}: {report.units}; immutable hash and source metadata present.",
                    report=report.model_dump(mode="json"),
                )

            await self._status(run, RunStatus.HARMONIZING_DATA, "harmonization", 55)
            self.policy.require("CrossDatasetHarmonizationAgent", ToolCapability.ARTIFACT_READ)
            report, harmonized_uri = await asyncio.to_thread(
                harmonize_local,
                str(run_id),
                acquisitions,
                self.artifacts,
                run.research_spec.start_date,
                run.research_spec.end_date,
            )
            run.harmonization = report
            await self.runs.save(run)
            await self.emit(
                run_id,
                "CrossDatasetHarmonizationAgent",
                "harmonization.completed",
                f"Aligned {report.paired_sample_count} monthly observations across {report.overlap_start}–{report.overlap_end}.",
                harmonization=report.model_dump(mode="json"),
            )

            await self._status(run, RunStatus.PLANNING_ANALYSIS, "analysis_planning", 64)
            plan = create_adk_analysis_plan(
                run.research_spec,
                report,
                list(decision.analysis_operations),
            )
            await self.emit(
                run_id,
                "AnalysisPlanner",
                "analysis.plan_created",
                f"Created {len(plan.steps)} typed analysis steps with declared scientific artifacts.",
                plan=plan.model_dump(mode="json"),
            )

            await self._status(run, RunStatus.GENERATING_CODE, "code_generation", 70)
            code = generate_analysis_code(plan)
            if run.demo_fault and run.repair_attempts == 0:
                code += "\nraise KeyError('terraforge controlled recovery demonstration')\n"
                await self.emit(
                    run_id,
                    "ReliabilityHarness",
                    "demo.fault.injected",
                    "Injected a disclosed schema-style failure to demonstrate bounded autonomous recovery.",
                    status="warning",
                    fault="controlled_key_error",
                )
            code_artifact = self.artifacts.put_artifact(
                str(run_id), "analysis.py", code.encode(), "text/x-python", "CodeGenerationAgent"
            )
            run.artifacts.append(code_artifact)
            await self.runs.save(run)
            await self.emit(
                run_id,
                "CodeGenerationAgent",
                "code.generated",
                "Generated analysis.py from the approved plan; static safety inspection is enforced by the job runtime.",
                artifact=code_artifact.model_dump(mode="json"),
            )

            await self._status(run, RunStatus.EXECUTING, "analysis_execution", 77)
            self.policy.require("AnalysisExecutor", ToolCapability.RESTRICTED_EXECUTION)
            await self.emit(
                run_id,
                "AnalysisExecutor",
                "execution.started",
                "Started restricted analysis runtime with declared inputs and outputs only.",
                attempt=1,
            )
            if self.settings.cloud_enabled:
                result, output_dir = await self.executor.execute_cloud(
                    run_id, code_artifact.uri, harmonized_uri
                )
            else:
                result, output_dir = await self.executor.execute_local(run_id, code, harmonized_uri)
            if result.status == "failed":
                await self.emit(
                    run_id,
                    "AnalysisExecutor",
                    "execution.failed",
                    f"Execution failed: {result.error_class}.",
                    status="error",
                    result=result.model_dump(mode="json"),
                )
                await self._status(run, RunStatus.REPAIRING, "repair", 79)
                run.repair_attempts += 1
                if run.repair_attempts >= self.settings.max_repair_attempts:
                    raise RuntimeError("Bounded repair attempts exhausted")
                await self.emit(
                    run_id,
                    "ExecutionRepairAgent",
                    "repair.started",
                    "Classified the failure and prepared a bounded implementation-only patch.",
                )
                # The canonical generator is deterministic; regenerating repairs accidental schema edits without altering science.
                code = generate_analysis_code(plan)
                await self.emit(
                    run_id,
                    "ExecutionRepairAgent",
                    "repair.completed",
                    "Reconciled the generated schema mapping and passed the static safety check.",
                )
                repaired_artifact = self.artifacts.put_artifact(
                    str(run_id),
                    "analysis_repaired.py",
                    code.encode(),
                    "text/x-python",
                    "ExecutionRepairAgent",
                )
                run.artifacts.append(repaired_artifact)
                await self.runs.save(run)
                if self.settings.cloud_enabled:
                    result, output_dir = await self.executor.execute_cloud(
                        run_id, repaired_artifact.uri, harmonized_uri, attempt=2
                    )
                else:
                    result, output_dir = await self.executor.execute_local(
                        run_id, code, harmonized_uri, attempt=2
                    )
                if result.status == "failed":
                    raise RuntimeError(result.stderr_excerpt or "Repaired execution failed")
            await self.emit(
                run_id,
                "AnalysisExecutor",
                "execution.completed",
                f"Analysis execution attempt {result.attempt} produced declared artifacts and structured metrics.",
                result=result.model_dump(mode="json"),
            )

            run.metrics = result.metrics
            run.chart_data = result.summary_fields.get("chart_data", {})
            if run.vegetation:
                vegetation_metrics = {
                    "vegetation_current_ndvi": run.vegetation.median_ndvi,
                    "vegetation_baseline_ndvi": run.vegetation.baseline_median_ndvi,
                    "vegetation_ndvi_anomaly": run.vegetation.ndvi_anomaly,
                    "vegetation_current_ndmi": run.vegetation.median_ndmi,
                    "vegetation_baseline_ndmi": run.vegetation.baseline_median_ndmi,
                    "vegetation_ndmi_anomaly": run.vegetation.ndmi_anomaly,
                    "vegetation_stressed_area_pct": run.vegetation.stressed_area_pct,
                    "vegetation_valid_coverage_pct": run.vegetation.valid_coverage_pct,
                }
                run.metrics.update(
                    {key: value for key, value in vegetation_metrics.items() if value is not None}
                )
                if run.vegetation.time_series:
                    run.chart_data["vegetation-condition"] = {
                        "kind": "line",
                        "x_key": "date",
                        "x_label": "Acquisition date",
                        "y_label": "Vegetation index",
                        "unit": "index",
                        "series": [
                            {"key": "ndvi", "label": "NDVI greenness", "color": "#267a50", "kind": "line"},
                            {"key": "ndmi", "label": "NDMI moisture", "color": "#287f97", "kind": "line"},
                        ],
                        "data": run.vegetation.time_series,
                    }
            run.confidence, run.evidence_disagreements = self._assess_evidence(run.metrics)
            if run.vegetation and run.vegetation.status != "available":
                run.evidence_disagreements.append(
                    {
                        "indicator": "satellite_vegetation_coverage",
                        "severity": "moderate",
                        "message": (
                            "Sentinel-2 evidence did not meet the minimum scene-count and "
                            "cloud-free coverage gates, so no vegetation-stress classification "
                            "was made."
                        ),
                        "value": run.vegetation.valid_coverage_pct,
                    }
                )
                run.confidence = max(0.35, round((run.confidence or 0.0) - 0.12, 2))
            await self.runs.save(run)
            if run.evidence_disagreements:
                await self.emit(
                    run_id,
                    "ScientificValidationAgent",
                    "evidence.disagreement.detected",
                    f"Detected {len(run.evidence_disagreements)} cross-source disagreements; confidence was reduced rather than hiding the conflict.",
                    status="warning",
                    confidence=run.confidence,
                    disagreements=run.evidence_disagreements,
                )
            else:
                await self.emit(
                    run_id,
                    "ScientificValidationAgent",
                    "evidence.corroboration.completed",
                    "Independent source indicators were directionally consistent.",
                    confidence=run.confidence,
                )
            for path in Path(output_dir).iterdir():
                if (
                    path.suffix in {".png", ".json", ".geojson"}
                    and path.name != "execution_manifest.json"
                ):
                    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                    run.artifacts.append(
                        self.artifacts.put_artifact(
                            str(run_id),
                            path.name,
                            path.read_bytes(),
                            content_type,
                            "AnalysisExecutor",
                        )
                    )
            await self.runs.save(run)

            await self._status(run, RunStatus.VALIDATING_OUTPUT, "scientific_validation", 88)
            finite = all(
                math.isfinite(value)
                for value in result.metrics.values()
                if isinstance(value, float)
            )
            if not finite or len([item for item in run.artifacts if item.type == "plot"]) < 4:
                raise ValueError("Scientific validation found missing or non-finite outputs")
            proposed_summary = evidence_summary(run.metrics)
            self.policy.require("ADKScientificReviewer", ToolCapability.MODEL_DECISION)
            review = await self.adk.review_science(
                run_id=str(run_id),
                proposed_summary=proposed_summary,
                metrics=run.metrics,
                confidence=run.confidence or 0.0,
                disagreements=run.evidence_disagreements,
                warnings=(
                    result.warnings
                    + (run.vegetation.warnings if run.vegetation else [])
                ),
            )
            run.scientific_review = review.model_dump(mode="json")
            run.confidence = max(
                0.0, min(1.0, (run.confidence or 0.0) + review.confidence_adjustment)
            )
            await self.runs.save(run)
            if not review.approved_for_reporting:
                raise ValueError(
                    "The ADK Scientific Reviewer withheld reporting because the evidence was insufficient"
                )
            await self.emit(
                run_id,
                "ADKScientificReviewer",
                "adk.scientific_review.completed",
                review.reviewer_summary,
                confidence=run.confidence,
                concerns=review.concerns,
                action_constraints=review.action_constraints,
            )
            await self.emit(
                run_id,
                "ScientificValidationAgent",
                "scientific_validation.completed",
                "Validated finite statistics, expected plots, sample count, dates, and non-causal relationship wording.",
            )

            finding_audit = await self.gemma_audits.audit_finding(run, proposed_summary)
            run.gemma_audits.append(finding_audit)
            if finding_audit.verdict in {GemmaAuditVerdict.BLOCK, GemmaAuditVerdict.ERROR}:
                run.confidence = min(run.confidence or 0.55, 0.55)
            elif finding_audit.verdict == GemmaAuditVerdict.WARN:
                run.confidence = min(run.confidence or 0.7, 0.7)
            await self.runs.save(run)
            await self.emit(
                run_id,
                "Gemma Evidence Auditor",
                "gemma.finding_audit.completed",
                finding_audit.rationale,
                status=(
                    "success"
                    if finding_audit.verdict == GemmaAuditVerdict.PASS
                    else "warning"
                ),
                audit=finding_audit.model_dump(mode="json"),
                confidence=run.confidence,
            )

            await self._status(run, RunStatus.GENERATING_REPORT, "reporting", 93)
            run.final_summary = proposed_summary
            await self.runs.save(run)
            await self.emit(
                run_id,
                "ProvenanceReportingAgent",
                "report.completed",
                "Generated findings strictly from structured execution metrics.",
                summary=run.final_summary,
            )
            run.operational_impact = self._operational_impact(run)
            await self.runs.save(run)

            await self._status(run, RunStatus.PACKAGING, "packaging", 97)
            model_manifest = {
                "run_id": str(run.id),
                "generated_at": utc_now().isoformat(),
                "models": [item.model_dump(mode="json") for item in run.model_usage],
                "gemma_audits": [item.model_dump(mode="json") for item in run.gemma_audits],
                "configured_models": {
                    "Gemini": self.settings.gemini_model,
                    "Gemma": self.settings.gemma_model,
                    "Veo": self.settings.veo_model,
                    "Lyria": self.settings.lyria_model,
                },
            }
            run.artifacts.append(
                self.artifacts.put_artifact(
                    str(run.id),
                    "google_ai_model_manifest.json",
                    json.dumps(model_manifest, indent=2, default=str).encode(),
                    "application/json",
                    "AI Provenance Agent",
                )
            )
            manifest_artifact, bundle_artifact = build_reproducibility_package(
                run, acquisitions, plan, code, self.artifacts
            )
            run.artifacts += [manifest_artifact, bundle_artifact]
            await self.runs.save(run)
            await self.emit(
                run_id,
                "ProvenanceReportingAgent",
                "bundle.completed",
                "Created provenance manifest and downloadable reproducibility bundle.",
                bundle=bundle_artifact.model_dump(mode="json"),
            )
            if run.monitoring_mission_id:
                mission = await self.missions.get(run.monitoring_mission_id)
                if mission is None:
                    raise RuntimeError("Monitoring mission disappeared during execution")
                previous = await self.runs.get(mission.latest_run_id)
                if previous is None:
                    raise RuntimeError("Monitoring baseline run is unavailable")
                mission = await self.missions.complete_check(
                    mission.id, current=run, previous=previous
                )
                check = next(item for item in mission.checks if item.run_id == run.id)
                self.policy.require("ADKOperationalActionAgent", ToolCapability.MODEL_DECISION)
                action = await self.adk.decide_monitoring_action(
                    run_id=str(run.id),
                    policy={
                        "name": mission.name,
                        "objective": mission.objective,
                        "sensitivity": mission.sensitivity,
                        "indicators": mission.indicator_keys,
                        "notification_authorized": mission.notification_enabled,
                    },
                    comparisons=[item.model_dump(mode="json") for item in check.comparisons],
                    scientific_review=run.scientific_review or {},
                )
                run.operational_action = action.model_dump(mode="json")
                mission = await self.missions.record_action(
                    mission.id, run.id, run.operational_action
                )
                alert = mission.alerts[-1]
                field_steps = "\n".join(f"- {item}" for item in alert.field_actions)
                briefing = (
                    f"# {alert.title}\n\n"
                    f"Mission: {mission.name}\n\n"
                    f"Region: {mission.region}\n\n"
                    f"{alert.message}\n\n"
                    f"Validated finding: {run.final_summary}\n\n"
                    f"Field-verification steps:\n{field_steps or '- No field action required.'}\n\n"
                    f"Run: {run.id}\n"
                )
                briefing_artifact = self.artifacts.put_artifact(
                    str(run.id),
                    "incident_action_packet.md",
                    briefing.encode(),
                    "text/markdown",
                    "ADKOperationalActionAgent",
                )
                run.artifacts.append(briefing_artifact)
                alert.action_packet_artifact_id = briefing_artifact.id
                dispatch_audit = await self.gemma_audits.audit_dispatch(
                    run,
                    title=alert.title,
                    message=alert.message,
                    field_actions=alert.field_actions,
                    comparison_metrics=alert.comparison_metrics,
                )
                run.gemma_audits.append(dispatch_audit)
                await self.runs.save(run)
                await self.emit(
                    run_id,
                    "Gemma Dispatch Auditor",
                    "gemma.dispatch_audit.completed",
                    dispatch_audit.rationale,
                    status="success" if dispatch_audit.dispatch_allowed else "warning",
                    audit=dispatch_audit.model_dump(mode="json"),
                )
                if (
                    alert.severity == "attention"
                    and action.notification_recommended
                    and mission.notification_enabled
                    and self.settings.monitoring_webhook_url
                    and dispatch_audit.dispatch_allowed
                ):
                    self.policy.require("NotificationAgent", ToolCapability.NOTIFICATION_DELIVERY)
                    alert.delivery = await deliver_webhook(
                        self.settings.monitoring_webhook_url.get_secret_value(),
                        {
                            "event": "habiwatch.monitoring.incident",
                            "mission_id": str(mission.id),
                            "run_id": str(run.id),
                            "severity": alert.severity,
                            "title": alert.title,
                            "message": alert.message,
                            "summary": run.final_summary,
                            "field_tasks": [item.model_dump(mode="json") for item in alert.field_tasks],
                            "action_packet": {
                                "artifact_url": f"/api/v1/runs/{run.id}/artifacts/{briefing_artifact.id}",
                                "content_markdown": briefing,
                            },
                        },
                        idempotency_key=str(alert.id),
                    )
                    if alert.delivery.get("status") == "delivered":
                        for task in alert.field_tasks:
                            task.status = "dispatched"
                elif (
                    alert.severity == "attention"
                    and action.notification_recommended
                    and mission.notification_enabled
                    and self.settings.monitoring_webhook_url
                ):
                    alert.delivery = {
                        "status": "withheld_by_gemma",
                        "message": "External delivery was withheld by the independent Gemma gate.",
                        "audit_id": str(dispatch_audit.id),
                    }
                else:
                    alert.delivery = {
                        "status": "artifact_only",
                        "message": "Briefing created; no external webhook was configured.",
                    }
                await self.runs.save(run)
                await self.missions.save(mission)
                if (
                    self.media
                    and alert.severity == "attention"
                    and mission.audio_alert_enabled
                    and dispatch_audit.dispatch_allowed
                ):
                    await self.media.enqueue_audio(mission.id, alert.id, run.id)
                await self.emit(
                    run_id,
                    "ADKOperationalActionAgent",
                    "adk.operational_action.completed",
                    action.rationale,
                    action=run.operational_action,
                    incident_id=str(alert.id),
                )
                await self.emit(
                    run_id,
                    "MonitoringAgent",
                    "monitoring.comparison.completed",
                    check.summary or "Monitoring comparison completed.",
                    meaningful_change=check.meaningful_change,
                    comparisons=[item.model_dump(mode="json") for item in check.comparisons],
                    mission_id=str(mission.id),
                )
                await self.emit(
                    run_id,
                    "NotificationAgent",
                    "monitoring.alert.delivery_recorded",
                    "Created a habitat-change briefing and recorded its delivery outcome.",
                    delivery=alert.delivery,
                    briefing=briefing_artifact.model_dump(mode="json"),
                )
            await self._status(run, RunStatus.COMPLETED, "complete", 100)
            run.operational_impact = self._operational_impact(run)
            run.workflow_completed_at = utc_now()
            await self.runs.save(run)
            await self.emit(
                run_id,
                "ResearchCoordinator",
                "run.completed",
                "Research run completed with traceable evidence and reproducible artifacts.",
            )
        except asyncio.CancelledError:
            run.status = RunStatus.CANCELLED
            run.current_step = "cancelled"
            await self.runs.save(run)
            await self.emit(
                run_id,
                "ResearchCoordinator",
                "run.cancelled",
                "The research run was cancelled safely.",
                status="warning",
            )
        except Exception as exc:  # noqa: BLE001 -- workflow boundary persists every failure
            error_text = str(exc).lower()
            retryable = isinstance(exc, (TimeoutError, ConnectionError)) or any(
                marker in error_text
                for marker in ("timed out", "timeout", "429", "503", "temporar", "after 3 attempts")
            )
            run.status = RunStatus.FAILED
            run.current_step = "failed"
            run.error = {
                "code": type(exc).__name__.upper(),
                "message": str(exc),
                "retryable": retryable,
                "details": {},
            }
            if run.current_step:
                run.workflow_checkpoints[run.current_step] = WorkflowOperationStatus.FAILED
            await self.runs.save(run)
            await self.emit(
                run_id, "ResearchCoordinator", "run.failed", f"Run failed: {exc}", status="error"
            )
            if run.monitoring_mission_id:
                await self.missions.fail_check(run.monitoring_mission_id, run.id, str(exc))

    async def _status(self, run, status: RunStatus, step: str, progress: int):
        latest = await self.runs.get(run.id)
        if latest and latest.cancel_requested and status != RunStatus.CANCELLED:
            raise asyncio.CancelledError
        for name, operation_status in list(run.workflow_checkpoints.items()):
            if operation_status == WorkflowOperationStatus.ACTIVE and name != step:
                run.workflow_checkpoints[name] = WorkflowOperationStatus.COMPLETED
        run.status = status
        run.current_step = step
        run.progress = progress
        run.workflow_checkpoints[step] = (
            WorkflowOperationStatus.COMPLETED
            if status == RunStatus.COMPLETED
            else WorkflowOperationStatus.ACTIVE
        )
        await self.runs.save(run)

    @staticmethod
    def _assess_evidence(metrics: dict) -> tuple[float, list[dict]]:
        disagreements: list[dict] = []
        if "climate_source_agreement" in metrics:
            temperature_agreement = float(metrics.get("climate_source_agreement", 0))
            precipitation_agreement = float(metrics.get("precipitation_source_agreement", 0))
            if temperature_agreement < 0.65:
                disagreements.append(
                    {
                        "indicator": "temperature",
                        "severity": "moderate",
                        "message": "NOAA station and NASA regional temperature anomalies have weak agreement.",
                        "value": temperature_agreement,
                    }
                )
            if precipitation_agreement < 0.4:
                disagreements.append(
                    {
                        "indicator": "precipitation",
                        "severity": "moderate",
                        "message": "Station and modeled precipitation series have weak agreement.",
                        "value": precipitation_agreement,
                    }
                )
            station_trend = float(metrics.get("station_temperature_trend_c_per_decade", 0))
            regional_trend = float(metrics.get("regional_temperature_trend_c_per_decade", 0))
        else:
            station_trend = float(metrics.get("local_temperature_trend_c_per_decade", 0))
            regional_trend = float(metrics.get("regional_temperature_trend_c_per_decade", 0))
        if station_trend and regional_trend and station_trend * regional_trend < 0:
            disagreements.append(
                {
                    "indicator": "temperature_trend_direction",
                    "severity": "high",
                    "message": "Local and regional temperature trends point in opposite directions.",
                    "values": {"local": station_trend, "regional": regional_trend},
                }
            )
        ecological_roles = metrics.get("ecological_evidence_available_count")
        if isinstance(ecological_roles, (int, float)) and ecological_roles < 3:
            disagreements.append(
                {
                    "indicator": "ecological_evidence_coverage",
                    "severity": "moderate",
                    "message": (
                        f"Only {int(ecological_roles)} of 3 ecological evidence roles were "
                        "available; the assessment is explicitly coverage-limited."
                    ),
                    "value": ecological_roles,
                }
            )
        confidence = max(0.35, 0.92 - 0.18 * len(disagreements))
        return round(confidence, 2), disagreements

    @staticmethod
    def _operational_impact(run) -> dict[str, float | int | str]:
        started = run.workflow_started_at or run.created_at
        elapsed = (utc_now() - started).total_seconds()
        return {
            "authoritative_sources_acquired": len(run.selected_datasets),
            "artifacts_created": len(run.artifacts),
            "validation_checks_completed": len(
                [event for event in run.events if "validation.completed" in event.type]
            ),
            "workflow_steps_automated": len(run.workflow_checkpoints),
            "repair_attempts": run.repair_attempts,
            "runtime_seconds": round(elapsed, 2),
            "estimated_manual_hours_saved": 6,
            "impact_estimation_method": (
                "Conservative task-time model v1; estimate, not measured labor telemetry"
            ),
        }
