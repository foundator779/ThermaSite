from __future__ import annotations

import asyncio
import io
import json
import math
import warnings as pywarnings
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlparse

import httpx
import numpy as np
from matplotlib import colormaps
from PIL import Image

from terraforge.contracts.models import (
    AcquisitionResult,
    DatasetRequest,
    MapRasterLayer,
    RasterLegendStop,
    VegetationAnalysis,
    VegetationPeriod,
)
from terraforge.persistence.artifacts import ArtifactStore
from terraforge.settings import Settings

DATASET_ID = "sentinel-2-l2a-vegetation-user-area"
ALLOWED_ASSET_HOSTS = {"sentinel-cogs.s3.us-west-2.amazonaws.com"}
EXCLUDED_SCL_CLASSES = {0, 1, 3, 7, 8, 9, 10, 11}
SQ_METERS_PER_SQ_MILE = 2_589_988.110336


def calculate_ndvi(nir: np.ndarray, red: np.ndarray) -> np.ndarray:
    return _normalized_difference(nir, red)


def calculate_ndmi(nir: np.ndarray, swir: np.ndarray) -> np.ndarray:
    return _normalized_difference(nir, swir)


def scale_sentinel_reflectance(values: np.ndarray) -> np.ndarray:
    """Convert Sentinel-2 L2A integer surface reflectance to physical reflectance."""
    result = values.astype("float32", copy=True)
    result[result == 0] = np.nan
    result *= 0.0001
    return result


def _normalized_difference(first: np.ndarray, second: np.ndarray) -> np.ndarray:
    first = first.astype("float32", copy=False)
    second = second.astype("float32", copy=False)
    denominator = first + second
    result = np.full(first.shape, np.nan, dtype="float32")
    np.divide(first - second, denominator, out=result, where=np.abs(denominator) > 1e-8)
    result[(result < -1) | (result > 1)] = np.nan
    return result


def classify_percentile(percentile: float | None) -> str:
    if percentile is None or not math.isfinite(percentile):
        return "No valid observation"
    if percentile <= 10:
        return "Severe stress"
    if percentile <= 25:
        return "Moderate stress"
    if percentile <= 75:
        return "Typical"
    return "Above typical"


def validate_asset_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_ASSET_HOSTS:
        raise ValueError("Sentinel asset URL is outside the approved public COG host")
    if not parsed.path.lower().endswith(".tif"):
        raise ValueError("Sentinel analysis accepts GeoTIFF assets only")


def _safe_replace_year(value: date, year: int) -> date:
    try:
        return value.replace(year=year)
    except ValueError:
        return value.replace(year=year, day=28)


