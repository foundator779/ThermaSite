from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from time import monotonic
from uuid import UUID, uuid4

from google import genai
from google.cloud import pubsub_v1
from google.genai import types

from terraforge.contracts.models import (
    BriefingVideoStatus,
    IncidentAudioStatus,
    MediaJob,
    MediaJobStatus,
    MediaJobType,
    ModelUsageRecord,
    RunEvent,
    RunRecord,
    utc_now,
)
from terraforge.persistence import ArtifactStore, MediaJobStore, MissionStore, RunStore
from terraforge.settings import Settings

from .briefing import build_briefing_prompt

LOGGER = logging.getLogger("terraforge.media")


def _clean(value: object, limit: int = 500) -> str:
    return " ".join(str(value).split())[:limit]


def build_lyria_prompt(
    *, habitat: str, severity: str, confidence: float, indicators: list[str]
) -> str:
    """Create a deterministic, sanitized operational-audio prompt."""
    categories: list[str] = []
    for indicator in indicators:
        lowered = indicator.lower()
        category = next(
            (
                name
                for token, name in (
                    ("wildfire", "fire weather"),
                    ("ndvi", "vegetation greenness"),
                    ("ndmi", "vegetation moisture"),
                    ("stress", "vegetation stress"),
                    ("wetland", "wetland condition"),
                    ("water", "water condition"),
                    ("temperature", "climate"),
                    ("precip", "climate"),
                    ("species", "biodiversity evidence"),
                )
                if token in lowered
            ),
            "habitat condition",
        )
        if category not in categories:
            categories.append(category)
    confidence_band = "high" if confidence >= 0.8 else "moderate" if confidence >= 0.6 else "limited"
    safe_habitat = " ".join(habitat.replace("_", " ").split())[:80]
    return (
        "Create a 30-second instrumental operational alert cue for habitat monitoring. "
        f"Context category: {safe_habitat}; incident severity: {_clean(severity, 20)}; "
        f"evidence confidence: {confidence_band}; indicator categories: "
        f"{', '.join(categories[:5]) or 'habitat condition'}. "
        "Use a calm opening, a clearly perceptible attention motif, and a resolved ending. "
        "No vocals, speech, narration, words, species imitation, artist imitation, alarm sirens, "
        "coordinates, place names, or factual claims. Instrumental only."
    )


def _audio_bytes(response: object) -> bytes:
    output_audio = getattr(response, "output_audio", None)
    output_data = getattr(output_audio, "data", None) if output_audio else None
    if isinstance(output_data, bytes) and output_data:
        return output_data
    if isinstance(output_data, str) and output_data:
        return base64.b64decode(output_data)
    for output in getattr(response, "outputs", None) or []:
        inline = getattr(output, "inline_data", None)
        data = getattr(inline, "data", None) if inline else None
        if isinstance(data, bytes) and data:
            return data
        if isinstance(data, str) and data:
            return base64.b64decode(data)
    parts = list(getattr(response, "parts", None) or [])
    if not parts:
        for candidate in getattr(response, "candidates", None) or []:
            parts.extend(getattr(getattr(candidate, "content", None), "parts", None) or [])
    for part in parts:
        inline = getattr(part, "inline_data", None)
        data = getattr(inline, "data", None) if inline else None
        if isinstance(data, bytes) and data:
            return data
        if isinstance(data, str) and data:
            return base64.b64decode(data)
    raise RuntimeError("Lyria returned no playable audio")


