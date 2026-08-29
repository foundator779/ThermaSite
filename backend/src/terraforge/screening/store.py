from __future__ import annotations

import asyncio
from uuid import UUID

from google.cloud import firestore

from terraforge.contracts.models import RunEvent
from terraforge.persistence.local import atomic_write_text
from terraforge.settings import Settings

from .models import ScreeningRecord, utc_now


class ScreeningStore:
    """Firestore in production and durable local JSON during development."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._records: dict[UUID, ScreeningRecord] = {}
        self._conditions: dict[UUID, asyncio.Condition] = {}
        self._write_locks: dict[UUID, asyncio.Lock] = {}
        self._dir = (settings.terraforge_data_dir / "screenings").resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._firestore = (
            firestore.AsyncClient(
                project=settings.gcp_project_id, database=settings.firestore_database
            )
            if settings.cloud_enabled
            else None
        )

    async def create(self, record: ScreeningRecord) -> ScreeningRecord:
        self._records[record.id] = record
        self._conditions[record.id] = asyncio.Condition()
        await self.save(record)
        return record

    async def get(self, screening_id: UUID) -> ScreeningRecord | None:
        if screening_id in self._records:
            return self._records[screening_id]
        if self._firestore:
            snapshot = (
                await self._firestore.collection("screenings").document(str(screening_id)).get()
            )
            if snapshot.exists:
                record = self._decode_document(snapshot.to_dict())
                self._records[record.id] = record
                self._conditions[record.id] = asyncio.Condition()
                return record
        path = self._dir / f"{screening_id}.json"
        if path.exists():
            record = ScreeningRecord.model_validate_json(path.read_text(encoding="utf-8"))
            self._records[record.id] = record
            self._conditions[record.id] = asyncio.Condition()
            return record
        return None

    async def list(self, limit: int = 50, owner_id: UUID | None = None) -> list[ScreeningRecord]:
        records = dict(self._records)
        if self._firestore:
            async for snapshot in self._firestore.collection("screenings").stream():
                record = self._decode_document(snapshot.to_dict())
                records[record.id] = record
        else:
            for path in self._dir.glob("*.json"):
                record = ScreeningRecord.model_validate_json(path.read_text(encoding="utf-8"))
                records[record.id] = record
        visible = (
            [item for item in records.values() if item.owner_id == owner_id]
            if owner_id is not None
            else list(records.values())
        )
        return sorted(visible, key=lambda item: item.updated_at, reverse=True)[:limit]

    async def save(self, record: ScreeningRecord) -> None:
        record.updated_at = utc_now()
        self._records[record.id] = record
        if self._firestore:
            await (
                self._firestore.collection("screenings")
                .document(str(record.id))
                .set(
                    {
                        # Firestore rejects GeoJSON coordinate arrays nested inside feature
                        # arrays. Persisting the validated record as JSON preserves the exact
                        # provider response while keeping queryable ownership/status metadata.
                        "payload": record.model_dump_json(),
                        "owner_id": str(record.owner_id) if record.owner_id else None,
                        "status": record.status.value,
                        "updated_at": record.updated_at,
                    }
                )
            )
        else:
            lock = self._write_locks.setdefault(record.id, asyncio.Lock())
            async with lock:
                await atomic_write_text(
                    self._dir / f"{record.id}.json", record.model_dump_json(indent=2)
                )
        condition = self._conditions.setdefault(record.id, asyncio.Condition())
        async with condition:
            condition.notify_all()

    @staticmethod
    def _decode_document(document: dict) -> ScreeningRecord:
        payload = document.get("payload")
        if isinstance(payload, str):
            return ScreeningRecord.model_validate_json(payload)
        # Compatibility with records written before the GeoJSON-safe envelope.
        return ScreeningRecord.model_validate(document)

    async def append_event(self, screening_id: UUID, event: RunEvent) -> None:
        record = await self.get(screening_id)
        if record is None:
            raise KeyError(screening_id)
        record.events.append(event)
        await self.save(record)

    async def wait_for_events(
        self, screening_id: UUID, known_count: int, timeout: float = 15
    ) -> ScreeningRecord | None:
        record = await self.get(screening_id)
        if record is None or len(record.events) > known_count:
            return record
        condition = self._conditions.setdefault(screening_id, asyncio.Condition())
        try:
            async with condition:
                await asyncio.wait_for(condition.wait(), timeout=timeout)
        except TimeoutError:
            pass
        return await self.get(screening_id)
