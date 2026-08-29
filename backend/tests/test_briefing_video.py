from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from pydantic import SecretStr

from terraforge.contracts.models import BriefingVideoStatus, RunRecord, RunStatus
from terraforge.main import app
from terraforge.media import VeoBriefingService, build_briefing_prompt
from terraforge.persistence import ArtifactStore, RunStore
from terraforge.settings import Settings


class FakeVeoClient:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.closed = False
        self.prompt = ""
        self.models = SimpleNamespace(generate_videos=self.generate_videos)
        self.operations = SimpleNamespace(get=self.get_operation)
        self.files = SimpleNamespace(download=self.download)

    def generate_videos(self, *, model, prompt, config):
        del model, config
        self.prompt = prompt
        if self.fail:
            raise RuntimeError("provider unavailable")
        return SimpleNamespace(name="operations/video-test", done=False, error=None, response=None)

    def get_operation(self, operation):
        del operation
        video = SimpleNamespace(uri="https://example.invalid/video.mp4")
        generated = SimpleNamespace(video=video)
        response = SimpleNamespace(generated_videos=[generated])
        return SimpleNamespace(
            name="operations/video-test", done=True, error=None, response=response
        )

    def download(self, *, file):
        del file
        return b"synthetic mp4 test bytes"

    def close(self):
        self.closed = True


def completed_run() -> RunRecord:
    return RunRecord(
        user_query="Assess habitat change in the selected area over the last decade.",
        status=RunStatus.COMPLETED,
        progress=100,
        final_summary="Validated wetland evidence indicates a modest seasonal change.",
        scientific_review={"valid": True, "confidence": 0.88},
        metrics={"wetland_inventory_count": 14, "annual_temperature_slope_c_per_year": 0.04},
    )


async def test_veo_briefing_is_persisted_as_an_illustrative_video(tmp_path):
    settings = Settings(
        google_api_key="test-key",
        terraforge_data_dir=tmp_path,
        veo_poll_interval_seconds=0.001,
        veo_timeout_seconds=2,
    )
    runs = RunStore(settings)
    artifacts = ArtifactStore(settings)
    record = completed_run()
    await runs.create(record)
    fake = FakeVeoClient()
    service = VeoBriefingService(settings, runs, artifacts, client_factory=lambda: fake)

    await service.enqueue(record.id)
    task = service.tasks[record.id]
    await task

    saved = await runs.get(record.id)
    assert saved is not None
    assert saved.briefing_video_status == BriefingVideoStatus.COMPLETED
    assert saved.briefing_video_operation_name == "operations/video-test"
    assert saved.briefing_video_artifact_id == saved.artifacts[-1].id
    assert saved.artifacts[-1].type == "video"
    assert saved.artifacts[-1].content_type == "video/mp4"
    assert artifacts.read_bytes(saved.artifacts[-1].uri) == b"synthetic mp4 test bytes"
    assert "illustrative communication asset, not evidence" in fake.prompt
    assert fake.closed


async def test_veo_provider_failure_is_persisted_and_retryable(tmp_path):
    settings = Settings(google_api_key="test-key", terraforge_data_dir=tmp_path)
    runs = RunStore(settings)
    record = completed_run()
    await runs.create(record)
    fake = FakeVeoClient(fail=True)
    service = VeoBriefingService(
        settings, runs, ArtifactStore(settings), client_factory=lambda: fake
    )

    await service.enqueue(record.id)
    task = service.tasks[record.id]
    await task

    saved = await runs.get(record.id)
    assert saved is not None
    assert saved.briefing_video_status == BriefingVideoStatus.FAILED
    assert "provider unavailable" in (saved.briefing_video_error or "")
    assert any(event.type == "briefing.video.failed" for event in saved.events)


def test_briefing_prompt_uses_validated_context_without_claiming_evidence():
    prompt = build_briefing_prompt(completed_run())
    assert "Validated wetland evidence" in prompt
    assert "wetland_inventory_count: 14" in prompt
    assert "not evidence" in prompt
    assert "do not dramatize change" in prompt


def test_briefing_endpoint_requires_validation_and_enqueues(monkeypatch):
    with TestClient(app) as client:
        record = completed_run()
        client.app.state.runs._runs[record.id] = record
        client.app.state.settings.google_api_key = SecretStr("test-key")

        async def enqueue(run_id):
            assert run_id == record.id
            record.briefing_video_status = BriefingVideoStatus.QUEUED
            return record

        monkeypatch.setattr(client.app.state.briefings, "enqueue", enqueue)
        response = client.post(f"/api/v1/runs/{record.id}/briefing-video")

        assert response.status_code == 202
        assert response.json()["status"] == "QUEUED"
        assert response.json()["model"].startswith("veo-")


def test_briefing_endpoint_rejects_an_unvalidated_run():
    with TestClient(app) as client:
        record = RunRecord(user_query="Unvalidated run", status=RunStatus.COMPLETED)
        client.app.state.runs._runs[record.id] = record
        response = client.post(f"/api/v1/runs/{record.id}/briefing-video")
        assert response.status_code == 409