class Sentinel2VegetationConnector:
    dataset_id = DATASET_ID

    def __init__(self, artifacts: ArtifactStore, settings: Settings):
        self.artifacts = artifacts
        self.settings = settings
        self.endpoint = settings.sentinel_stac_url.rstrip("/") + "/search"

    def validate_request(self, request: DatasetRequest) -> None:
        if request.dataset_id != self.dataset_id:
            raise ValueError("Connector dataset mismatch")
        if request.geometry.type != "Polygon":
            raise ValueError("Sentinel vegetation analysis requires polygon geometry")
        if "vegetation_condition" not in request.variables:
            raise ValueError("Sentinel acquisition requires vegetation_condition")

    async def metadata(self) -> dict:
        return {
            "dataset_id": self.dataset_id,
            "collection": "sentinel-2-l2a",
            "stac_url": self.settings.sentinel_stac_url,
            "resolution_m": 20,
            "authentication": "none",
        }

    async def fetch(self, run_id: str, request: DatasetRequest) -> AcquisitionResult:
        self.validate_request(request)
        today = datetime.now(UTC).date()
        current_start = today - timedelta(days=90)
        baseline_windows = [
            (_safe_replace_year(current_start, today.year - offset), _safe_replace_year(today, today.year - offset))
            for offset in range(1, 6)
        ]
        warnings: list[str] = []
        current_items: list[dict] = []
        baseline_items: list[dict] = []
        if self.settings.sentinel_analysis_enabled:
            try:
                async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
                    tasks = [self._search(client, request, current_start, today, 5)] + [
                        self._search(client, request, start, end, 3)
                        for start, end in baseline_windows
                    ]
                    results = await asyncio.gather(*tasks)
                current_items = results[0]
                baseline_items = [item for group in results[1:] for item in group]
            except Exception as exc:  # noqa: BLE001 - remote evidence failures must degrade safely
                warnings.append(f"Sentinel-2 discovery was unavailable: {type(exc).__name__}: {exc}")
        else:
            warnings.append("Sentinel-2 analysis is disabled by configuration.")

        manifest = {
            "collection": "sentinel-2-l2a",
            "stac_endpoint": self.endpoint,
            "geometry": request.geometry.model_dump(mode="json"),
            "current_window": [current_start.isoformat(), today.isoformat()],
            "baseline_windows": [[start.isoformat(), end.isoformat()] for start, end in baseline_windows],
            "cloud_cover_limit_pct": self.settings.sentinel_max_cloud_cover,
            "assets": ["red", "nir", "swir16", "scl"],
            "current_items": [_manifest_item(item) for item in current_items],
            "baseline_items": [_manifest_item(item) for item in baseline_items],
            "processing": {
                "processing_version": "habiwatch-sentinel-v1",
                "resolution_m": 20,
                "current_composite": "median of up to five usable acquisition dates",
                "baseline_composite": "same-season median across previous five years",
                "cloud_mask": sorted(EXCLUDED_SCL_CLASSES),
                "ndvi": "(NIR - red) / (NIR + red)",
                "ndmi": "(NIR - SWIR1) / (NIR + SWIR1)",
            },
            "attribution": "Contains modified Copernicus Sentinel data",
            "warnings": warnings,
        }
        raw = await self.artifacts.put_raw(
            run_id,
            self.dataset_id,
            "sentinel_scene_manifest.json",
            json.dumps(manifest, indent=2).encode(),
            "application/json",
        )

        analysis: VegetationAnalysis
        derived = []
        if current_items and baseline_items:
            try:
                analysis, derived = await asyncio.to_thread(
                    self._process,
                    run_id,
                    request,
                    current_items,
                    baseline_items,
                    current_start,
                    today,
                    min(start for start, _ in baseline_windows),
                    max(end for _, end in baseline_windows),
                    warnings,
                )
            except Exception as exc:  # noqa: BLE001 - raster providers expose varied GDAL failures
                warnings.append(f"Sentinel-2 raster processing was unavailable: {type(exc).__name__}: {exc}")
                analysis = _insufficient_analysis(
                    current_start, today, min(start for start, _ in baseline_windows), max(end for _, end in baseline_windows), warnings
                )
        else:
            warnings.append("No current and baseline Sentinel-2 scenes satisfied the discovery filters.")
            analysis = _insufficient_analysis(
                current_start, today, min(start for start, _ in baseline_windows), max(end for _, end in baseline_windows), warnings
            )

        return AcquisitionResult(
            dataset_id=self.dataset_id,
            provider="Copernicus Sentinel-2 via Earth Search",
            source_request={"url": self.endpoint, "geometry": request.geometry.model_dump(mode="json")},
            files=[raw],
            metadata={
                "units": "unitless spectral indices",
                "row_count": len(current_items) + len(baseline_items),
                "available": analysis.status == "available",
                "current_scene_count": analysis.current_scene_count,
                "baseline_scene_count": analysis.baseline_scene_count,
                "valid_coverage_pct": analysis.valid_coverage_pct,
                "license": "Copernicus Sentinel Data Terms",
            },
            warnings=warnings,
            derived_artifacts=derived,
            vegetation_analysis=analysis,
        )

    async def _search(
        self,
        client: httpx.AsyncClient,
        request: DatasetRequest,
        start: date,
        end: date,
        max_dates: int,
    ) -> list[dict]:
        payload = {
            "collections": ["sentinel-2-l2a"],
            "intersects": request.geometry.model_dump(mode="json"),
            "datetime": f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z",
            "limit": 100,
            "query": {"eo:cloud_cover": {"lt": self.settings.sentinel_max_cloud_cover}},
            "sortby": [{"field": "properties.datetime", "direction": "desc"}],
        }
        response = await client.post(self.endpoint, json=payload)
        response.raise_for_status()
        features = response.json().get("features", [])
        required = {"red", "nir", "swir16", "scl"}
        features = [
            item
            for item in features
            if required.issubset(item.get("assets", {}))
            and (
                not isinstance(item.get("properties", {}).get("eo:cloud_cover"), (int, float))
                or item["properties"]["eo:cloud_cover"] < self.settings.sentinel_max_cloud_cover
            )
        ]
        dates: list[str] = []
        selected: list[dict] = []
        for item in features:
            day = str(item.get("properties", {}).get("datetime", ""))[:10]
            if not day:
                continue
            if day not in dates:
                if len(dates) >= max_dates:
                    continue
                dates.append(day)
            selected.append(item)
        return selected

    def _process(
        self,
        run_id: str,
        request: DatasetRequest,
        current_items: list[dict],
        baseline_items: list[dict],
        current_start: date,
        current_end: date,
        baseline_start: date,
        baseline_end: date,
        warnings: list[str],
    ) -> tuple[VegetationAnalysis, list]:
        import rasterio
        from rasterio.features import geometry_mask
        from rasterio.transform import from_bounds
        from rasterio.warp import transform_bounds

        ring = request.geometry.coordinates[0]
        west = min(float(point[0]) for point in ring)
        south = min(float(point[1]) for point in ring)
        east = max(float(point[0]) for point in ring)
        north = max(float(point[1]) for point in ring)
        projected = transform_bounds("EPSG:4326", "EPSG:3857", west, south, east, north)
        span_x, span_y = projected[2] - projected[0], projected[3] - projected[1]
        resolution = 20.0
        width = max(1, math.ceil(span_x / resolution))
        height = max(1, math.ceil(span_y / resolution))
        if width * height > 16_000_000:
            raise ValueError(
                "The geometry extent exceeds the safe 20 m processing grid; draw a more compact area."
            )
        transform = from_bounds(*projected, width, height)
        geometry = request.geometry.model_dump(mode="json")
        projected_geometry = rasterio.warp.transform_geom("EPSG:4326", "EPSG:3857", geometry)
        inside = geometry_mask([projected_geometry], (height, width), transform, invert=True)

        current_stack, _ = _read_index_stack(current_items, transform, width, height, inside)
        baseline_stack, _ = _read_index_stack(baseline_items, transform, width, height, inside)
        if not current_stack or not baseline_stack:
            raise ValueError("No cloud-free pixels were available in the requested geometry")
        current_ndvi_stack = np.stack([item[0] for item in current_stack])
        current_ndmi_stack = np.stack([item[1] for item in current_stack])
        baseline_ndvi_stack = np.stack([item[0] for item in baseline_stack])
        baseline_ndmi_stack = np.stack([item[1] for item in baseline_stack])
        current_ndvi = _nanmedian(current_ndvi_stack)
        current_ndmi = _nanmedian(current_ndmi_stack)
        baseline_ndvi = _nanmedian(baseline_ndvi_stack)
        baseline_ndmi = _nanmedian(baseline_ndmi_stack)
        vegetation_mask = inside & np.isfinite(baseline_ndvi) & (baseline_ndvi > 0.2)
        valid = vegetation_mask & np.isfinite(baseline_ndmi) & np.isfinite(current_ndvi) & np.isfinite(current_ndmi)
        denominator = max(1, int(vegetation_mask.sum()))
        coverage = float(valid.sum() / denominator * 100)

        ndvi_available = np.isfinite(baseline_ndvi_stack)
        ndmi_available = np.isfinite(baseline_ndmi_stack)
        ndvi_percentile = np.divide(
            np.sum(ndvi_available & (baseline_ndvi_stack <= current_ndvi[None, :, :]), axis=0),
            np.sum(ndvi_available, axis=0),
            out=np.full(current_ndvi.shape, np.nan),
            where=np.sum(ndvi_available, axis=0) > 0,
        ) * 100
        ndmi_percentile = np.divide(
            np.sum(ndmi_available & (baseline_ndmi_stack <= current_ndmi[None, :, :]), axis=0),
            np.sum(ndmi_available, axis=0),
            out=np.full(current_ndmi.shape, np.nan),
            where=np.sum(ndmi_available, axis=0) > 0,
        ) * 100
        percentile = np.minimum(ndvi_percentile, ndmi_percentile).astype("float32")
        percentile[~valid] = np.nan
        stressed = valid & (percentile <= 25)
        stressed_pct = float(stressed.sum() / max(1, valid.sum()) * 100)
        pixel_area_sq_mi = abs(transform.a * transform.e) / SQ_METERS_PER_SQ_MILE
        stressed_sq_mi = float(stressed.sum() * pixel_area_sq_mi)
        current_dates = sorted({entry[2] for entry in current_stack})
        baseline_dates = sorted({entry[2] for entry in baseline_stack})
        current_series = [
            {"date": day, "ndvi": _median_or_none(ndvi[vegetation_mask]), "ndmi": _median_or_none(ndmi[vegetation_mask])}
            for ndvi, ndmi, day in current_stack
        ]
        baseline_series = [
            {"date": day, "ndvi": _median_or_none(ndvi[vegetation_mask]), "ndmi": _median_or_none(ndmi[vegetation_mask])}
            for ndvi, ndmi, day in baseline_stack
        ]
        sufficient = len(current_dates) >= 2 and len(baseline_dates) >= 6 and coverage >= 60
        if not sufficient:
            warnings.append(
                "Vegetation classification requires two current dates, six baseline dates, and 60% valid coverage."
            )
            percentile = np.full(percentile.shape, np.nan, dtype="float32")

        bounds = (west, south, east, north)
        artifacts = []
        layer_specs = [
            ("ndvi-current", "Greenness — current", "ndvi", "current", current_ndvi, "RdYlGn", -0.2, 0.9, _ndvi_legend()),
            ("ndvi-baseline", "Greenness — baseline", "ndvi", "baseline", baseline_ndvi, "RdYlGn", -0.2, 0.9, _ndvi_legend()),
            ("ndmi-current", "Moisture — current", "ndmi", "current", current_ndmi, "BrBG", -0.5, 0.7, _ndmi_legend()),
            ("ndmi-baseline", "Moisture — baseline", "ndmi", "baseline", baseline_ndmi, "BrBG", -0.5, 0.7, _ndmi_legend()),
            ("vegetation-stress", "Seasonal vegetation condition", "stress", "anomaly", percentile, "RdYlGn", 0, 100, _stress_legend()),
        ]
        layers: list[MapRasterLayer] = []
        for layer_id, label, metric, period, values, cmap, minimum, maximum, legend in layer_specs:
            artifact = self.artifacts.put_artifact(
                run_id,
                f"{layer_id}.png",
                _render_overlay(values, cmap, minimum, maximum),
                "image/png",
                "SentinelVegetationProcessor",
            )
            artifacts.append(artifact)
            layers.append(
                MapRasterLayer(
                    id=layer_id,
                    label=label,
                    metric=metric,
                    period=period,
                    artifact_id=artifact.id,
                    bounds=bounds,
                    unit="percentile" if metric == "stress" else "index",
                    legend=legend,
                    resolution_m=round(resolution, 2),
                    scientific_resolution_m=20,
                    display_width_px=width,
                    display_height_px=height,
                )
            )

        scientific = _write_geotiff(
            np.stack([current_ndvi, baseline_ndvi, current_ndmi, baseline_ndmi, percentile]),
            transform,
        )
        artifacts.append(
            self.artifacts.put_artifact(
                run_id,
                "sentinel_vegetation_indices.tif",
                scientific,
                "image/tiff",
                "SentinelVegetationProcessor",
            )
        )
        grid_buffer = io.BytesIO()
        np.savez_compressed(
            grid_buffer,
            current_ndvi=current_ndvi.astype("float32"),
            baseline_ndvi=baseline_ndvi.astype("float32"),
            current_ndmi=current_ndmi.astype("float32"),
            baseline_ndmi=baseline_ndmi.astype("float32"),
            percentile=percentile.astype("float32"),
            transform=np.asarray(tuple(transform)[:6], dtype="float64"),
        )
        grid_artifact = self.artifacts.put_artifact(
            run_id,
            "vegetation_sample_grid.npz",
            grid_buffer.getvalue(),
            "application/octet-stream",
            "SentinelVegetationProcessor",
        )
        artifacts.append(grid_artifact)
        series_artifact = self.artifacts.put_artifact(
            run_id,
            "vegetation_time_series.json",
            json.dumps({"current": current_series, "baseline": baseline_series}, indent=2).encode(),
            "application/json",
            "SentinelVegetationProcessor",
        )
        artifacts.append(series_artifact)

        latest_date = max(datetime.fromisoformat(day).date() for day in current_dates)
        confidence = min(1.0, coverage / 100) * min(1.0, len(current_dates) / 3) * min(1.0, len(baseline_dates) / 10)
        analysis = VegetationAnalysis(
            status="available" if sufficient else "insufficient",
            resolution_m=round(resolution, 2),
            current_period=VegetationPeriod(start=current_start, end=current_end),
            baseline_period=VegetationPeriod(start=baseline_start, end=baseline_end),
            current_scene_count=len(current_dates),
            baseline_scene_count=len(baseline_dates),
            valid_coverage_pct=round(coverage, 2),
            observation_age_days=(datetime.now(UTC).date() - latest_date).days,
            latest_observation_date=latest_date,
            median_ndvi=_median_or_none(current_ndvi[valid]),
            baseline_median_ndvi=_median_or_none(baseline_ndvi[valid]),
            ndvi_anomaly=_median_or_none((current_ndvi - baseline_ndvi)[valid]),
            median_ndmi=_median_or_none(current_ndmi[valid]),
            baseline_median_ndmi=_median_or_none(baseline_ndmi[valid]),
            ndmi_anomaly=_median_or_none((current_ndmi - baseline_ndmi)[valid]),
            stressed_area_pct=round(stressed_pct, 2) if sufficient else None,
            stressed_area_sq_mi=round(stressed_sq_mi, 2) if sufficient else None,
            confidence=round(confidence, 3) if sufficient else 0,
            scene_ids=[str(item.get("id")) for item in current_items + baseline_items],
            layers=layers,
            sample_grid_artifact_id=grid_artifact.id,
            time_series=[
                *[{**point, "period": "baseline"} for point in baseline_series],
                *[{**point, "period": "current"} for point in current_series],
            ],
            warnings=list(warnings),
        )
        return analysis, artifacts


