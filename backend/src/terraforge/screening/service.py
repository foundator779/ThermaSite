from __future__ import annotations

import asyncio
import io
import zipfile
from uuid import UUID

from terraforge.contracts.models import RunEvent
from terraforge.observability import EventPublisher
from terraforge.persistence import ArtifactStore
from terraforge.settings import Settings

from .catalog import get_catalog_site, select_catalog_shortlist
from .estimator import calculate_resource_estimate, normalize_polygon
from .fortyguard import FortyGuardClient, candidate_polygon
from .models import (
    CandidateSite,
    RescoreRequest,
    ResourceEstimate,
    ResourceEstimatorRequest,
    ScreeningRecord,
    ScreeningStatus,
)
from .research import GroundedSiteResearch
from .scoring import score_candidates
from .store import ScreeningStore


class ScreeningService:
    def __init__(
        self,
        settings: Settings,
        store: ScreeningStore,
        artifacts: ArtifactStore,
        publisher: EventPublisher,
        fortyguard: FortyGuardClient | None = None,
    ):
        self.settings = settings
        self.store = store
        self.artifacts = artifacts
        self.publisher = publisher
        self.fortyguard = fortyguard or FortyGuardClient(settings)
        self.research = GroundedSiteResearch(settings)
        self.tasks: dict[UUID, asyncio.Task] = {}

    async def start(self, record: ScreeningRecord) -> None:
        task = asyncio.create_task(self.run(record.id), name=f"screening-{record.id}")
        self.tasks[record.id] = task
        task.add_done_callback(lambda _: self.tasks.pop(record.id, None))

    async def shutdown(self) -> None:
        active = [task for task in self.tasks.values() if not task.done()]
        for task in active:
            task.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)

    async def emit(
        self,
        screening_id: UUID,
        agent: str,
        event_type: str,
        message: str,
        *,
        status: str = "success",
        **payload,
    ) -> None:
        event = RunEvent(
            agent=agent,
            type=event_type,
            message=message,
            status=status,
            payload={"screening_id": str(screening_id), **payload},
        )
        await self.store.append_event(screening_id, event)
        await self.publisher.publish(screening_id, event)

    async def _stage(
        self, record: ScreeningRecord, status: ScreeningStatus, step: str, progress: int
    ) -> None:
        record.status = status
        record.current_step = step
        record.progress = progress
        await self.store.save(record)

    async def run(self, screening_id: UUID) -> None:
        record = await self.store.get(screening_id)
        if record is None:
            return
        try:
            await self._stage(record, ScreeningStatus.PLANNING, "planning", 8)
            record.candidates = self._resolve_candidates(record)
            await self.store.save(record)
            await self.emit(
                screening_id,
                "Intake Agent",
                "screening.plan.created",
                (
                    f"Translated a {record.request.facility.facility_size_acres:g}-acre campus at "
                    f"{record.request.facility.it_density_mw_per_acre:g} MW/acre into a "
                    f"{record.request.cooling.it_load_mw:g} MW planning profile and selected "
                    f"{len(record.candidates)} comparable U.S. candidates."
                ),
                weights=record.request.weights.normalized(),
                facility=record.request.facility.model_dump(mode="json"),
                thermal_window=record.request.thermal_window.model_dump(mode="json"),
            )
            for site in record.candidates:
                await self.emit(
                    screening_id,
                    "Shortlist Agent",
                    "screening.candidate.selected",
                    f"Added {site.name} to the shortlist.",
                    site_id=site.id,
                    coordinates=[site.longitude, site.latitude],
                    rationale=site.shortlist_reason,
                )

            await self._stage(record, ScreeningStatus.ACQUIRING_HEAT, "fortyguard", 25)
            await self.emit(
                screening_id,
                "Heat Agent",
                "fortyguard.analysis.started",
                (
                    f"Submitted {len(record.candidates)} same-scale facility footprints for matched temperature "
                    "and exceedance analyses to FortyGuard."
                ),
                candidate_count=len(record.candidates),
                facility_size_acres=record.request.facility.facility_size_acres,
            )
            await asyncio.gather(
                *(self._acquire_heat(screening_id, record, site) for site in record.candidates)
            )
            if (
                record.request.auto_shortlist
                and not record.request.candidate_ids
                and not record.request.candidates
            ):
                await self._backfill_failed_heat_candidates(screening_id, record)
            await self.store.save(record)
            if not any(site.thermal for site in record.candidates):
                raise RuntimeError(
                    "No candidate returned rankable FortyGuard thermal evidence. Check the API key, plan access, and activity errors."
                )

            record.resource_estimates = self._build_facility_estimates(record)
            await self.store.save(record)
            await self.emit(
                screening_id,
                "Resource Estimator Agent",
                "facility.projections.completed",
                (
                    f"Converted FortyGuard heat evidence into {len(record.resource_estimates)} "
                    "comparable facility power and direct-water scenarios."
                ),
                estimates=[
                    {
                        "site_id": item.site_id,
                        "average_facility_power_mw": item.average_facility_power_mw,
                        "peak_facility_power_mw": item.peak_facility_power_mw,
                        "window_water_gallons_low": item.window_water_gallons_low,
                        "window_water_gallons_high": item.window_water_gallons_high,
                    }
                    for item in record.resource_estimates
                ],
            )

            await self._stage(record, ScreeningStatus.RESEARCHING_SITES, "site_intelligence", 55)
            for site in record.candidates:
                await self.emit(
                    screening_id,
                    "Site Intelligence Agent",
                    "site.research.started",
                    f"Reviewing permitting, power, water, and infrastructure evidence for {site.name}.",
                    site_id=site.id,
                )
                await self.research.enrich(site)
                await self.emit(
                    screening_id,
                    "Site Intelligence Agent",
                    "site.research.completed",
                    f"Recorded {len(site.citations)} cited site-intelligence sources for {site.name}.",
                    site_id=site.id,
                    citation_count=len(site.citations),
                    warnings=site.warnings,
                )
            await self.store.save(record)

            await self._stage(record, ScreeningStatus.SCORING, "deterministic_scoring", 72)
            record.recommendations = score_candidates(
                record.candidates,
                record.request.weights,
                record.request.constraints,
                record.request.cooling,
                record.request.thermal_window,
            )
            await self.store.save(record)
            await self.emit(
                screening_id,
                "Deterministic Scoring Engine",
                "screening.scoring.completed",
                "Applied normalized factor weights, confidence regression, and hard constraints without model-authored scores.",
                scores=[item.model_dump(mode="json") for item in record.recommendations],
            )

            await self._stage(record, ScreeningStatus.AUDITING, "evidence_audit", 84)
            record.audit = self._audit(record)
            await self.store.save(record)
            await self.emit(
                screening_id,
                "Evidence Audit Gate",
                "screening.audit.completed",
                record.audit["summary"],
                status="warning" if record.audit["warnings"] else "success",
                audit=record.audit,
            )
            if not record.audit["passed"]:
                raise RuntimeError(
                    "Evidence audit did not pass; recommendation artifacts were not issued."
                )

            await self._stage(record, ScreeningStatus.REPORTING, "reporting", 92)
            record.summary, record.due_diligence = self._recommend(record)
            record.artifacts = self._write_artifacts(record)
            await self.store.save(record)
            await self.emit(
                screening_id,
                "Recommendation Agent",
                "screening.report.completed",
                "Created the cited investment memo and machine-readable evidence bundle.",
                artifact_ids=[str(item.id) for item in record.artifacts],
            )

            await self._stage(record, ScreeningStatus.COMPLETED, "complete", 100)
            await self.emit(
                screening_id,
                "Screening Coordinator",
                "screening.completed",
                "ThermaSite completed the auditable multi-factor screening.",
            )
        except asyncio.CancelledError:
            record.status = ScreeningStatus.CANCELLED
            record.current_step = "cancelled"
            await self.store.save(record)
            raise
        except Exception as exc:  # noqa: BLE001 -- workflow boundary records safe error
            record.status = ScreeningStatus.FAILED
            record.current_step = "failed"
            record.error = {
                "code": type(exc).__name__.upper(),
                "message": str(exc),
                "retryable": "timeout" in str(exc).lower() or "rate limit" in str(exc).lower(),
            }
            await self.store.save(record)
            await self.emit(
                screening_id,
                "Screening Coordinator",
                "screening.failed",
                str(exc),
                status="error",
            )

    def _resolve_candidates(self, record: ScreeningRecord) -> list[CandidateSite]:
        resolved: list[CandidateSite] = []
        seen: set[str] = set()
        for site_id in record.request.candidate_ids:
            site = get_catalog_site(site_id)
            if site is None:
                raise ValueError(f"Unknown site catalog id: {site_id}")
            if site.id not in seen:
                site.area_sq_mi = record.request.facility.facility_size_acres / 640
                resolved.append(site)
                seen.add(site.id)
        for index, item in enumerate(record.request.candidates):
            site_id = f"custom-{index + 1}-{item.state.lower()}"
            if site_id in seen:
                continue
            resolved.append(
                CandidateSite(
                    id=site_id,
                    name=item.name,
                    metro=item.metro,
                    state=item.state.upper(),
                    latitude=item.latitude,
                    longitude=item.longitude,
                    area_sq_mi=record.request.facility.facility_size_acres / 640,
                    catalog=False,
                    shortlist_reason="User-supplied site retained for direct comparison.",
                )
            )
            seen.add(site_id)
        if record.request.auto_shortlist and not record.request.candidate_ids and not record.request.candidates:
            selected = select_catalog_shortlist(
                record.request.weights,
                record.request.constraints,
                record.request.facility.shortlist_size,
                seen,
            )
            for site in selected:
                site.area_sq_mi = record.request.facility.facility_size_acres / 640
                resolved.append(site)
                seen.add(site.id)
        return resolved

    @staticmethod
    def _build_facility_estimates(record: ScreeningRecord) -> list[ResourceEstimate]:
        estimates: list[ResourceEstimate] = []
        for site in record.candidates:
            if site.thermal is None:
                continue
            polygon = candidate_polygon(site)
            polygon["features"][0]["properties"]["purpose"] = "planned_facility"
            payload = ResourceEstimatorRequest(
                site_id=site.id,
                polygon=polygon,
                it_load_mw=record.request.cooling.it_load_mw,
                utilization=record.request.cooling.utilization,
                baseline_pue=record.request.cooling.baseline_pue,
                reference_temperature_c=record.request.cooling.reference_temperature_c,
                pue_sensitivity_per_c=record.request.cooling.pue_sensitivity_per_c,
                cooling_system=record.request.facility.cooling_system,
                it_density_mw_per_acre=record.request.facility.it_density_mw_per_acre,
            )
            normalized, area_sq_mi = normalize_polygon(
                polygon,
                site.id,
                expected_latitude=site.latitude,
                expected_longitude=site.longitude,
            )
            normalized["features"][0]["properties"]["purpose"] = "planned_facility"
            estimates.append(
                calculate_resource_estimate(
                    payload,
                    normalized,
                    area_sq_mi,
                    site.thermal,
                    record.request.thermal_window,
                )
            )
        return estimates

    async def _acquire_heat(
        self, screening_id: UUID, record: ScreeningRecord, site: CandidateSite
    ) -> None:
        try:
            site.thermal = await self.fortyguard.analyze(site, record.request.thermal_window)
            await self.emit(
                screening_id,
                "Heat Agent",
                "fortyguard.analysis.completed",
                f"FortyGuard returned a street-level thermal layer for {site.name}.",
                site_id=site.id,
                activity_ids=site.thermal.activity_ids,
                mean_temperature_c=site.thermal.mean_temperature_c,
                maximum_temperature_c=site.thermal.maximum_temperature_c,
            )
        except Exception as exc:  # noqa: BLE001 -- one site failure must not discard peers
            site.warnings.append(str(exc))
            await self.emit(
                screening_id,
                "Heat Agent",
                "fortyguard.analysis.failed",
                f"{site.name}: {exc}",
                site_id=site.id,
                status="warning",
                retryable=getattr(exc, "retryable", False),
            )

    async def _backfill_failed_heat_candidates(
        self, screening_id: UUID, record: ScreeningRecord
    ) -> None:
        """Replace failed automatic candidates until five rankable AOIs are available."""

        target = record.request.facility.shortlist_size
        successful = [site for site in record.candidates if site.thermal is not None]
        excluded = {site.id for site in record.candidates}
        while len(successful) < target:
            alternatives = select_catalog_shortlist(
                record.request.weights,
                record.request.constraints,
                1,
                excluded,
            )
            if not alternatives:
                break
            replacement = alternatives[0]
            excluded.add(replacement.id)
            replacement.area_sq_mi = record.request.facility.facility_size_acres / 640
            await self.emit(
                screening_id,
                "Shortlist Agent",
                "screening.candidate.replaced",
                (
                    f"Promoted {replacement.name} after a shortlisted AOI failed "
                    "FortyGuard thermal validation."
                ),
                site_id=replacement.id,
                coordinates=[replacement.longitude, replacement.latitude],
                rationale=replacement.shortlist_reason,
            )
            await self._acquire_heat(screening_id, record, replacement)
            if replacement.thermal is not None:
                successful.append(replacement)
        record.candidates = successful
        if len(successful) < target:
            raise RuntimeError(
                f"Only {len(successful)} of {target} catalog candidates returned rankable FortyGuard thermal evidence."
            )

    @staticmethod
    def _audit(record: ScreeningRecord) -> dict:
        warnings: list[str] = []
        numerical_mismatches: list[str] = []
        recalculated = score_candidates(
            record.candidates,
            record.request.weights,
            record.request.constraints,
            record.request.cooling,
            record.request.thermal_window,
        )
        expected = {item.site_id: item for item in recalculated}
        for result in record.recommendations:
            audit_result = expected[result.site_id]
            if result.score != audit_result.score or result.rank != audit_result.rank:
                numerical_mismatches.append(
                    f"{result.site_id} stored rank/score did not match deterministic recalculation."
                )
        sites_by_id = {site.id: site for site in record.candidates}
        for estimate in record.resource_estimates:
            estimate_site = sites_by_id.get(estimate.site_id)
            if estimate_site is None or estimate_site.thermal is None:
                numerical_mismatches.append(
                    f"{estimate.site_id} facility projection has no matching FortyGuard evidence."
                )
                continue
            reproduced = calculate_resource_estimate(
                ResourceEstimatorRequest(
                    site_id=estimate.site_id,
                    polygon=estimate.polygon,
                    it_load_mw=estimate.it_load_mw,
                    utilization=estimate.utilization,
                    baseline_pue=estimate.baseline_pue,
                    reference_temperature_c=record.request.cooling.reference_temperature_c,
                    pue_sensitivity_per_c=record.request.cooling.pue_sensitivity_per_c,
                    cooling_system=estimate.cooling_system,
                    it_density_mw_per_acre=estimate.it_density_mw_per_acre,
                ),
                estimate.polygon,
                estimate.area_sq_mi,
                estimate_site.thermal,
                record.request.thermal_window,
            )
            if (
                reproduced.average_facility_power_mw != estimate.average_facility_power_mw
                or reproduced.peak_facility_power_mw != estimate.peak_facility_power_mw
                or reproduced.window_water_gallons_high != estimate.window_water_gallons_high
            ):
                numerical_mismatches.append(
                    f"{estimate.site_id} facility projection did not match deterministic recalculation."
                )
        for site in record.candidates:
            if site.thermal is None:
                warnings.append(
                    f"{site.name} is unrankable because FortyGuard evidence is missing."
                )
            elif not site.thermal.activity_ids:
                warnings.append(f"{site.name} thermal evidence is missing FortyGuard activity IDs.")
            if not site.citations:
                warnings.append(f"{site.name} has no non-thermal source citations.")
            citation_urls = {str(item.url) for item in site.citations}
            if (
                site.industrial_energy_price_cents_kwh is not None
                and not any("eia.gov" in url for url in citation_urls)
                and site.catalog
            ):
                warnings.append(f"{site.name} electricity price is missing an EIA citation.")
            if site.water_risk_0_5 is not None and not any(
                "wri.org" in url for url in citation_urls
            ):
                warnings.append(f"{site.name} water-risk proxy is missing Aqueduct attribution.")
            if site.permitting_score is None:
                warnings.append(f"{site.name} permitting readiness remains unknown.")
            if site.evidence:
                unsupported = [
                    fact
                    for fact in site.evidence.facts
                    if str(fact.source_url) not in citation_urls
                ]
                if unsupported:
                    warnings.append(
                        f"{site.name} contains structured facts without preserved citations."
                    )
        warnings.extend(numerical_mismatches)
        return {
            "passed": any(item.rankable for item in record.recommendations)
            and not numerical_mismatches,
            "warnings": warnings,
            "summary": (
                "Evidence audit failed because stored numerical claims did not reproduce."
                if numerical_mismatches
                else "Evidence audit passed with explicit due-diligence warnings."
                if warnings
                else "Evidence audit passed; every ranked site has thermal and non-thermal provenance."
            ),
        }

    @staticmethod
    def _recommend(record: ScreeningRecord) -> tuple[str, list[str]]:
        leader = next(
            (item for item in record.recommendations if item.rank == 1 and item.eligible), None
        )
        if leader is None:
            summary = "No candidate clears the current hard constraints with rankable evidence."
        else:
            site = next(item for item in record.candidates if item.id == leader.site_id)
            summary = (
                f"{site.name} leads the five-market search for this "
                f"{record.request.facility.facility_size_acres:g}-acre, "
                f"{record.request.cooling.it_load_mw:g} MW campus at {leader.score:.1f}/100 with "
                f"{leader.decision_readiness * 100:.0f}% decision readiness. "
                "The result is a comparative diligence signal, not a permit, capacity reservation, or engineering guarantee."
            )
        due = [
            "Obtain a utility load letter and interconnection/capacity study for the intended MW profile.",
            "Confirm zoning, conditional-use requirements, review sequence, fees, and current moratoria with the authority having jurisdiction.",
            "Secure water-provider capacity, conservation, wastewater, and drought-contingency documentation.",
            "Validate parcel ownership, fiber diversity, geotechnical conditions, flood exposure, and emergency access.",
            "Replace the illustrative PUE-temperature coefficient with project engineering assumptions before financial underwriting.",
        ]
        return summary, due

    def _write_artifacts(self, record: ScreeningRecord):
        memo = self._memo(record).encode()
        manifest = record.model_dump_json(indent=2).encode()
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("thermasite_investment_memo.md", memo)
            archive.writestr("screening_manifest.json", manifest)
        return [
            self.artifacts.put_artifact(
                str(record.id),
                "thermasite_investment_memo.md",
                memo,
                "text/markdown",
                "RecommendationAgent",
            ),
            self.artifacts.put_artifact(
                str(record.id),
                "thermasite_evidence_bundle.zip",
                buffer.getvalue(),
                "application/zip",
                "EvidencePackager",
            ),
        ]

    @staticmethod
    def _memo(record: ScreeningRecord) -> str:
        lines = [
            "# ThermaSite investment screening",
            "",
            record.summary or "Screening result pending.",
            "",
            "## Facility profile",
            "",
            f"- Campus footprint: {record.request.facility.facility_size_acres:g} acres",
            f"- IT design density: {record.request.facility.it_density_mw_per_acre:g} MW/acre",
            f"- Planned IT capacity: {record.request.cooling.it_load_mw:g} MW",
            f"- Cooling architecture: {record.request.facility.cooling_system}",
            "- Every finalist was analyzed with the same illustrative footprint area.",
            "",
            "## Ranked shortlist",
        ]
        sites = {item.id: item for item in record.candidates}
        for item in record.recommendations:
            site = sites[item.site_id]
            score = f"{item.score:.1f}" if item.score is not None else "unranked"
            lines.append(
                f"- **{item.rank or '—'}. {site.name}** — {score}/100; "
                f"readiness {item.decision_readiness * 100:.0f}%; eligible: {item.eligible}."
            )
        if record.resource_estimates:
            lines += ["", "## Saved resource-estimator scenarios"]
            for estimate in record.resource_estimates:
                estimate_site = sites.get(estimate.site_id)
                lines.append(
                    f"- **{estimate_site.name if estimate_site else estimate.site_id}** — "
                    f"{estimate.area_acres:.1f} acres, {estimate.cooling_system} cooling, "
                    f"{estimate.average_facility_power_mw:.1f} MW average facility power, and "
                    f"{estimate.window_water_gallons_low:,.0f}–"
                    f"{estimate.window_water_gallons_high:,.0f} gallons of direct water "
                    "in the selected window."
                )
                lines.append(
                    f"  FortyGuard activities: {', '.join(estimate.thermal.activity_ids)}. "
                    "Values are scenario ranges, not engineering forecasts."
                )
        lines += ["", "## What to verify next"]
        lines += [f"- {item}" for item in record.due_diligence]
        lines += ["", "## Sources"]
        for site in record.candidates:
            for citation in site.citations:
                lines.append(f"- {site.name}: [{citation.title}]({citation.url}) — {citation.fact}")
            if site.thermal:
                lines.append(
                    f"- {site.name}: FortyGuard Temperature API activities "
                    f"{', '.join(site.thermal.activity_ids)}."
                )
        lines += [
            "",
            "## Disclaimer",
            "ThermaSite is a comparative screening tool. It does not replace engineering, legal, utility, permitting, water-rights, or financial due diligence.",
        ]
        return "\n".join(lines)

    async def rescore(self, record: ScreeningRecord, payload: RescoreRequest) -> ScreeningRecord:
        if payload.weights is not None:
            record.request.weights = payload.weights
        if payload.cooling is not None:
            record.request.cooling = payload.cooling
        if payload.constraints is not None:
            record.request.constraints = payload.constraints
        record.recommendations = score_candidates(
            record.candidates,
            record.request.weights,
            record.request.constraints,
            record.request.cooling,
            record.request.thermal_window,
        )
        record.summary, record.due_diligence = self._recommend(record)
        await self.store.save(record)
        await self.emit(
            record.id,
            "Deterministic Scoring Engine",
            "screening.rescored",
            "Recalculated the shortlist from persisted evidence without repeating external calls.",
            weights=record.request.weights.normalized(),
        )
        return record

    async def estimate_resources(
        self, record: ScreeningRecord, payload: ResourceEstimatorRequest
    ) -> ResourceEstimate:
        site = next((item for item in record.candidates if item.id == payload.site_id), None)
        if site is None:
            raise ValueError("The selected candidate is not part of this screening")
        polygon, area_sq_mi = normalize_polygon(
            payload.polygon,
            payload.site_id,
            expected_latitude=site.latitude,
            expected_longitude=site.longitude,
        )
        await self.emit(
            record.id,
            "Resource Estimator Agent",
            "estimator.analysis.started",
            f"Submitted the drawn {area_sq_mi * 640:.1f}-acre footprint to FortyGuard.",
            site_id=site.id,
            area_sq_mi=round(area_sq_mi, 6),
            cooling_system=payload.cooling_system,
        )
        thermal = await self.fortyguard.analyze_polygon(
            polygon, f"{site.id}-resource-estimate", record.request.thermal_window
        )
        estimate = calculate_resource_estimate(
            payload, polygon, area_sq_mi, thermal, record.request.thermal_window
        )
        record.resource_estimates.append(estimate)
        record.artifacts = self._write_artifacts(record)
        await self.store.save(record)
        await self.emit(
            record.id,
            "Resource Estimator Agent",
            "estimator.analysis.completed",
            "Calculated auditable power and direct-water scenario ranges from the drawn footprint and FortyGuard heat evidence.",
            estimate_id=str(estimate.id),
            site_id=site.id,
            fortyguard_activity_ids=thermal.activity_ids,
            average_facility_power_mw=estimate.average_facility_power_mw,
            water_gallons_range=[
                estimate.window_water_gallons_low,
                estimate.window_water_gallons_high,
            ],
        )
        return estimate
