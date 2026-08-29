from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from terraforge.agents.interpreter import interpret_research_question
from terraforge.contracts.models import (
    MonitoringMission,
    MonitoringTriggerDirection,
    RunEvent,
    RunRecord,
    RunStatus,
    utc_now,
)
from terraforge.knowledge import discover
from terraforge.main import app
from terraforge.persistence import MissionStore
from terraforge.settings import Settings


def completed_run() -> RunRecord:
    query = (
        "How has climate around Utqiagvik changed from 2005 to 2025 by season, "
        "significance, and sea ice?"
    )
    spec = interpret_research_question(query)
    return RunRecord(
        status=RunStatus.COMPLETED,
        user_query=query,
        research_spec=spec,
        selected_datasets=[
            candidate
            for candidate in discover(spec)
            if candidate.data_role in spec.required_data_roles
        ],
        current_step="complete",
        progress=100,
        final_summary="Regional warming was validated against three authoritative sources.",
        metrics={
            "regional_temperature_trend_c_per_decade": 0.42,
            "regional_temperature_p_value": 0.01,
            "sea_ice_trend_mkm2_per_decade": -0.31,
            "temperature_sea_ice_correlation": -0.72,
        },
        events=[
            RunEvent(
                agent="ScientificValidationAgent",
                type="scientific_validation.completed",
                message="Validated finite statistics and expected outputs.",
            )
        ],
    )


def test_completed_run_can_become_a_monitoring_mission_and_expose_evidence():
    with TestClient(app) as client:
        source = completed_run()
        client.portal.call(client.app.state.runs.create, source)

        options_response = client.get(f"/api/v1/runs/{source.id}/monitoring-policy/options")
        assert options_response.status_code == 200
        options = options_response.json()
        assert options["default_cadence_days"] == 30
        assert [item["days"] for item in options["cadence_presets"]] == [1, 7, 30, 90]
        assert {item["key"] for item in options["available_indicators"]} == {
            "temperature_trend",
            "sea_ice",
        }
        assert options["default_indicator_keys"] == ["sea_ice", "temperature_trend"]

        response = client.post(
            "/api/v1/missions",
            json={
                "source_run_id": str(source.id),
                "cadence_days": 14,
                "sensitivity": "HIGH",
                "indicator_keys": ["temperature_trend"],
                "metric_thresholds": {"regional_temperature_trend_c_per_decade": 0.075},
                "trigger_directions": {"temperature_trend": "INCREASE"},
                "objective": "Flag meaningful climate changes for field review.",
            },
        )
        assert response.status_code == 201
        mission_id = response.json()["mission_id"]

        mission = client.get(f"/api/v1/missions/{mission_id}").json()
        assert mission["status"] == "ACTIVE"
        assert mission["baseline_run_id"] == str(source.id)
        assert mission["cadence_days"] == 14
        assert mission["sensitivity"] == "HIGH"
        assert mission["indicator_keys"] == ["temperature_trend"]
        assert mission["metric_thresholds"]["regional_temperature_trend_c_per_decade"] == 0.075
        assert mission["trigger_directions"] == {"temperature_trend": "INCREASE"}

        updated = client.patch(
            f"/api/v1/missions/{mission_id}",
            json={"status": "PAUSED", "sensitivity": "BALANCED"},
        )
        assert updated.status_code == 200
        assert updated.json()["status"] == "PAUSED"
        assert updated.json()["metric_thresholds"]["regional_temperature_trend_c_per_decade"] == 0.1
        assert updated.json()["trigger_directions"] == {"temperature_trend": "INCREASE"}

        evidence = client.get(f"/api/v1/runs/{source.id}/evidence")
        assert evidence.status_code == 200
        payload = evidence.json()
        assert payload["validation_status"] == "validated"
        assert any(node["kind"] == "claim" for node in payload["nodes"])
        assert sum(node["kind"] == "dataset" for node in payload["nodes"]) == 3
        assert any(link["relationship"] == "supported by" for link in payload["links"])