def _manifest_item(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "datetime": item.get("properties", {}).get("datetime"),
        "cloud_cover_pct": item.get("properties", {}).get("eo:cloud_cover"),
        "assets": {key: item.get("assets", {}).get(key, {}).get("href") for key in ("red", "nir", "swir16", "scl")},
    }


def _insufficient_analysis(
    current_start: date,
    current_end: date,
    baseline_start: date,
    baseline_end: date,
    warnings: list[str],
) -> VegetationAnalysis:
    return VegetationAnalysis(
        status="insufficient",
        current_period=VegetationPeriod(start=current_start, end=current_end),
        baseline_period=VegetationPeriod(start=baseline_start, end=baseline_end),
        warnings=list(warnings),
    )


def _read_index_stack(items: list[dict], transform, width: int, height: int, inside: np.ndarray):
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        groups[str(item.get("properties", {}).get("datetime", ""))[:10]].append(item)
    stack: list[tuple[np.ndarray, np.ndarray, str]] = []
    series: list[dict] = []
    for day, group in sorted(groups.items()):
        tile_ndvi: list[np.ndarray] = []
        tile_ndmi: list[np.ndarray] = []
        for item in group:
            try:
                red = _read_asset(item, "red", transform, width, height, categorical=False)
                nir = _read_asset(item, "nir", transform, width, height, categorical=False)
                swir = _read_asset(item, "swir16", transform, width, height, categorical=False)
                scl = _read_asset(item, "scl", transform, width, height, categorical=True)
                clear = inside & ~np.isin(scl.astype("uint8"), list(EXCLUDED_SCL_CLASSES))
                ndvi = calculate_ndvi(nir, red)
                ndmi = calculate_ndmi(nir, swir)
                ndvi[~clear] = np.nan
                ndmi[~clear] = np.nan
                tile_ndvi.append(ndvi)
                tile_ndmi.append(ndmi)
            except Exception:  # noqa: BLE001, S112 - one bad tile must not discard a valid mosaic
                continue
        if not tile_ndvi:
            continue
        ndvi = _nanmedian(np.stack(tile_ndvi))
        ndmi = _nanmedian(np.stack(tile_ndmi))
        if np.isfinite(ndvi).sum() == 0:
            continue
        stack.append((ndvi, ndmi, day))
        series.append(
            {
                "date": day,
                "ndvi": _median_or_none(ndvi[inside]),
                "ndmi": _median_or_none(ndmi[inside]),
            }
        )
    return stack, series


