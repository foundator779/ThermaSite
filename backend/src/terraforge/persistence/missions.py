from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import UUID

from google.cloud import firestore

from terraforge.contracts.models import (
    FieldInspectionTask,
    MetricComparison,
    MissionCheck,
    MissionCheckStatus,
    MonitoringAlert,
    MonitoringMission,
    RunRecord,
    utc_now,
)
from terraforge.monitoring import build_trigger_directions, direction_for_metric
from terraforge.persistence.local import atomic_write_text
from terraforge.settings import Settings


class MissionStore:
    """Persistent monitoring missions backed by Firestore or durable local JSON."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._missions: dict[UUID, MonitoringMission] = {}
        self._locks: dict[UUID, asyncio.Lock] = {}
        self._write_locks: dict[UUID, asyncio.Lock] = {}
        self._dir = (settings.terraforge_data_dir / "missions").resolve()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._firestore = (
            firestore.AsyncClient(
                project=settings.gcp_project_id, database=settings.firestore_database
            )
            if settings.cloud_enabled
            else None
        )

    async def create(self, mission: MonitoringMission) -> MonitoringMission:
        self._normalize_policy(mission)
        self._missions[mission.id] = mission
        await self.save(mission)
        return mission

    async def get(self, mission_id: UUID) -> MonitoringMission | None:
        if mission_id in self._missions:
            mission = self._missions[mission_id]
            self._normalize_policy(mission)
            return mission
        if self._firestore:
            snapshot = (
                await self._firestore.collection("monitoring_missions")
                .document(str(mission_id))
                .get()
            )
            if snapshot.exists:
                mission = MonitoringMission.model_validate(snapshot.to_dict())
                self._normalize_policy(mission)
                self._missions[mission_id] = mission
                return mission
        path = self._dir / f"{mission_id}.json"
        if path.exists():
            mission = MonitoringMission.model_validate_json(path.read_text(encoding="utf-8"))
            self._normalize_policy(mission)
            self._missions[mission_id] = mission
            return mission
        return None

    async def list(self, limit: int = 50) -> list[MonitoringMission]:
        missions: dict[UUID, MonitoringMission] = dict(self._missions)
        if self._firestore:
            snapshots = self._firestore.collection("monitoring_missions").stream()
            async for snapshot in snapshots:
                mission = MonitoringMission.model_validate(snapshot.to_dict())
                self._normalize_policy(mission)
                missions[mission.id] = mission
        else:
            for path in self._dir.glob("*.json"):
                mission = MonitoringMission.model_validate_json(path.read_text(encoding="utf-8"))
                self._normalize_policy(mission)
                missions[mission.id] = mission
        return sorted(missions.values(), key=lambda mission: mission.updated_at, reverse=True)[
            :limit
        ]

    async def save(self, mission: MonitoringMission) -> None:
        self._normalize_policy(mission)
        mission.updated_at = utc_now()
        self._missions[mission.id] = mission
        if self._firestore:
            await (
                self._firestore.collection("monitoring_missions")
                .document(str(mission.id))
                .set(mission.model_dump(mode="json"))
            )
        else:
            lock = self._write_locks.setdefault(mission.id, asyncio.Lock())
            async with lock:
                path = self._dir / f"{mission.id}.json"
                await atomic_write_text(path, mission.model_dump_json(indent=2))

    async def begin_check(self, mission_id: UUID, run_id: UUID, lease_seconds: int = 900) -> bool:
        """Atomically lease a mission check so duplicate scheduler deliveries cannot duplicate work."""
        if self._firestore:
            reference = self._firestore.collection("monitoring_missions").document(str(mission_id))
            transaction = self._firestore.transaction()

            @firestore.async_transactional
            async def claim(transaction):
                snapshot = await reference.get(transaction=transaction)
                if not snapshot.exists:
                    return False
                mission = MonitoringMission.model_validate(snapshot.to_dict())
                now = utc_now()
                if mission.check_lease_expires_at and mission.check_lease_expires_at > now:
                    return False
                mission.check_lease_expires_at = now + timedelta(seconds=lease_seconds)
                mission.checks.append(
                    MissionCheck(run_id=run_id, status=MissionCheckStatus.RUNNING)
                )
                if run_id not in mission.run_ids:
                    mission.run_ids.append(run_id)
                mission.updated_at = now
                transaction.set(reference, mission.model_dump(mode="json"))
                self._missions[mission_id] = mission
                return True

            return await claim(transaction)

        lock = self._locks.setdefault(mission_id, asyncio.Lock())
        async with lock:
            mission = await self._require(mission_id)
            now = utc_now()
            if mission.check_lease_expires_at and mission.check_lease_expires_at > now:
                return False
            mission.check_lease_expires_at = now + timedelta(seconds=lease_seconds)
            mission.checks.append(MissionCheck(run_id=run_id, status=MissionCheckStatus.RUNNING))
            if run_id not in mission.run_ids:
                mission.run_ids.append(run_id)
            await self.save(mission)
            return True

    async def complete_check(
        self, mission_id: UUID, current: RunRecord, previous: RunRecord
    ) -> MonitoringMission:
        mission = await self._require(mission_id)
        comparisons = self._compare_metrics(mission, previous.metrics, current.metrics)
        meaningful = any(comparison.meaningful for comparison in comparisons)
        check = self._check_for_run(mission, current.id)
        check.status = MissionCheckStatus.COMPLETED
        check.completed_at = utc_now()
        check.meaningful_change = meaningful
        check.comparisons = comparisons
        changed = [comparison for comparison in comparisons if comparison.meaningful]
        if changed:
            check.summary = f"Detected {len(changed)} metric changes above mission thresholds."
        else:
            check.summary = "No monitored indicator exceeded its meaningful-change threshold."
        mission.latest_run_id = current.id
        if current.research_spec:
            mission.last_observation_end = current.research_spec.end_date
        mission.check_lease_expires_at = None
        mission.next_check_at = utc_now() + timedelta(days=mission.cadence_days)
        await self.save(mission)
        return mission

    async def record_action(
        self,
        mission_id: UUID,
        run_id: UUID,
        action: dict[str, object],
    ) -> MonitoringMission:
        """Persist an ADK action decision after deterministic comparison and review."""
        mission = await self._require(mission_id)
        check = self._check_for_run(mission, run_id)
        changed_metrics = [item.metric for item in check.comparisons if item.meaningful]
        create_incident = bool(action.get("create_incident"))
        duplicate = create_incident and any(
            alert.severity == "attention"
            and alert.comparison_metrics == changed_metrics
            and alert.title == str(action.get("title"))
            for alert in mission.alerts
        )
        if duplicate:
            alert = MonitoringAlert(
                severity="info",
                title="Duplicate monitoring signal suppressed",
                message=(
                    "The same validated indicator set already has an open monitoring incident."
                ),
                run_id=run_id,
                comparison_metrics=changed_metrics,
            )
        else:
            field_actions = [str(item) for item in action.get("field_actions", [])]
            coordinates = mission.study_area.center if mission.study_area else None
            alert = MonitoringAlert(
                severity="attention" if create_incident else "info",
                title=str(action.get("title") or "Monitoring check completed"),
                message=str(action.get("message") or check.summary or "Monitoring completed."),
                run_id=run_id,
                metric=changed_metrics[0] if len(changed_metrics) == 1 else None,
                comparison_metrics=changed_metrics,
                field_actions=field_actions,
                field_tasks=[
                    FieldInspectionTask(
                        id=f"field-task-{index + 1}",
                        title=(instruction.split(".", 1)[0] or f"Field inspection {index + 1}")[:100],
                        instructions=instruction,
                        priority="urgent" if create_incident and index == 0 else "priority",
                        coordinates=coordinates,
                    )
                    for index, instruction in enumerate(field_actions)
                ],
            )
        mission.alerts.append(alert)
        await self.save(mission)
        return mission

    async def fail_check(self, mission_id: UUID, run_id: UUID, error: str) -> None:
        mission = await self._require(mission_id)
        check = self._check_for_run(mission, run_id)
        check.status = MissionCheckStatus.FAILED
        check.completed_at = utc_now()
        check.error = error
        check.summary = "Monitoring check failed before a scientific comparison was available."
        mission.check_lease_expires_at = None
        await self.save(mission)

    async def _require(self, mission_id: UUID) -> MonitoringMission:
        mission = await self.get(mission_id)
        if mission is None:
            raise KeyError(mission_id)
        return mission

    @staticmethod
    def _check_for_run(mission: MonitoringMission, run_id: UUID) -> MissionCheck:
        check = next((item for item in mission.checks if item.run_id == run_id), None)
        if check is None:
            check = MissionCheck(run_id=run_id, status=MissionCheckStatus.RUNNING)
            mission.checks.append(check)
        return check

    @staticmethod
    def _normalize_policy(mission: MonitoringMission) -> None:
        """Hydrate defaults for missions created before trigger directions were persisted."""
        retained = {
            key: value
            for key, value in mission.trigger_directions.items()
            if key in mission.indicator_keys
        }
        mission.trigger_directions = build_trigger_directions(
            mission.indicator_keys,
            retained,
        )

    @staticmethod
    def _compare_metrics(
        mission: MonitoringMission,
        previous: dict[str, object],
        current: dict[str, object],
    ) -> list[MetricComparison]:
        comparisons: list[MetricComparison] = []
        for metric, threshold in mission.metric_thresholds.items():
            old = previous.get(metric)
            new = current.get(metric)
            if not isinstance(old, (int, float)) or not isinstance(new, (int, float)):
                continue
            delta = float(new) - float(old)
            direction = direction_for_metric(
                mission.indicator_keys,
                mission.trigger_directions,
                metric,
            )
            meaningful = {
                "INCREASE": delta >= threshold,
                "DECREASE": delta <= -threshold,
                "EITHER": abs(delta) >= threshold,
            }[direction.value]
            comparisons.append(
                MetricComparison(
                    metric=metric,
                    previous_value=float(old),
                    current_value=float(new),
                    absolute_delta=delta,
                    threshold=threshold,
                    direction=direction,
                    meaningful=meaningful,
                )
            )
        return comparisons
