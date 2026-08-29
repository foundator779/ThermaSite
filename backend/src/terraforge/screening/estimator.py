from __future__ import annotations

import math
from typing import Any

from .models import ResourceEstimate, ResourceEstimatorRequest, ThermalMetrics, ThermalWindow

EARTH_RADIUS_M = 6_371_008.8
SQ_M_PER_SQ_MI = 2_589_988.110336
ACRES_PER_SQ_MI = 640.0
LITERS_PER_GALLON = 3.785411784

# Direct, on-site WUE scenario bands. These are editable model assumptions represented as
# ranges so ThermaSite never implies that ambient heat alone determines water consumption.
WUE_BANDS: dict[str, tuple[float, float]] = {
    "dry": (0.0, 0.08),
    "evaporative": (1.2, 2.4),
    "hybrid": (0.3, 1.2),
    "liquid": (0.05, 0.35),
}


def _extract_ring(geojson: dict[str, Any]) -> list[list[float]]:
    geometry = geojson
    if geojson.get("type") == "FeatureCollection":
        features = geojson.get("features")
        if not isinstance(features, list) or len(features) != 1:
            raise ValueError("Draw exactly one data-center footprint polygon")
        geometry = features[0].get("geometry") or {}
    elif geojson.get("type") == "Feature":
        geometry = geojson.get("geometry") or {}
    if geometry.get("type") != "Polygon":
        raise ValueError("The estimator accepts one GeoJSON Polygon")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) != 1:
        raise ValueError("Polygon holes and multipolygons are not supported in this estimator")
    ring = coordinates[0]
    if not isinstance(ring, list) or not 4 <= len(ring) <= 101:
        raise ValueError("The footprint must contain between 3 and 100 vertices")
    clean: list[list[float]] = []
    for point in ring:
        if (
            not isinstance(point, list)
            or len(point) < 2
            or not all(isinstance(value, (int, float)) for value in point[:2])
        ):
            raise ValueError("The footprint contains an invalid coordinate")
        longitude, latitude = float(point[0]), float(point[1])
        regions = (
            (24.3, 49.6, -125.0, -66.0),
            (51.0, 72.0, -179.0, -129.0),
            (18.8, 22.6, -161.0, -154.0),
        )
        if not any(s <= latitude <= n and w <= longitude <= e for s, n, w, e in regions):
            raise ValueError("The footprint must remain within the United States")
        clean.append([longitude, latitude])
    if clean[0] != clean[-1]:
        clean.append(clean[0])
    if len({tuple(point) for point in clean[:-1]}) < 3:
        raise ValueError("The footprint must contain at least three distinct vertices")
    return clean


def normalize_polygon(
    geojson: dict[str, Any],
    site_id: str,
    *,
    expected_latitude: float | None = None,
    expected_longitude: float | None = None,
) -> tuple[dict[str, Any], float]:
    ring = _extract_ring(geojson)
    mean_latitude = sum(point[1] for point in ring[:-1]) / (len(ring) - 1)
    mean_longitude = sum(point[0] for point in ring[:-1]) / (len(ring) - 1)
    if expected_latitude is not None and expected_longitude is not None:
        latitude_delta = math.radians(mean_latitude - expected_latitude)
        longitude_delta = math.radians(mean_longitude - expected_longitude)
        haversine = (
            math.sin(latitude_delta / 2) ** 2
            + math.cos(math.radians(expected_latitude))
            * math.cos(math.radians(mean_latitude))
            * math.sin(longitude_delta / 2) ** 2
        )
        distance_miles = EARTH_RADIUS_M * 2 * math.asin(min(1, math.sqrt(haversine))) / 1609.344
        if distance_miles > 50:
            raise ValueError("The footprint must remain near the selected U.S. candidate")
    cosine = math.cos(math.radians(mean_latitude))
    projected = [
        (
            EARTH_RADIUS_M * math.radians(longitude) * cosine,
            EARTH_RADIUS_M * math.radians(latitude),
        )
        for longitude, latitude in ring
    ]
    twice_area = sum(
        projected[index][0] * projected[index + 1][1]
        - projected[index + 1][0] * projected[index][1]
        for index in range(len(projected) - 1)
    )
    area_sq_mi = abs(twice_area) / 2 / SQ_M_PER_SQ_MI
    if area_sq_mi < 0.0001:
        raise ValueError("The drawn footprint is too small to analyze")
    if area_sq_mi > 10:
        raise ValueError("FortyGuard Basic-compatible footprints may not exceed 10 square miles")
    feature_collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"site_id": site_id, "purpose": "resource_estimator"},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        ],
    }
    return feature_collection, area_sq_mi