def _read_asset(item: dict, key: str, transform, width: int, height: int, categorical: bool):
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT

    url = str(item["assets"][key]["href"])
    validate_asset_url(url)
    with rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        AWS_NO_SIGN_REQUEST="YES",
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
    ), rasterio.open(url) as source, WarpedVRT(
        source,
        crs="EPSG:3857",
        transform=transform,
        width=width,
        height=height,
        resampling=Resampling.nearest if categorical else Resampling.bilinear,
        src_nodata=0,
        nodata=0,
    ) as vrt:
        data = vrt.read(1).astype("float32")
    if not categorical:
        data = scale_sentinel_reflectance(data)
    return data


def _render_overlay(values: np.ndarray, cmap_name: str, minimum: float, maximum: float) -> bytes:
    normalized = np.clip((values - minimum) / (maximum - minimum), 0, 1)
    rgba = (colormaps[cmap_name](np.nan_to_num(normalized, nan=0)) * 255).astype("uint8")
    rgba[..., 3] = np.where(np.isfinite(values), 205, 0).astype("uint8")
    buffer = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _write_geotiff(values: np.ndarray, transform) -> bytes:
    from rasterio.io import MemoryFile

    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            width=values.shape[2],
            height=values.shape[1],
            count=values.shape[0],
            dtype="float32",
            crs="EPSG:3857",
            transform=transform,
            nodata=np.nan,
            compress="deflate",
            tiled=True,
        ) as dataset:
            dataset.write(values.astype("float32"))
            dataset.descriptions = (
                "current_ndvi",
                "baseline_ndvi",
                "current_ndmi",
                "baseline_ndmi",
                "seasonal_percentile",
            )
        return memory.read()


