from __future__ import annotations

import io
import os
from datetime import date

import httpx
import numpy as np
import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response
from rasterio.transform import from_bounds
from rasterio.warp import transform as project

from terraforge.connectors import sentinel
from terraforge.connectors.sentinel import (
    Sentinel2VegetationConnector,
    calculate_ndmi,
    calculate_ndvi,
    classify_percentile,
    sample_grid,
    scale_sentinel_reflectance,
    validate_asset_url,
)
from terraforge.contracts.models import (
    DatasetRequest,
    GeometrySpec,
    RunRecord,
    VegetationAnalysis,
    VegetationPeriod,
)
from terraforge.main import app
from terraforge.persistence.artifacts import ArtifactStore
from terraforge.settings import Settings


def vegetation_request() -> DatasetRequest:
    return DatasetRequest(
        dataset_id=Sentinel2VegetationConnector.dataset_id,
        variables=["vegetation_condition"],
        start_date=date(2005, 1, 1),
        end_date=date(2025, 12, 31),
        geometry=GeometrySpec(
            type="Polygon",
            coordinates=[
                [
                    [-89.390, 36.388],
                    [-89.388, 36.388],
                    [-89.388, 36.390],
                    [-89.390, 36.390],
                    [-89.390, 36.388],
                ]
            ],
        ),
    )


def reelfoot_live_request() -> DatasetRequest:
    return DatasetRequest(
        dataset_id=Sentinel2VegetationConnector.dataset_id,
        variables=["vegetation_condition"],
        start_date=date(2005, 1, 1),
        end_date=date(2025, 12, 31),
        geometry=GeometrySpec(
            type="Polygon",
            coordinates=[
                [
                    [-89.405, 36.375],
                    [-89.375, 36.375],
                    [-89.375, 36.402],
                    [-89.405, 36.402],
                    [-89.405, 36.375],
                ]
            ],
        ),
    )


def test_vegetation_indices_are_deterministic_and_bound_invalid_pixels():
    nir = np.array([[0.8, 0.0], [0.4, np.nan]], dtype="float32")
    red = np.array([[0.2, 0.0], [0.4, 0.2]], dtype="float32")
    swir = np.array([[0.3, 0.0], [0.6, 0.2]], dtype="float32")

    ndvi = calculate_ndvi(nir, red)
    ndmi = calculate_ndmi(nir, swir)

    assert ndvi[0, 0] == pytest.approx(0.6)
    assert ndmi[0, 0] == pytest.approx(0.454545)
    assert np.isnan(ndvi[0, 1])
    assert classify_percentile(8) == "Severe stress"
    assert classify_percentile(20) == "Moderate stress"
    assert classify_percentile(50) == "Typical"
    assert classify_percentile(90) == "Above typical"

    reflectance = scale_sentinel_reflectance(np.array([[0, 1_000, 8_500]], dtype="uint16"))
    assert np.isnan(reflectance[0, 0])
    assert reflectance[0, 1] == pytest.approx(0.1)
    assert reflectance[0, 2] == pytest.approx(0.85)


def test_same_day_tiles_are_mosaicked_after_scene_classification_mask(monkeypatch):
    items = [
        {"id": "tile-a", "properties": {"datetime": "2026-08-10T12:00:00Z"}},
        {"id": "tile-b", "properties": {"datetime": "2026-08-10T12:00:00Z"}},
    ]
    arrays = {
        ("tile-a", "red"): np.full((2, 3), 0.2, dtype="float32"),
        ("tile-a", "nir"): np.full((2, 3), 0.8, dtype="float32"),
        ("tile-a", "swir16"): np.full((2, 3), 0.3, dtype="float32"),
        ("tile-a", "scl"): np.array([[4, 0, 0], [4, 0, 0]], dtype="float32"),
        ("tile-b", "red"): np.full((2, 3), 0.2, dtype="float32"),
        ("tile-b", "nir"): np.full((2, 3), 0.6, dtype="float32"),
        ("tile-b", "swir16"): np.full((2, 3), 0.35, dtype="float32"),
        ("tile-b", "scl"): np.array([[0, 4, 4], [0, 4, 3]], dtype="float32"),
    }

    monkeypatch.setattr(
        sentinel,
        "_read_asset",
        lambda item, key, *_args, **_kwargs: arrays[(item["id"], key)].copy(),
    )
    stack, _ = sentinel._read_index_stack(items, None, 3, 2, np.ones((2, 3), dtype=bool))

    assert len(stack) == 1
    ndvi, ndmi, day = stack[0]
    assert day == "2026-08-10"
    assert ndvi[0, 0] == pytest.approx(0.6)
    assert ndvi[0, 1] == pytest.approx(0.5)
    assert np.isfinite(ndmi).sum() == 5
    assert np.isnan(ndvi[1, 2])


