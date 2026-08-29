from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import UUID

from google.cloud import firestore

from terraforge.contracts.models import MediaJob, MediaJobStatus, MediaJobType, utc_now
from terraforge.persistence.local import atomic_write_text
from terraforge.settings import Settings


class MediaJobStore:
    """Durable, idempotent media-job state for local and Cloud Run execution."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._jobs: dict[UUID, MediaJob] = {}
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._dir = (settings.terraforge_data_dir / "media_jobs").resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._firestore = (
            firestore.AsyncClient(
                project=settings.gcp_project_id, database=settings.firestore_database
            )
            if settings.cloud_enabled
            else None
        )

    async def create(self, job: MediaJob) -> MediaJob:
        existing = await self.find(job.job_type, job.run_id, job.alert_id)
        if existing:
            return existing
        await self.save(job)
        return job

    async def get(self, job_id: UUID) -> MediaJob | None:
        if job_id in self._jobs:
            return self._jobs[job_id]
        if self._firestore:
            snapshot = await self._firestore.collection("media_jobs").document(str(job_id)).get()
            if snapshot.exists:
                job = MediaJob.model_validate(snapshot.to_dict())
                self._jobs[job_id] = job
                return job
        path = self._dir / f"{job_id}.json"
        if path.exists():
            job = MediaJob.model_validate_json(path.read_text(encoding="utf-8"))
            self._jobs[job_id] = job
            return job
        return None

    async def list(self, limit: int = 200) -> list[MediaJob]:
        jobs = dict(self._jobs)
        if self._firestore:
            async for snapshot in self._firestore.collection("media_jobs").stream():
                job = MediaJob.model_validate(snapshot.to_dict())
                jobs[job.id] = job
        else:
            for path in self._dir.glob("*.json"):
                job = MediaJob.model_validate_json(path.read_text(encoding="utf-8"))
                jobs[job.id] = job
        return sorted(jobs.values(), key=lambda item: item.updated_at, reverse=True)[:limit]

    async def find(
        self, job_type: MediaJobType, run_id: UUID, alert_id: UUID | None = None
    ) -> MediaJob | None:
        return next(
            (
                job
                for job in await self.list()
                if job.job_type == job_type
                and job.run_id == run_id
                and job.alert_id == alert_id
            ),
            None,
        )

    async def save(self, job: MediaJob) -> None:
        job.updated_at = utc_now()
        self._jobs[job.id] = job
        if self._firestore:
            await self._firestore.collection("media_jobs").document(str(job.id)).set(
                job.model_dump(mode="json")
            )
            return
        lock = self._locks.setdefault(job.id, asyncio.Lock())
        async with lock:
            await atomic_write_text(
                self._dir / f"{job.id}.json", job.model_dump_json(indent=2)
            )

    async def claim(self, job_id: UUID, dispatch_id: str, lease_seconds: int = 900) -> bool:
        if self._firestore:
            reference = self._firestore.collection("media_jobs").document(str(job_id))
            transaction = self._firestore.transaction()

            @firestore.async_transactional
            async def claim_job(transaction):
                snapshot = await reference.get(transaction=transaction)
                if not snapshot.exists:
                    return False
                job = MediaJob.model_validate(snapshot.to_dict())
                now = utc_now()
                if job.status == MediaJobStatus.COMPLETED:
                    return False
                if job.lease_expires_at and job.lease_expires_at > now:
                    return False
                if job.attempt_count >= self.settings.max_media_attempts:
                    return False
                job.status = MediaJobStatus.GENERATING
                job.dispatch_id = dispatch_id
                job.attempt_count += 1
                job.started_at = job.started_at or now
                job.lease_expires_at = now + timedelta(seconds=lease_seconds)
                transaction.set(reference, job.model_dump(mode="json"))
                self._jobs[job.id] = job
                return True

            return await claim_job(transaction)

        lock = self._locks.setdefault(job_id, asyncio.Lock())
        async with lock:
            job = await self.get(job_id)
            now = utc_now()
            if (
                not job
                or job.status == MediaJobStatus.COMPLETED
                or (job.lease_expires_at and job.lease_expires_at > now)
                or job.attempt_count >= self.settings.max_media_attempts
            ):
                return False
            job.status = MediaJobStatus.GENERATING
            job.dispatch_id = dispatch_id
            job.attempt_count += 1
            job.started_at = job.started_at or now
            job.lease_expires_at = now + timedelta(seconds=lease_seconds)
            self._jobs[job.id] = job
            await atomic_write_text(
                self._dir / f"{job.id}.json", job.model_dump_json(indent=2)
            )
            return True

    async def release(self, job_id: UUID) -> None:
        job = await self.get(job_id)
        if job:
            job.lease_expires_at = None
            await self.save(job)