def _median_or_none(values: np.ndarray) -> float | None:
    finite = values[np.isfinite(values)]
    return round(float(np.median(finite)), 4) if finite.size else None


def _nanmedian(values: np.ndarray) -> np.ndarray:
    with pywarnings.catch_warnings():
        pywarnings.simplefilter("ignore", category=RuntimeWarning)
        return np.nanmedian(values, axis=0)


def _ndvi_legend():
    return [
        RasterLegendStop(value=0, label="Sparse", color="#a50026"),
        RasterLegendStop(value=0.3, label="Low", color="#fdae61"),
        RasterLegendStop(value=0.6, label="Healthy", color="#66bd63"),
        RasterLegendStop(value=0.9, label="Dense", color="#006837"),
    ]


def _ndmi_legend():
    return [
        RasterLegendStop(value=-0.3, label="Dry", color="#8c510a"),
        RasterLegendStop(value=0, label="Low moisture", color="#dfc27d"),
        RasterLegendStop(value=0.3, label="Moist", color="#80cdc1"),
        RasterLegendStop(value=0.6, label="High moisture", color="#01665e"),
    ]


def _stress_legend():
    return [
        RasterLegendStop(value=10, label="Severe stress", color="#a50026"),
        RasterLegendStop(value=25, label="Moderate stress", color="#f46d43"),
        RasterLegendStop(value=75, label="Typical", color="#a6d96a"),
        RasterLegendStop(value=100, label="Above typical", color="#006837"),
    ]