def test_sentinel_asset_allowlist_rejects_unapproved_or_non_tiff_urls():
    validate_asset_url(
        "https://sentinel-cogs.s3.us-west-2.amazonaws.com/sentinel-s2-l2a-cogs/example/B04.tif"
    )
    with pytest.raises(ValueError, match="approved"):
        validate_asset_url("https://example.com/B04.tif")
    with pytest.raises(ValueError, match="GeoTIFF"):
        validate_asset_url("https://sentinel-cogs.s3.us-west-2.amazonaws.com/example.png")


@respx.mock
async def test_stac_discovery_limits_unique_dates_and_requires_analysis_assets(tmp_path):
    settings = Settings(terraforge_data_dir=tmp_path)
    connector = Sentinel2VegetationConnector(ArtifactStore(settings), settings)
    features = []
    for index in range(7):
        features.append(
            {
                "id": f"scene-{index}",
                "properties": {
                    "datetime": f"2026-08-{20 - index:02d}T12:00:00Z",
                    "eo:cloud_cover": 2,
                },
                "assets": {
                    key: {"href": f"https://sentinel-cogs.s3.us-west-2.amazonaws.com/{key}.tif"}
                    for key in ("red", "nir", "swir16", "scl")
                },
            }
        )
    features.append(
        {"id": "incomplete", "properties": {"datetime": "2026-08-01T12:00:00Z"}, "assets": {}}
    )
    route = respx.post(connector.endpoint).mock(
        return_value=Response(200, json={"features": features})
    )

    async with httpx.AsyncClient() as client:
        selected = await connector._search(
            client, vegetation_request(), date(2026, 5, 1), date(2026, 8, 21), 5
        )

    assert len(selected) == 5
    assert route.calls[0].request.content


@respx.mock
async def test_missing_sentinel_imagery_returns_insufficient_evidence(tmp_path):
    settings = Settings(terraforge_data_dir=tmp_path)
    artifacts = ArtifactStore(settings)
    connector = Sentinel2VegetationConnector(artifacts, settings)
    respx.post(connector.endpoint).mock(return_value=Response(200, json={"features": []}))

    result = await connector.fetch("missing-scenes", vegetation_request())

    assert result.vegetation_analysis is not None
    assert result.vegetation_analysis.status == "insufficient"
    assert result.vegetation_analysis.stressed_area_pct is None
    assert result.files[0].filename == "sentinel_scene_manifest.json"


@pytest.mark.skipif(
    not os.getenv("LIVE_SENTINEL_TEST"),
    reason="Set LIVE_SENTINEL_TEST=1 for a real keyless Earth Search/COG run",
)
async def test_live_reelfoot_sentinel_pipeline(tmp_path):
    settings = Settings(terraforge_data_dir=tmp_path, request_timeout_seconds=90)
    connector = Sentinel2VegetationConnector(ArtifactStore(settings), settings)

    result = await connector.fetch("live-reelfoot", reelfoot_live_request())

    assert result.vegetation_analysis is not None
    assert result.vegetation_analysis.status == "available"
    assert result.vegetation_analysis.current_scene_count >= 2
    assert result.vegetation_analysis.baseline_scene_count >= 6
    assert result.vegetation_analysis.valid_coverage_pct >= 60


