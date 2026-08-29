from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import UUID

from google.cloud import firestore

from terraforge.contracts.models import RunEvent, RunRecord, utc_now
from terraforge.persistence.local import atomic_write_text
from terraforge.settings import Settings


class RunStore:
    """Firestore in cloud; durable JSON plus in-process subscriptions in local development."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._runs: dict[UUID, RunRecord] = {}
        self._conditions: dict[UUID, asyncio.Condition] = {}
        self._write_locks: dict[UUID, asyncio.Lock] = {}
        self._dir = (settings.terraforge_data_dir / "state").resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._firestore = (
            firestore.AsyncClient(
                project=settings.gcp_project_id, database=settings.firestore_database
            )
            if settings.cloud_enabled
            else None
        )

    async def create(self, record: RunRecord) -> RunRecord:
        self._runs[record.id] = record
        self._conditions[record.id] = asyncio.Condition()
        await self.save(record)
        return record

    async def get(self, run_id: UUID) -> RunRecord | None:
        if run_id in self._runs:
            return self._runs[run_id]
        if self._firestore:
            snapshot = await self._firestore.collection("runs").document(str(run_id)).get()
            if snapshot.exists:
                record = RunRecord.model_validate(snapshot.to_dict())
                self._runs[run_id] = record
                self._conditions[run_id] = asyncio.Condition()
                return record
        path = self._dir / f"{run_id}.json"
        if path.exists():
            record = RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
            self._runs[run_id] = record
            self._conditions[run_id] = asyncio.Condition()
            return record
        return None

    async def list(self, limit: int = 50) -> list[RunRecord]:
        records: dict[UUID, RunRecord] = dict(self._runs)
        if self._firestore:
            snapshots = self._firestore.collection("runs").stream()
            async for snapshot in snapshots:
                record = RunRecord.model_validate(snapshot.to_dict())
                records[record.id] = record
        else:
            for path in self._dir.glob("*.json"):
                record = RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
                records[record.id] = record
        return sorted(records.values(), key=lambda record: record.updated_at, reverse=True)[:limit]

    async def save(self, record: RunRecord) -> None:
        record.updated_at = utc_now()
        self._runs[record.id] = record
        if self._firestore:
            await (
                self._firestore.collection("runs")
                .document(str(record.id))
                .set(record.model_dump(mode="json"))
            )
        else:
            lock = self._write_locks.setdefault(record.id, asyncio.Lock())
            async with lock:
                path = self._dir / f"{record.id}.json"
                await atomic_write_text(path, record.model_dump_json(indent=2))
        condition = self._conditions.setdefault(record.id, asyncio.Condition())
        async with condition:
            condition.notify_all()

    async def append_event(self, run_id: UUID, event: RunEvent) -> None:
        record = await self.get(run_id)
        if record is None:
            raise KeyError(run_id)
        record.events.append(event)
        if self._firestore:
            await (
                self._firestore.collection("runs")
                .document(str(run_id))
                .collection("events")
                .document(str(event.id))
                .set(event.model_dump(mode="json"))
            )
        await self.save(record)

    async def claim_workflow(
        self, run_id: UUID, dispatch_id: str, lease_seconds: int = 900
    ) -> bool:
        """Atomically claim a workflow dispatch; duplicate Pub/Sub deliveries become no-ops."""
        if self._firestore:
            reference = self._firestore.collection("runs").document(str(run_id))
            transaction = self._firestore.transaction()

            @firestore.async_transactional
            async def claim(transaction):
                snapshot = await reference.get(transaction=transaction)
                if not snapshot.exists:
                    return False
                record = RunRecord.model_validate(snapshot.to_dict())
                now = utc_now()
                if record.status.value in {"COMPLETED", "CANCELLED"}:
                    return False
                if record.workflow_lease_expires_at and record.workflow_lease_expires_at > now:
                    return False
                record.workflow_dispatch_id = dispatch_id
                record.workflow_attempt += 1
                record.workflow_started_at = record.workflow_started_at or now
                record.workflow_lease_expires_at = now + timedelta(seconds=lease_seconds)
                record.updated_at = now
                transaction.set(reference, record.model_dump(mode="json"))
                self._runs[run_id] = record
                return True

            return await claim(transaction)

        lock = self._conditions.setdefault(run_id, asyncio.Condition())
        async with lock:
            record = await self.get(run_id)
            if record is None or record.status.value in {"COMPLETED", "CANCELLED"}:
                return False
            now = utc_now()
            if record.workflow_lease_expires_at and record.workflow_lease_expires_at > now:
                return False
            record.workflow_dispatch_id = dispatch_id
            record.workflow_attempt += 1
            record.workflow_started_at = record.workflow_started_at or now
            record.workflow_lease_expires_at = now + timedelta(seconds=lease_seconds)
            # Avoid calling save while holding the same condition lock.
            self._runs[run_id] = record
            write_lock = self._write_locks.setdefault(run_id, asyncio.Lock())
            async with write_lock:
                path = self._dir / f"{run_id}.json"
                await atomic_write_text(path, record.model_dump_json(indent=2))
            return True

    async def release_workflow(self, run_id: UUID) -> None:
        record = await self.get(run_id)
        if record is None:
            return
        record.workflow_lease_expires_at = None
        if record.status.value in {"COMPLETED", "FAILED", "CANCELLED"}:
            record.workflow_completed_at = utc_now()
        await self.save(record)

    async def wait_for_events(
        self, run_id: UUID, known_count: int, timeout: float = 15
    ) -> RunRecord:
        record = await self.get(run_id)
        if record is None or len(record.events) > known_count:
            return record
        condition = self._conditions.setdefault(run_id, asyncio.Condition())
        try:
            async with condition:
                await asyncio.wait_for(condition.wait(), timeout=timeout)
        except TimeoutError:
            pass
        return await self.get(run_id)
