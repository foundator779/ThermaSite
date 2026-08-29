import os
from datetime import timedelta
from types import SimpleNamespace

import pytest

from terraforge.contracts.models import (
    IncidentAudioStatus,
    MediaJob,
    MediaJobStatus,
    MediaJobType,
    MonitoringAlert,
    MonitoringMission,
    RunRecord,
    utc_now,
)
from terraforge.media import MediaService, build_lyria_prompt
from terraforge.persistence import ArtifactStore, MediaJobStore, MissionStore, RunStore
from terraforge.settings import Settings

pytestmark = pytest.mark.asyncio


class FakeLyriaClient:
    def __init__(self):
        self.interactions = self

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(output_audio=SimpleNamespace(data=b"ID3-playable-audio"))

    def close(self):
        return None


async def test_lyria_prompt_excludes_coordinates_and_raw_indicator_names():
    prompt = build_lyria_prompt(
        habitat="freshwater_wetland",
        severity="attention",
        confidence=0.81,
        indicators=["ndvi_anomaly", "wildfire_activity", "species_evidence"],
    )
    assert "coordinates" in prompt
    assert "36.3889" not in prompt
    assert "ndvi_anomaly" not in prompt
    assert "instrumental" in prompt.lower()
    assert "No vocals" in prompt


async def test_media_job_store_claim_is_idempotent(tmp_path):
    settings = Settings(terraforge_data_dir=tmp_path)
    store = MediaJobStore(settings)
    run = RunRecord(user_query="Assess habitat condition over the selected research area")
    prompt = "safe prompt"
    job = MediaJob(
        job_type=MediaJobType.VEO_FIELD_BRIEFING,
        model="veo-test",
        run_id=run.id,
        prompt=prompt,
        prompt_sha256="a" * 64,
    )
    await store.create(job)
    assert await store.claim(job.id, "first") is True
    assert await store.claim(job.id, "duplicate") is False


async def test_lyria_audio_is_persisted_and_duplicate_enqueue_reuses_job(tmp_path):
    settings = Settings(google_api_key="test", terraforge_data_dir=tmp_path)
    runs = RunStore(settings)
    missions = MissionStore(settings)
    jobs = MediaJobStore(settings)
    record = RunRecord(user_query="Assess habitat condition over the selected research area")
    record.confidence = 0.82
    await runs.create(record)
    alert = MonitoringAlert(
        title="Vegetation stress review",
        message="A validated threshold was crossed.",
        run_id=record.id,
        comparison_metrics=["ndvi_anomaly"],
    )
    mission = MonitoringMission(
        name="Wetland watch",
        baseline_run_id=record.id,
        latest_run_id=record.id,
        query=record.user_query,
        region="Selected area",
        habitat="freshwater_wetland",
        next_check_at=utc_now() + timedelta(days=30),
        metric_thresholds={"ndvi_anomaly": 0.1},
        indicator_keys=["vegetation_greenness"],
        alerts=[alert],
        audio_alert_enabled=True,
    )
    await missions.create(mission)
    service = MediaService(
        settings,
        runs,
        ArtifactStore(settings),
        missions,
        jobs,
        client_factory=FakeLyriaClient,
    )

    job = await service.enqueue_audio(mission.id, alert.id, record.id)
    await service.tasks[job.id]
    duplicate = await service.enqueue_audio(mission.id, alert.id, record.id)

    saved_job = await jobs.get(job.id)
    saved_mission = await missions.get(mission.id)
    saved_alert = saved_mission.alerts[-1]
    assert duplicate.id == job.id
    assert saved_job.status == MediaJobStatus.COMPLETED
    assert saved_alert.audio_status == IncidentAudioStatus.COMPLETED
    assert saved_alert.audio_artifact_id is not None
    saved_run = await runs.get(record.id)
    audio = next(item for item in saved_run.artifacts if item.type == "audio")
    assert ArtifactStore(settings).read_bytes(audio.uri).startswith(b"ID3")


@pytest.mark.skipif(
    not os.getenv("LIVE_GOOGLE_AI_MODELS"),
    reason="Set LIVE_GOOGLE_AI_MODELS=1 for one real 30-second Lyria clip",
)
async def test_live_lyria_clip_is_nonempty_mp3(tmp_path):
    settings = Settings(terraforge_data_dir=tmp_path)
    if not settings.google_api_key:
        pytest.skip("GOOGLE_API_KEY is not configured")
    runs = RunStore(settings)
    missions = MissionStore(settings)
    record = RunRecord(user_query="Assess habitat condition from validated measurements")
    record.confidence = 0.84
    await runs.create(record)
    alert = MonitoringAlert(
        title="Vegetation stress review",
        message="A validated threshold was crossed.",
        run_id=record.id,
        comparison_metrics=["vegetation_ndvi_anomaly"],
    )
    mission = MonitoringMission(
        name="Habitat watch",
        baseline_run_id=record.id,
        latest_run_id=record.id,
        query=record.user_query,
        region="Selected area",
        habitat="wetland",
        next_check_at=utc_now() + timedelta(days=30),
        metric_thresholds={"vegetation_ndvi_anomaly": 0.1},
        indicator_keys=["vegetation_greenness"],
        alerts=[alert],
        audio_alert_enabled=True,
    )
    await missions.create(mission)
    service = MediaService(settings, runs, ArtifactStore(settings), missions)
    job = await service.enqueue_audio(mission.id, alert.id, record.id)
    await service.tasks[job.id]
    saved = await service.jobs.get(job.id)
    assert saved.status == MediaJobStatus.COMPLETED
    assert saved.artifact_id
    updated = await runs.get(record.id)
    artifact = next(item for item in updated.artifacts if item.id == saved.artifact_id)
    assert len(ArtifactStore(settings).read_bytes(artifact.uri)) > 1024
