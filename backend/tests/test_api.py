import time

from fastapi.testclient import TestClient

from terraforge.contracts.models import RunRecord
from terraforge.main import app
from terraforge.screening.models import ThermalMetrics


def test_health_and_openapi_are_exposed():
    with TestClient(app) as client:
        health = client.get("/api/v1/healthz").json()
        assert health == {"status": "ok", "service": "thermasite-api"}
        schema = client.get("/openapi.json").json()
        assert "/api/v1/runs" not in schema["paths"]
        assert "/api/v1/screenings" in schema["paths"]
        assert "/api/v1/screenings/{screening_id}/rescore" in schema["paths"]


def test_thermasite_catalog_and_missing_key_state_are_exposed_without_secrets():
    with TestClient(app) as client:
        assert client.post("/api/v1/auth/demo").status_code == 200
        client.app.state.settings.fortyguard_api_key = None
        catalog = client.get("/api/v1/site-catalog")
        assert catalog.status_code == 200
        assert {site["id"] for site in catalog.json()["sites"]} == {
            "phoenix-az",
            "columbus-oh",
            "hillsboro-or",
            "council-bluffs-ia",
            "ashburn-va",
            "dallas-tx",
            "atlanta-ga",
            "reno-nv",
        }
        response = client.post(
            "/api/v1/screenings",
            json={"brief": "Compare the preset data center candidates."},
        )
        assert response.status_code == 503
        assert "FORTYGUARD_API_KEY" in response.json()["detail"]


def test_mocked_preset_screening_completes_and_rescores_without_external_calls():
    class FakeFortyGuard:
        ready = True

        async def analyze(self, site, window):
            if site.id == "atlanta-ga":
                raise RuntimeError("FortyGuard completed without required temperature statistics")
            temperatures = {
                "phoenix-az": (36.0, 47.0, 0.68),
                "columbus-oh": (27.0, 38.0, 0.16),
                "hillsboro-or": (24.0, 34.0, 0.05),
                "council-bluffs-ia": (26.0, 36.0, 0.10),
                "ashburn-va": (29.0, 39.0, 0.20),
                "dallas-tx": (35.0, 46.0, 0.60),
                "atlanta-ga": (33.0, 43.0, 0.40),
                "reno-nv": (31.0, 43.0, 0.35),
            }
            mean, maximum, exceedance = temperatures[site.id]
            return ThermalMetrics(
                activity_ids=[f"mock-{site.id}"],
                mean_temperature_c=mean,
                maximum_temperature_c=maximum,
                exceedance_ratio=exceedance,
                threshold_c=window.threshold_c,
                map_data={"type": "FeatureCollection", "features": []},
            )

        async def analyze_polygon(self, polygon, site_id, window):
            assert polygon["features"][0]["properties"]["purpose"] == "resource_estimator"
            return ThermalMetrics(
                activity_ids=["mock-estimator-tcm", "mock-estimator-exceedance"],
                mean_temperature_c=36,
                maximum_temperature_c=47,
                exceedance_ratio=0.68,
                threshold_c=window.threshold_c,
                map_data={"type": "FeatureCollection", "features": []},
            )

    with TestClient(app) as client:
        demo = client.post("/api/v1/auth/demo")
        assert demo.status_code == 200
        assert demo.json()["user"]["is_demo"] is True
        client.app.state.screening_service.fortyguard = FakeFortyGuard()
        created = client.post(
            "/api/v1/screenings",
            json={"brief": "Compare the preset markets for a 50 MW data center."},
        )
        assert created.status_code == 202
        screening_id = created.json()["screening_id"]
        record = None
        for _ in range(100):
            record = client.get(f"/api/v1/screenings/{screening_id}").json()
            if record["status"] in {"COMPLETED", "FAILED"}:
                break
            time.sleep(0.02)
        assert record["status"] == "COMPLETED"
        assert record["recommendations"][0]["site_id"] == "hillsboro-or"
        assert len(record["candidates"]) == 5
        assert len(record["resource_estimates"]) == 5
        assert "dallas-tx" in {site["id"] for site in record["candidates"]}
        assert "atlanta-ga" not in {site["id"] for site in record["candidates"]}
        assert any(
            event["type"] == "screening.candidate.replaced" for event in record["events"]
        )
        assert record["request"]["facility"]["facility_size_acres"] == 40
        assert record["request"]["cooling"]["it_load_mw"] == 50
        assert all(
            item["polygon"]["features"][0]["properties"]["purpose"]
            == "planned_facility"
            for item in record["resource_estimates"]
        )
        assert record["audit"]["passed"] is True
        assert {artifact["content_type"] for artifact in record["artifacts"]} == {
            "text/markdown",
            "application/zip",
        }

        target = record["candidates"][0]
        lat, lng = target["latitude"], target["longitude"]
        ring = [
            [lng - 0.003, lat - 0.003],
            [lng + 0.003, lat - 0.003],
            [lng + 0.003, lat + 0.003],
            [lng - 0.003, lat + 0.003],
            [lng - 0.003, lat - 0.003],
        ]
        estimated = client.post(
            f"/api/v1/screenings/{screening_id}/estimate",
            json={
                "site_id": target["id"],
                "polygon": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {},
                            "geometry": {"type": "Polygon", "coordinates": [ring]},
                        }
                    ],
                },
                "it_load_mw": 50,
                "cooling_system": "hybrid",
            },
        )
        assert estimated.status_code == 200
        estimate = estimated.json()
        assert estimate["average_facility_power_mw"] > 50
        assert estimate["window_water_gallons_high"] > estimate["window_water_gallons_low"]
        persisted = client.get(f"/api/v1/screenings/{screening_id}").json()
        assert any(item["id"] == estimate["id"] for item in persisted["resource_estimates"])
        assert len(persisted["artifacts"]) == 2

        rescored = client.post(
            f"/api/v1/screenings/{screening_id}/rescore",
            json={
                "weights": {
                    "thermal": 5,
                    "power": 70,
                    "water": 10,
                    "permitting": 10,
                    "logistics": 5,
                }
            },
        )
        assert rescored.status_code == 200
        assert rescored.json()["events"][-1]["type"] == "screening.rescored"

        client.post("/api/v1/auth/logout")
        client.post(
            "/api/v1/auth/register",
            json={
                "name": "Other Builder",
                "email": f"other-{time.time_ns()}@example.com",
                "password": "another-secure-pass",
            },
        )
        assert client.get(f"/api/v1/screenings/{screening_id}").status_code == 404


