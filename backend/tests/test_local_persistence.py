from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from terraforge.contracts.models import MonitoringMission, RunRecord, utc_now
from terraforge.persistence.missions import MissionStore
from terraforge.persistence.runs import RunStore
from terraforge.settings import Settings


@pytest.mark.asyncio
async def test_concurrent_run_saves_use_independent_atomic_files(tmp_path):
    store = RunStore(Settings(terraforge_data_dir=tmp_path))
    record = RunRecord(user_query="Concurrent persistence test")
    await store.create(record)

    await asyncio.gather(*(store.save(record) for _ in range(20)))

    persisted = await store.get(record.id)
    assert persisted is not None
    assert persisted.user_query == record.user_query
    assert not list((tmp_path / "state").glob("*.tmp"))


@pytest.mark.asyncio
async def test_concurrent_mission_saves_use_independent_atomic_files(tmp_path):
    store = MissionStore(Settings(terraforge_data_dir=tmp_path))
    baseline = RunRecord(user_query="Mission baseline")
    mission = MonitoringMission(
        name="Persistence watch",
        baseline_run_id=baseline.id,
        latest_run_id=baseline.id,
        query=baseline.user_query,
        region="Test habitat",
        next_check_at=utc_now() + timedelta(days=30),
        metric_thresholds={"test_metric": 0.1},
        last_observation_end="2025-12-31",
    )
    await store.create(mission)

    await asyncio.gather(*(store.save(mission) for _ in range(20)))

    persisted = await store.get(mission.id)
    assert persisted is not None
    assert persisted.name == mission.name
    assert not list((tmp_path / "missions").glob("*.tmp"))
