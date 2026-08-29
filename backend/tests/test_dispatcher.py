import asyncio

from terraforge.contracts.models import RunRecord, RunStatus
from terraforge.orchestration.dispatcher import WorkflowDispatcher
from terraforge.persistence import RunStore
from terraforge.settings import Settings


class BlockingCoordinator:
    def __init__(self, runs: RunStore):
        self.runs = runs
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def run(self, run_id):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        record = await self.runs.get(run_id)
        record.status = RunStatus.COMPLETED
        await self.runs.save(record)


async def test_duplicate_dispatch_cannot_cross_an_active_workflow_lease(tmp_path):
    settings = Settings(terraforge_data_dir=tmp_path)
    runs = RunStore(settings)
    record = RunRecord(user_query="Investigate a sufficiently detailed habitat monitoring question")
    await runs.create(record)
    coordinator = BlockingCoordinator(runs)
    dispatcher = WorkflowDispatcher(settings, runs, coordinator)

    first = asyncio.create_task(dispatcher.dispatch(record.id, "dispatch-one"))
    await coordinator.started.wait()
    duplicate = await dispatcher.dispatch(record.id, "dispatch-two")
    coordinator.release.set()

    assert duplicate is False
    assert await first is True
    assert coordinator.calls == 1
    completed = await runs.get(record.id)
    assert completed.workflow_attempt == 1
    assert completed.workflow_lease_expires_at is None