def sample_grid(content: bytes, longitude: float, latitude: float) -> dict:
    from affine import Affine
    from rasterio.warp import transform as project

    with np.load(io.BytesIO(content)) as grid:
        affine = Affine(*grid["transform"].tolist())
        xs, ys = project("EPSG:4326", "EPSG:3857", [longitude], [latitude])
        column, row = (~affine) * (xs[0], ys[0])
        row, column = math.floor(row), math.floor(column)
        shape = grid["current_ndvi"].shape
        if row < 0 or column < 0 or row >= shape[0] or column >= shape[1]:
            raise ValueError("Coordinate is outside the vegetation analysis grid")
        percentile_value = _value_or_none(grid["percentile"][row, column])
        return {
            "latitude": latitude,
            "longitude": longitude,
            "current_ndvi": _value_or_none(grid["current_ndvi"][row, column]),
            "baseline_ndvi": _value_or_none(grid["baseline_ndvi"][row, column]),
            "current_ndmi": _value_or_none(grid["current_ndmi"][row, column]),
            "baseline_ndmi": _value_or_none(grid["baseline_ndmi"][row, column]),
            "seasonal_percentile": percentile_value,
            "classification": classify_percentile(percentile_value),
        }


def _value_or_none(value) -> float | None:
    return round(float(value), 4) if np.isfinite(value) else None