def calculate_resource_estimate(
    request: ResourceEstimatorRequest,
    polygon: dict[str, Any],
    area_sq_mi: float,
    thermal: ThermalMetrics,
    window: ThermalWindow,
) -> ResourceEstimate:
    window_hours = ((window.end_date - window.start_date).days + 1) * 24
    mean_delta = max(0.0, thermal.mean_temperature_c - request.reference_temperature_c)
    peak_delta = max(0.0, thermal.maximum_temperature_c - request.reference_temperature_c)
    system_pue_factor = {
        "dry": 1.18,
        "evaporative": 0.88,
        "hybrid": 1.0,
        "liquid": 0.82,
    }[request.cooling_system]
    adjusted_pue = request.baseline_pue + (
        mean_delta * request.pue_sensitivity_per_c * system_pue_factor
    )
    peak_pue = request.baseline_pue + (
        peak_delta * request.pue_sensitivity_per_c * system_pue_factor
    )
    average_power = request.it_load_mw * request.utilization * adjusted_pue
    peak_power = request.it_load_mw * peak_pue
    it_energy = request.it_load_mw * request.utilization * window_hours
    facility_energy = it_energy * adjusted_pue

    base_wue_low, base_wue_high = WUE_BANDS[request.cooling_system]
    water_heat_factor = 1 + mean_delta * (
        0.02 if request.cooling_system in {"evaporative", "hybrid"} else 0.005
    )
    wue_low = base_wue_low * water_heat_factor
    wue_high = base_wue_high * water_heat_factor
    low_liters = it_energy * 1000 * wue_low
    high_liters = it_energy * 1000 * wue_high
    annual_scale = 8760 / window_hours

    return ResourceEstimate(
        site_id=request.site_id,
        polygon=polygon,
        area_acres=round(area_sq_mi * ACRES_PER_SQ_MI, 2),
        area_sq_mi=round(area_sq_mi, 6),
        cooling_system=request.cooling_system,
        it_density_mw_per_acre=request.it_density_mw_per_acre,
        it_load_mw=request.it_load_mw,
        utilization=request.utilization,
        baseline_pue=request.baseline_pue,
        heat_adjusted_pue=round(adjusted_pue, 3),
        peak_pue=round(peak_pue, 3),
        average_facility_power_mw=round(average_power, 2),
        peak_facility_power_mw=round(peak_power, 2),
        window_it_energy_mwh=round(it_energy, 2),
        window_facility_energy_mwh=round(facility_energy, 2),
        window_water_liters_low=round(low_liters, 2),
        window_water_liters_high=round(high_liters, 2),
        window_water_gallons_low=round(low_liters / LITERS_PER_GALLON, 2),
        window_water_gallons_high=round(high_liters / LITERS_PER_GALLON, 2),
        illustrative_annual_energy_mwh=round(facility_energy * annual_scale, 2),
        illustrative_annual_water_gallons_low=round(
            low_liters / LITERS_PER_GALLON * annual_scale, 2
        ),
        illustrative_annual_water_gallons_high=round(
            high_liters / LITERS_PER_GALLON * annual_scale, 2
        ),
        wue_l_kwh_low=round(wue_low, 3),
        wue_l_kwh_high=round(wue_high, 3),
        thermal=thermal,
        confidence=0.72,
        assumptions=[
            (
                f"Planning capacity derives from {area_sq_mi * ACRES_PER_SQ_MI:.1f} acres Ã— "
                f"{request.it_density_mw_per_acre:.2f} MW/acre = {request.it_load_mw:g} MW nameplate IT load."
                if request.it_density_mw_per_acre is not None
                else f"{request.it_load_mw:g} MW nameplate IT load at {request.utilization * 100:.0f}% utilization."
            ),
            f"The facility operates at {request.utilization * 100:.0f}% utilization in this scenario.",
            f"Baseline PUE {request.baseline_pue:.2f}; temperature sensitivity {request.pue_sensitivity_per_c:.3f} PUE/°C above {request.reference_temperature_c:g}°C.",
            f"{request.cooling_system.title()} cooling uses an assumed direct WUE band of {base_wue_low:.2f}–{base_wue_high:.2f} L/kWh before the heat adjustment.",
            "Annual figures extrapolate the selected heat window and are illustrative, not a weather-normalized forecast.",
            "FortyGuard ambient temperature adjusts the scenario; acreage and design density are planning inputs, not a utility-capacity commitment.",
        ],
    )