class MediaService:
    """Durable Pub/Sub media queue with an equivalent local task adapter."""

    def __init__(
        self,
        settings: Settings,
        runs: RunStore,
        artifacts: ArtifactStore,
        missions: MissionStore | None = None,
        jobs: MediaJobStore | None = None,
        client_factory=None,
    ):
        self.settings = settings
        self.runs = runs
        self.artifacts = artifacts
        self.missions = missions
        self.jobs = jobs or MediaJobStore(settings)
        self.tasks: dict[UUID, asyncio.Task[None]] = {}
        self._client_factory = client_factory or self._build_client
        self._publisher = pubsub_v1.PublisherClient() if settings.cloud_enabled else None
        self._topic = (
            self._publisher.topic_path(settings.gcp_project_id, settings.media_topic)
            if self._publisher
            else None
        )

    @property
    def ready(self) -> bool:
        return self.settings.veo_enabled

    @property
    def lyria_ready(self) -> bool:
        return self.settings.lyria_enabled

    def _build_client(self):
        if not self.settings.google_api_key:
            raise RuntimeError("GOOGLE_API_KEY is not configured")
        return genai.Client(api_key=self.settings.google_api_key.get_secret_value())

    async def check_model(self, model_name: str) -> str:
        """Verify model metadata without triggering billable generation."""
        client = self._client_factory()
        try:
            model = await asyncio.to_thread(client.models.get, model=model_name)
            return model.name or model_name
        finally:
            close = getattr(client, "close", None)
            if close:
                close()

    async def enqueue(self, run_id: UUID) -> RunRecord:
        record = await self.runs.get(run_id)
        if not record:
            raise KeyError(run_id)
        existing = await self.jobs.find(MediaJobType.VEO_FIELD_BRIEFING, run_id)
        if existing and existing.status == MediaJobStatus.COMPLETED:
            return record
        prompt = build_briefing_prompt(record)
        job = existing or MediaJob(
            job_type=MediaJobType.VEO_FIELD_BRIEFING,
            model=self.settings.veo_model,
            run_id=run_id,
            prompt=prompt,
            prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
        )
        if existing and existing.status == MediaJobStatus.FAILED:
            job.attempt_count = 0
            job.provider_operation_name = None
            record.briefing_video_operation_name = None
        job.status = MediaJobStatus.QUEUED
        job.error = None
        job.lease_expires_at = None
        await self.jobs.create(job) if not existing else await self.jobs.save(job)
        record.briefing_video_status = BriefingVideoStatus.QUEUED
        record.briefing_video_error = None
        record.briefing_video_model = self.settings.veo_model
        self._usage(record, "Veo", self.settings.veo_model, "Illustrative field video", "queued")
        await self.runs.save(record)
        await self._event(record.id, "Veo Briefing Agent", "briefing.video.queued", "Queued a durable Veo field briefing job.", job)
        await self._publish(job)
        return record

    async def enqueue_audio(self, mission_id: UUID, alert_id: UUID, run_id: UUID) -> MediaJob:
        if not self.missions:
            raise RuntimeError("Monitoring store is unavailable")
        existing = await self.jobs.find(MediaJobType.LYRIA_INCIDENT_AUDIO, run_id, alert_id)
        if existing and existing.status != MediaJobStatus.FAILED:
            return existing
        mission = await self.missions.get(mission_id)
        record = await self.runs.get(run_id)
        if not mission or not record:
            raise KeyError("Monitoring incident is unavailable")
        alert = next((item for item in mission.alerts if item.id == alert_id), None)
        if not alert:
            raise KeyError(alert_id)
        prompt = build_lyria_prompt(
            habitat=mission.habitat,
            severity=alert.severity,
            confidence=record.confidence or 0,
            indicators=alert.comparison_metrics,
        )
        job = existing or MediaJob(
            job_type=MediaJobType.LYRIA_INCIDENT_AUDIO,
            model=self.settings.lyria_model,
            run_id=run_id,
            mission_id=mission_id,
            alert_id=alert_id,
            prompt=prompt,
            prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
        )
        if existing and existing.status == MediaJobStatus.FAILED:
            job.attempt_count = 0
        job.status = MediaJobStatus.QUEUED
        job.error = None
        job.lease_expires_at = None
        await self.jobs.create(job) if not existing else await self.jobs.save(job)
        alert.audio_status = IncidentAudioStatus.QUEUED
        alert.audio_job_id = job.id
        alert.audio_model = self.settings.lyria_model
        alert.audio_error = None
        self._usage(record, "Lyria", self.settings.lyria_model, "Opt-in incident audio", "queued")
        await self.missions.save(mission)
        await self.runs.save(record)
        await self._event(run_id, "Lyria Habitat Pulse", "incident.audio.queued", "Queued an opt-in Habitat Pulse audio job.", job)
        await self._publish(job)
        return job

    async def _publish(self, job: MediaJob) -> None:
        dispatch_id = str(uuid4())
        message = {"job_id": str(job.id), "dispatch_id": dispatch_id}
        if self._publisher and self._topic:
            future = self._publisher.publish(
                self._topic,
                json.dumps(message, separators=(",", ":")).encode(),
                job_id=str(job.id),
                dispatch_id=dispatch_id,
            )
            await asyncio.to_thread(future.result, timeout=10)
            return
        task = asyncio.create_task(self.dispatch(job.id, dispatch_id), name=f"media-{job.id}")
        self.tasks[job.id] = task
        if job.job_type == MediaJobType.VEO_FIELD_BRIEFING:
            self.tasks[job.run_id] = task
        task.add_done_callback(
            lambda _, job_id=job.id, run_id=job.run_id: (
                self.tasks.pop(job_id, None), self.tasks.pop(run_id, None)
            )
        )

    async def dispatch(self, job_id: UUID, dispatch_id: str) -> bool:
        if not await self.jobs.claim(job_id, dispatch_id):
            return False
        job = await self.jobs.get(job_id)
        if not job:
            return False
        try:
            if job.job_type == MediaJobType.VEO_FIELD_BRIEFING:
                await self._generate_veo(job)
            else:
                await self._generate_lyria(job)
            return True
        except Exception as exc:
            LOGGER.exception("Media job %s failed", job.id)
            job.status = MediaJobStatus.FAILED
            job.error = f"{type(exc).__name__}: {_clean(exc)}"
            job.completed_at = utc_now()
            await self.jobs.save(job)
            await self._mark_failed(job)
            return False
        finally:
            await self.jobs.release(job_id)

    async def _generate_veo(self, job: MediaJob) -> None:
        record = await self.runs.get(job.run_id)
        if not record:
            raise KeyError(job.run_id)
        record.briefing_video_status = BriefingVideoStatus.GENERATING
        self._usage(record, "Veo", job.model, "Illustrative field video", "generating")
        await self.runs.save(record)
        client = self._client_factory()
        try:
            if job.provider_operation_name:
                operation = types.GenerateVideosOperation(name=job.provider_operation_name)
            else:
                operation = await asyncio.to_thread(
                    client.models.generate_videos,
                    model=job.model,
                    prompt=job.prompt,
                    config=types.GenerateVideosConfig(
                        number_of_videos=1, duration_seconds=8, aspect_ratio="16:9",
                        resolution="720p", person_generation="dont_allow", generate_audio=True,
                        negative_prompt="text, labels, logos, people, disasters, sensational imagery",
                    ),
                )
                job.provider_operation_name = operation.name
                record.briefing_video_operation_name = operation.name
                await self.jobs.save(job)
                await self.runs.save(record)
            deadline = monotonic() + self.settings.veo_timeout_seconds
            while not operation.done:
                if monotonic() >= deadline:
                    raise TimeoutError("Veo generation exceeded its configured time limit")
                await asyncio.sleep(self.settings.veo_poll_interval_seconds)
                operation = await asyncio.to_thread(client.operations.get, operation)
            if operation.error:
                raise RuntimeError(f"Veo generation failed: {_clean(operation.error)}")
            videos = operation.response.generated_videos if operation.response else None
            if not videos or not videos[0].video:
                raise RuntimeError("Veo returned no generated video")
            content = await asyncio.to_thread(client.files.download, file=videos[0].video)
            artifact = self.artifacts.put_artifact(str(job.run_id), "veo_habitat_field_briefing.mp4", content, "video/mp4", "Veo Briefing Agent")
            artifact.name = "Veo Habitat Field Briefing"
            record.artifacts = [item for item in record.artifacts if item.id != record.briefing_video_artifact_id]
            record.artifacts.append(artifact)
            record.briefing_video_status = BriefingVideoStatus.COMPLETED
            record.briefing_video_artifact_id = artifact.id
            record.briefing_video_error = None
            job.status = MediaJobStatus.COMPLETED
            job.artifact_id = artifact.id
            job.completed_at = utc_now()
            self._usage(record, "Veo", job.model, "Illustrative field video", "completed", artifact.id)
            await self.jobs.save(job)
            await self.runs.save(record)
            await self._manifest(record)
            await self._event(job.run_id, "Veo Briefing Agent", "briefing.video.completed", "The illustrative Veo field briefing is ready.", job)
        finally:
            close = getattr(client, "close", None)
            if close:
                close()

    async def _generate_lyria(self, job: MediaJob) -> None:
        if not self.missions or not job.mission_id or not job.alert_id:
            raise RuntimeError("Lyria job has no monitoring target")
        mission = await self.missions.get(job.mission_id)
        record = await self.runs.get(job.run_id)
        if not mission or not record:
            raise KeyError("Lyria target disappeared")
        alert = next((item for item in mission.alerts if item.id == job.alert_id), None)
        if not alert:
            raise KeyError(job.alert_id)
        alert.audio_status = IncidentAudioStatus.GENERATING
        self._usage(record, "Lyria", job.model, "Opt-in incident audio", "generating")
        await self.missions.save(mission)
        await self.runs.save(record)
        client = self._client_factory()
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    client.interactions.create,
                    model=job.model,
                    input=job.prompt,
                ),
                timeout=self.settings.lyria_timeout_seconds,
            )
            content = _audio_bytes(response)
            artifact = self.artifacts.put_artifact(str(job.run_id), "lyria_habitat_pulse.mp3", content, "audio/mpeg", "Lyria Habitat Pulse")
            artifact.name = "Lyria Habitat Pulse (SynthID)"
            record.artifacts.append(artifact)
            alert.audio_status = IncidentAudioStatus.COMPLETED
            alert.audio_artifact_id = artifact.id
            alert.audio_error = None
            job.status = MediaJobStatus.COMPLETED
            job.artifact_id = artifact.id
            job.completed_at = utc_now()
            self._usage(record, "Lyria", job.model, "Opt-in incident audio", "completed", artifact.id)
            await self.jobs.save(job)
            await self.missions.save(mission)
            await self.runs.save(record)
            await self._manifest(record)
            await self._event(job.run_id, "Lyria Habitat Pulse", "incident.audio.completed", "The AI-generated Habitat Pulse is ready. It is not scientific evidence.", job)
        finally:
            close = getattr(client, "close", None)
            if close:
                close()

    async def _mark_failed(self, job: MediaJob) -> None:
        record = await self.runs.get(job.run_id)
        if record:
            family = "Veo" if job.job_type == MediaJobType.VEO_FIELD_BRIEFING else "Lyria"
            self._usage(record, family, job.model, "Generative communication artifact", "failed")
            if family == "Veo":
                record.briefing_video_status = BriefingVideoStatus.FAILED
                record.briefing_video_error = job.error
            await self.runs.save(record)
            event_type = (
                "briefing.video.failed"
                if family == "Veo"
                else "incident.audio.failed"
            )
            await self._event(
                job.run_id,
                f"{family} Media Agent",
                event_type,
                "The media job failed and can be retried.",
                job,
            )
        if self.missions and job.mission_id and job.alert_id:
            mission = await self.missions.get(job.mission_id)
            if mission:
                alert = next((item for item in mission.alerts if item.id == job.alert_id), None)
                if alert:
                    alert.audio_status = IncidentAudioStatus.FAILED
                    alert.audio_error = job.error
                    await self.missions.save(mission)

    async def resume_stale(self) -> None:
        now = utc_now()
        for job in await self.jobs.list():
            if job.status in {MediaJobStatus.QUEUED, MediaJobStatus.GENERATING} and (
                not job.lease_expires_at or job.lease_expires_at <= now
            ):
                await self._publish(job)

    async def shutdown(self) -> None:
        for task in list(self.tasks.values()):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    async def _event(self, run_id: UUID, agent: str, event_type: str, message: str, job: MediaJob) -> None:
        await self.runs.append_event(run_id, RunEvent(agent=agent, type=event_type, message=message, payload={"job_id": str(job.id), "model": job.model, "job_type": job.job_type}))

    async def _manifest(self, record: RunRecord) -> None:
        payload = {
            "run_id": str(record.id),
            "generated_at": utc_now().isoformat(),
            "models": [item.model_dump(mode="json") for item in record.model_usage],
            "gemma_audits": [item.model_dump(mode="json") for item in record.gemma_audits],
            "disclosures": {"Veo": "illustrative, not scientific evidence", "Lyria": "AI-generated operational audio with SynthID; not scientific evidence"},
        }
        artifact = self.artifacts.put_artifact(str(record.id), "google_ai_model_manifest.json", json.dumps(payload, indent=2, default=str).encode(), "application/json", "AI Provenance Agent")
        communication = [
            item for item in record.artifacts if item.type in {"video", "audio"}
        ]
        record.artifacts = [
            item
            for item in record.artifacts
            if item.name != artifact.name and item.type not in {"video", "audio"}
        ]
        record.artifacts.append(artifact)
        record.artifacts.extend(communication)
        await self.runs.save(record)

    @staticmethod
    def _usage(record: RunRecord, family: str, model: str, purpose: str, status: str, artifact_id: UUID | None = None) -> None:
        usage = next((item for item in record.model_usage if item.family == family), None)
        if not usage:
            usage = ModelUsageRecord(family=family, model=model, purpose=purpose, status=status)
            record.model_usage.append(usage)
        usage.model = model
        usage.purpose = purpose
        usage.status = status
        usage.last_used_at = utc_now()
        if status in {"completed", "failed"}:
            usage.invocation_count += 1
        if artifact_id and artifact_id not in usage.artifact_ids:
            usage.artifact_ids.append(artifact_id)


class VeoBriefingService(MediaService):
    """Backward-compatible name for the durable multi-model media service."""