@pytest.mark.asyncio
async def test_mission_comparison_creates_a_threshold_alert(tmp_path):
    settings = Settings(terraforge_data_dir=tmp_path)
    store = MissionStore(settings)
    baseline = completed_run()
    current = baseline.model_copy(deep=True)
    current.id = RunRecord(user_query="placeholder").id
    current.metrics["regional_temperature_trend_c_per_decade"] = 0.68
    mission = MonitoringMission(
        name="North Slope habitat watch",
        baseline_run_id=baseline.id,
        latest_run_id=baseline.id,
        query=baseline.user_query,
        region=baseline.research_spec.region,
        cadence_days=30,
        next_check_at=utc_now() + timedelta(days=30),
        metric_thresholds={"regional_temperature_trend_c_per_decade": 0.1},
        run_ids=[baseline.id],
    )
    await store.create(mission)
    await store.begin_check(mission.id, current.id)
    updated = await store.complete_check(mission.id, current=current, previous=baseline)
    updated = await store.record_action(
        mission.id,
        current.id,
        {
            "create_incident": True,
            "title": "Meaningful habitat indicator change",
            "message": "The validated temperature indicator exceeded the monitoring threshold.",
            "field_actions": ["Review the station and regional source comparison."],
        },
    )

    assert updated.checks[0].meaningful_change is True
    assert updated.checks[0].comparisons[0].absolute_delta == pytest.approx(0.26)
    assert updated.alerts[0].severity == "attention"
    assert updated.alerts[0].field_actions
    assert updated.alerts[0].field_tasks[0].priority == "urgent"
    assert updated.alerts[0].field_tasks[0].instructions.startswith("Review the station")


@pytest.mark.parametrize(
    ("direction", "current_value", "meaningful"),
    [
        (MonitoringTriggerDirection.INCREASE, 0.55, True),
        (MonitoringTriggerDirection.INCREASE, 0.25, False),
        (MonitoringTriggerDirection.DECREASE, 0.25, True),
        (MonitoringTriggerDirection.DECREASE, 0.55, False),
        (MonitoringTriggerDirection.EITHER, 0.25, True),
        (MonitoringTriggerDirection.EITHER, 0.55, True),
    ],
)
def test_monitoring_comparison_respects_trigger_direction(direction, current_value, meaningful):
    baseline = completed_run()
    mission = MonitoringMission(
        name="Directional habitat watch",
        baseline_run_id=baseline.id,
        latest_run_id=baseline.id,
        query=baseline.user_query,
        region=baseline.research_spec.region,
        indicator_keys=["temperature_trend"],
        next_check_at=utc_now() + timedelta(days=30),
        metric_thresholds={"regional_temperature_trend_c_per_decade": 0.1},
        trigger_directions={"temperature_trend": direction},
    )

    comparisons = MissionStore._compare_metrics(
        mission,
        {"regional_temperature_trend_c_per_decade": 0.4},
        {"regional_temperature_trend_c_per_decade": current_value},
    )

    assert comparisons[0].direction == direction
    assert comparisons[0].meaningful is meaningful


def test_policy_update_removes_stale_thresholds_and_validates_values():
    with TestClient(app) as client:
        source = completed_run()
        client.portal.call(client.app.state.runs.create, source)
        created = client.post(
            "/api/v1/missions",
            json={
                "source_run_id": str(source.id),
                "indicator_keys": ["temperature_trend", "sea_ice"],
                "trigger_directions": {
                    "temperature_trend": "INCREASE",
                    "sea_ice": "DECREASE",
                },
            },
        )
        mission_id = created.json()["mission_id"]
        before_update = utc_now()
        updated = client.patch(
            f"/api/v1/missions/{mission_id}",
            json={
                "cadence_days": 17,
                "indicator_keys": ["temperature_trend"],
                "metric_thresholds": {"regional_temperature_trend_c_per_decade": 0.125},
                "trigger_directions": {"temperature_trend": "EITHER"},
            },
        )
        assert updated.status_code == 200
        payload = updated.json()
        assert payload["metric_thresholds"] == {"regional_temperature_trend_c_per_decade": 0.125}
        assert payload["trigger_directions"] == {"temperature_trend": "EITHER"}
        assert payload["cadence_days"] == 17
        assert payload["next_check_at"] > before_update.isoformat()

        invalid = client.patch(
            f"/api/v1/missions/{mission_id}",
            json={"metric_thresholds": {"regional_temperature_trend_c_per_decade": 0}},
        )
        assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_legacy_mission_hydrates_smart_trigger_defaults(tmp_path):
    store = MissionStore(Settings(terraforge_data_dir=tmp_path))
    baseline = completed_run()
    mission = MonitoringMission(
        name="Legacy habitat watch",
        baseline_run_id=baseline.id,
        latest_run_id=baseline.id,
        query=baseline.user_query,
        region=baseline.research_spec.region,
        indicator_keys=["sea_ice"],
        next_check_at=utc_now() + timedelta(days=30),
        metric_thresholds={"sea_ice_trend_mkm2_per_decade": 0.05},
    )
    mission_path = tmp_path / "missions" / f"{mission.id}.json"
    mission_path.parent.mkdir(parents=True, exist_ok=True)
    mission_path.write_text(
        mission.model_dump_json(exclude={"trigger_directions"}),
        encoding="utf-8",
    )

    loaded = await store.get(mission.id)

    assert loaded is not None
    assert loaded.trigger_directions == {"sea_ice": MonitoringTriggerDirection.DECREASE}
