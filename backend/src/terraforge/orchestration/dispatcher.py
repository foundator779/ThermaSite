from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

from google.cloud import pubsub_v1

from terraforge.contracts.models import RunStatus, utc_now
from terraforge.observability import workflow_span
from terraforge.persistence import RunStore
from terraforge.settings import Settings


class WorkflowDispatcher:
    """Durable Pub/Sub dispatch in cloud with an equivalent local task adapter."""

    def __init__(self, settings: Settings, runs: RunStore, coordinator):
        self.settings = settings
        self.runs = runs
        self.coordinator = coordinator
        self.tasks: dict[UUID, asyncio.Task] = {}
        self._publisher = pubsub_v1.PublisherClient() if settings.cloud_enabled else None
        self._topic = (
            self._publisher.topic_path(settings.gcp_project_id, settings.workflow_topic)
            if self._publisher
            else None
        )

    async def enqueue(self, run_id: UUID, reason: str = "run.created") -> str:
        dispatch_id = str(uuid4())
        message = {
            "run_id": str(run_id),
            "dispatch_id": dispatch_id,
            "reason": reason,
            "queued_at": utc_now().isoformat(),
        }
        if self._publisher and self._topic:
            future = self._publisher.publish(
                self._topic,
                json.dumps(message, separators=(",", ":")).encode(),
                run_id=str(run_id),
                dispatch_id=dispatch_id,
            )
            await asyncio.to_thread(future.result, timeout=10)
        else:
            task = asyncio.create_task(
                self.dispatch(run_id, dispatch_id), name=f"terraforge-dispatch-{run_id}"
            )
            self.tasks[run_id] = task
            task.add_done_callback(lambda _: self.tasks.pop(run_id, None))
        return dispatch_id

    async def dispatch(self, run_id: UUID, dispatch_id: str) -> bool:
        claimed = await self.runs.claim_workflow(run_id, dispatch_id)
        if not claimed:
            return False
        try:
            with workflow_span(str(run_id), dispatch_id):
                await self.coordinator.run(run_id)
            completed = await self.runs.get(run_id)
            if (
                completed
                and completed.status == RunStatus.FAILED
                and completed.error
                and completed.error.get("retryable")
                and self.settings.cloud_enabled
            ):
                raise RuntimeError("Retryable workflow failure; request durable redelivery")
            return True
        finally:
            await self.runs.release_workflow(run_id)

    async def resume_stale(self) -> list[UUID]:
        resumed: list[UUID] = []
        now = utc_now()
        terminal = {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
        for record in await self.runs.list(limit=200):
            if record.status in terminal:
                continue
            if record.workflow_lease_expires_at and record.workflow_lease_expires_at > now:
                continue
            await self.enqueue(record.id, reason="workflow.resume")
            resumed.append(record.id)
        return resumed

    async def shutdown(self) -> None:
        for task in list(self.tasks.values()):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)