def test_processor_builds_layers_metrics_and_sampleable_grid(tmp_path, monkeypatch):
    settings = Settings(terraforge_data_dir=tmp_path)
    artifacts = ArtifactStore(settings)
    connector = Sentinel2VegetationConnector(artifacts, settings)
    current_items = [
        {"id": f"current-{day}", "properties": {"datetime": f"2026-08-{day:02d}T12:00:00Z"}}
        for day in (10, 15)
    ]
    baseline_items = [
        {"id": f"baseline-{year}", "properties": {"datetime": f"{year}-08-12T12:00:00Z"}}
        for year in range(2020, 2026)
    ]

    def fake_stack(items, _transform, width, height, inside):
        is_current = str(items[0]["id"]).startswith("current")
        output = []
        series = []
        for index, item in enumerate(items):
            ndvi_value = 0.34 + index * 0.01 if is_current else 0.55 + index * 0.015
            ndmi_value = 0.20 + index * 0.01 if is_current else 0.36 + index * 0.01
            ndvi = np.full((height, width), ndvi_value, dtype="float32")
            ndmi = np.full((height, width), ndmi_value, dtype="float32")
            ndvi[~inside] = np.nan
            ndmi[~inside] = np.nan
            day = item["properties"]["datetime"][:10]
            output.append((ndvi, ndmi, day))
            series.append({"date": day, "ndvi": ndvi_value, "ndmi": ndmi_value})
        return output, series

    monkeypatch.setattr(sentinel, "_read_index_stack", fake_stack)
    analysis, derived = connector._process(
        "vegetation-test",
        vegetation_request(),
        current_items,
        baseline_items,
        date(2026, 5, 23),
        date(2026, 8, 21),
        date(2020, 5, 23),
        date(2025, 8, 21),
        [],
    )

    assert analysis.status == "available"
    assert analysis.current_scene_count == 2
    assert analysis.baseline_scene_count == 6
    assert analysis.ndvi_anomaly is not None and analysis.ndvi_anomaly < 0
    assert analysis.stressed_area_pct == pytest.approx(100)
    assert len(analysis.layers) == 5
    assert len(derived) == 8
    grid_artifact = next(item for item in derived if item.id == analysis.sample_grid_artifact_id)
    sampled = sample_grid(artifacts.read_bytes(grid_artifact.uri), -89.389, 36.389)
    assert sampled["current_ndvi"] == pytest.approx(0.345, abs=0.001)
    assert sampled["classification"] == "Severe stress"

    insufficient, insufficient_artifacts = connector._process(
        "vegetation-insufficient-test",
        vegetation_request(),
        current_items[:1],
        baseline_items[:5],
        date(2026, 5, 23),
        date(2026, 8, 21),
        date(2021, 5, 23),
        date(2025, 8, 21),
        [],
    )
    assert insufficient.status == "insufficient"
    assert insufficient.stressed_area_pct is None
    insufficient_grid = next(
        item for item in insufficient_artifacts if item.id == insufficient.sample_grid_artifact_id
    )
    insufficient_sample = sample_grid(artifacts.read_bytes(insufficient_grid.uri), -89.389, 36.389)
    assert insufficient_sample["classification"] == "No valid observation"


def test_vegetation_api_hydrates_layers_and_samples_a_pixel():
    buffer = io.BytesIO()
    xs, ys = project("EPSG:4326", "EPSG:3857", [-89.40, -89.38], [36.38, 36.40])
    transform = from_bounds(xs[0], ys[0], xs[1], ys[1], 2, 2)
    values = np.full((2, 2), 0.42, dtype="float32")
    np.savez_compressed(
        buffer,
        transform=np.asarray(tuple(transform)[:6], dtype="float64"),
        current_ndvi=values,
        baseline_ndvi=np.full((2, 2), 0.55, dtype="float32"),
        current_ndmi=np.full((2, 2), 0.21, dtype="float32"),
        baseline_ndmi=np.full((2, 2), 0.33, dtype="float32"),
        percentile=np.full((2, 2), 18, dtype="float32"),
    )
    with TestClient(app) as client:
        record = RunRecord(user_query="Inspect vegetation evidence at Reelfoot Lake")
        grid = client.app.state.artifacts.put_artifact(
            str(record.id),
            "vegetation_sample_grid.npz",
            buffer.getvalue(),
            "application/octet-stream",
            "test",
        )
        record.artifacts.append(grid)
        record.vegetation = VegetationAnalysis(
            status="available",
            current_period=VegetationPeriod(start=date(2026, 5, 23), end=date(2026, 8, 21)),
            baseline_period=VegetationPeriod(start=date(2021, 5, 23), end=date(2025, 8, 21)),
            current_scene_count=2,
            baseline_scene_count=6,
            valid_coverage_pct=90,
            sample_grid_artifact_id=grid.id,
        )
        client.app.state.runs._runs[record.id] = record

        analysis = client.get(f"/api/v1/runs/{record.id}/vegetation")
        assert analysis.status_code == 200
        assert analysis.json()["source"].startswith("Copernicus Sentinel-2")
        sample = client.get(
            f"/api/v1/runs/{record.id}/vegetation/sample",
            params={"latitude": 36.39, "longitude": -89.39},
        )
        assert sample.status_code == 200
        assert sample.json()["current_ndvi"] == pytest.approx(0.42)
        assert sample.json()["classification"] == "Moderate stress"