def test_registration_login_logout_and_protected_screenings():
    unique = str(time.time_ns())
    email = f"builder-{unique}@example.com"
    with TestClient(app) as client:
        assert client.get("/api/v1/screenings").status_code == 401
        registered = client.post(
            "/api/v1/auth/register",
            json={"name": "Data Center Builder", "email": email, "password": "secure-pass-26"},
        )
        assert registered.status_code == 201
        assert registered.json()["token"]
        assert registered.json()["user"]["email"] == email
        assert client.get("/api/v1/auth/me").status_code == 200
        assert client.get("/api/v1/screenings").json() == []

        assert client.post("/api/v1/auth/logout").status_code == 204
        assert client.get("/api/v1/auth/me").status_code == 401
        invalid = client.post(
            "/api/v1/auth/login", json={"email": email, "password": "wrong-password"}
        )
        assert invalid.status_code == 401
        logged_in = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "secure-pass-26"},
        )
        assert logged_in.status_code == 200
        assert client.get("/api/v1/auth/me").json()["name"] == "Data Center Builder"


def test_cors_allows_localhost_and_loopback_frontend_origins():
    with TestClient(app) as client:
        for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
            for method in ("POST", "PATCH"):
                response = client.options(
                    "/api/v1/missions/example",
                    headers={"Origin": origin, "Access-Control-Request-Method": method},
                )
                assert response.status_code == 200
                assert response.headers["access-control-allow-origin"] == origin


def test_runs_and_datasets_can_be_listed():
    with TestClient(app) as client:
        runs = client.get("/api/v1/runs")
        assert runs.status_code == 200
        assert isinstance(runs.json(), list)

        datasets = client.get("/api/v1/datasets")
        assert datasets.status_code == 200
        payload = datasets.json()
        assert payload["registry_version"]
        assert len(payload["datasets"]) == 12
        assert {dataset["data_role"] for dataset in payload["datasets"]} >= {
            "nearby_sea_ice",
            "wetland_water_level",
            "area_station_climate",
            "area_regional_climate",
            "species_biodiversity",
            "wildfire_activity",
            "wetland_inventory",
            "sentinel_2_l2a",
        }


def test_run_creation_requires_gemini_api_key():
    with TestClient(app) as client:
        client.app.state.settings.google_api_key = None
        response = client.post(
            "/api/v1/runs",
            json={"query": "Summarize the long-term climate trend around Utqiagvik, Alaska."},
        )
        assert response.status_code == 503
        assert "GOOGLE_API_KEY" in response.json()["detail"]


def test_artifact_download_preserves_the_file_extension():
    with TestClient(app) as client:
        record = RunRecord(user_query="Download contract test")
        artifact = client.app.state.artifacts.put_artifact(
            str(record.id),
            "habiwatch_reproducibility_bundle.zip",
            b"PK test bundle",
            "application/zip",
            "test",
        )
        record.artifacts.append(artifact)
        client.app.state.runs._runs[record.id] = record

        response = client.get(f"/api/v1/runs/{record.id}/artifacts/{artifact.id}")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        disposition = response.headers["content-disposition"]
        assert disposition.startswith("attachment;")
        assert disposition.endswith("Bundle.zip")
