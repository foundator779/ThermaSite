from __future__ import annotations

import math

from terraforge.contracts.models import MonitoringSensitivity, MonitoringTriggerDirection

INDICATORS = {
    "vegetation_greenness": {
        "label": "NDVI anomaly",
        "detail": "Decrease from the same-season Sentinel-2 greenness baseline",
        "metric": "vegetation_ndvi_anomaly",
        "unit": "NDVI",
        "step": 0.01,
        "default_direction": MonitoringTriggerDirection.DECREASE,
        "thresholds": {"HIGH": 0.03, "BALANCED": 0.06, "IMPORTANT_ONLY": 0.10},
    },
    "vegetation_moisture": {
        "label": "NDMI anomaly",
        "detail": "Decrease from the same-season Sentinel-2 moisture baseline",
        "metric": "vegetation_ndmi_anomaly",
        "unit": "NDMI",
        "step": 0.01,
        "default_direction": MonitoringTriggerDirection.DECREASE,
        "thresholds": {"HIGH": 0.03, "BALANCED": 0.06, "IMPORTANT_ONLY": 0.10},
    },
    "vegetation_stress": {
        "label": "Stressed vegetation area",
        "detail": "Increase in area at or below the seasonal 25th percentile",
        "metric": "vegetation_stressed_area_pct",
        "unit": "%",
        "step": 1.0,
        "default_direction": MonitoringTriggerDirection.INCREASE,
        "thresholds": {"HIGH": 5.0, "BALANCED": 10.0, "IMPORTANT_ONLY": 20.0},
    },
    "satellite_coverage": {
        "label": "Satellite coverage",
        "detail": "Decrease in usable, cloud-free vegetation pixels",
        "metric": "vegetation_valid_coverage_pct",
        "unit": "%",
        "step": 1.0,
        "default_direction": MonitoringTriggerDirection.DECREASE,
        "thresholds": {"HIGH": 10.0, "BALANCED": 20.0, "IMPORTANT_ONLY": 30.0},
    },
    "temperature_anomaly": {
        "label": "Temperature anomaly",
        "detail": "Latest period compared with the validated baseline",
        "metric": "recent_temperature_anomaly_c",
        "unit": "°C",
        "step": 0.1,
        "default_direction": MonitoringTriggerDirection.EITHER,
        "thresholds": {"HIGH": 0.5, "BALANCED": 1.0, "IMPORTANT_ONLY": 1.5},
    },
    "precipitation_anomaly": {
        "label": "Precipitation anomaly",
        "detail": "Material change in recent precipitation conditions",
        "metric": "recent_precipitation_anomaly_pct",
        "unit": "%",
        "step": 1.0,
        "default_direction": MonitoringTriggerDirection.EITHER,
        "thresholds": {"HIGH": 10.0, "BALANCED": 20.0, "IMPORTANT_ONLY": 30.0},
    },
    "wildfire_activity": {
        "label": "Wildfire activity",
        "detail": "New NASA FIRMS detections inside the study area",
        "metric": "recent_fire_detection_count",
        "unit": "detections",
        "step": 1.0,
        "default_direction": MonitoringTriggerDirection.INCREASE,
        "thresholds": {"HIGH": 1.0, "BALANCED": 1.0, "IMPORTANT_ONLY": 2.0},
    },
    "species_evidence": {
        "label": "Species evidence",
        "detail": "Sampling-aware change in documented GBIF observations",
        "metric": "observed_species_count",
        "unit": "species",
        "step": 1.0,
        "default_direction": MonitoringTriggerDirection.DECREASE,
        "thresholds": {"HIGH": 5.0, "BALANCED": 10.0, "IMPORTANT_ONLY": 20.0},
    },
    "wetland_inventory": {
        "label": "Wetland inventory",
        "detail": "Mapped NWI acreage changes when the inventory updates",
        "metric": "nwi_mapped_wetland_acres",
        "unit": "acres",
        "step": 0.1,
        "default_direction": MonitoringTriggerDirection.DECREASE,
        "thresholds": {"HIGH": 0.5, "BALANCED": 2.0, "IMPORTANT_ONLY": 5.0},
    },
    "evidence_coverage": {
        "label": "Evidence coverage",
        "detail": "A required ecological source becomes unavailable",
        "metric": "ecological_evidence_available_count",
        "unit": "sources",
        "step": 1.0,
        "default_direction": MonitoringTriggerDirection.DECREASE,
        "thresholds": {"HIGH": 1.0, "BALANCED": 1.0, "IMPORTANT_ONLY": 1.0},
    },
    "water_level": {
        "label": "Water-level anomaly",
        "detail": "Latest wetland level compared with baseline",
        "metric": "latest_water_level_anomaly_ft",
        "unit": "ft",
        "step": 0.01,
        "default_direction": MonitoringTriggerDirection.EITHER,
        "thresholds": {"HIGH": 0.05, "BALANCED": 0.10, "IMPORTANT_ONLY": 0.20},
    },
    "dry_months": {
        "label": "Dry-month frequency",
        "detail": "Change in the fraction of unusually dry months",
        "metric": "dry_month_fraction_change",
        "unit": "fraction",
        "step": 0.005,
        "default_direction": MonitoringTriggerDirection.INCREASE,
        "thresholds": {"HIGH": 0.025, "BALANCED": 0.05, "IMPORTANT_ONLY": 0.10},
    },
    "sea_ice": {
        "label": "Sea-ice trend",
        "detail": "Meaningful change in the paired sea-ice trend",
        "metric": "sea_ice_trend_mkm2_per_decade",
        "unit": "M km²/decade",
        "step": 0.005,
        "default_direction": MonitoringTriggerDirection.DECREASE,
        "thresholds": {"HIGH": 0.025, "BALANCED": 0.05, "IMPORTANT_ONLY": 0.10},
    },
    "temperature_trend": {
        "label": "Temperature trend",
        "detail": "Change in the validated regional trend",
        "metric": "regional_temperature_trend_c_per_decade",
        "unit": "°C/decade",
        "step": 0.01,
        "default_direction": MonitoringTriggerDirection.EITHER,
        "thresholds": {"HIGH": 0.05, "BALANCED": 0.10, "IMPORTANT_ONLY": 0.20},
    },
}


def default_indicator_keys(habitat_type: str) -> list[str]:
    if habitat_type == "custom_habitat":
        return [
            "vegetation_greenness",
            "vegetation_moisture",
            "vegetation_stress",
            "temperature_anomaly",
            "precipitation_anomaly",
            "wildfire_activity",
            "species_evidence",
            "wetland_inventory",
            "evidence_coverage",
        ]
    if habitat_type == "everglades_wetland":
        return ["water_level", "dry_months", "temperature_trend"]
    return ["temperature_trend", "sea_ice"]


def build_thresholds(
    habitat_type: str,
    sensitivity: MonitoringSensitivity,
    indicator_keys: list[str],
    available_metrics: dict[str, object],
    custom_thresholds: dict[str, float] | None = None,
) -> tuple[list[str], dict[str, float]]:
    keys = list(dict.fromkeys(indicator_keys or default_indicator_keys(habitat_type)))
    unknown = set(keys) - set(INDICATORS)
    if unknown:
        raise ValueError(f"Unknown monitoring indicators: {sorted(unknown)}")

    thresholds = {
        definition["metric"]: float(definition["thresholds"][sensitivity.value])
        for key in keys
        if (definition := INDICATORS[key]) and definition["metric"] in available_metrics
    }
    if custom_thresholds:
        invalid = {
            metric
            for metric, threshold in custom_thresholds.items()
            if metric not in thresholds
            or isinstance(threshold, bool)
            or not math.isfinite(float(threshold))
            or threshold <= 0
        }
        if invalid:
            raise ValueError(f"Invalid monitoring thresholds: {sorted(invalid)}")
        thresholds.update({metric: float(value) for metric, value in custom_thresholds.items()})
    if not thresholds:
        raise ValueError("The completed run has no metrics for the selected monitoring indicators")
    active_keys = [key for key in keys if INDICATORS[key]["metric"] in thresholds]
    return active_keys, thresholds


def build_trigger_directions(
    indicator_keys: list[str],
    custom_directions: dict[str, MonitoringTriggerDirection] | None = None,
) -> dict[str, MonitoringTriggerDirection]:
    active_keys = list(dict.fromkeys(indicator_keys))
    unknown = set(active_keys) - set(INDICATORS)
    if unknown:
        raise ValueError(f"Unknown monitoring indicators: {sorted(unknown)}")
    directions = {
        key: INDICATORS[key]["default_direction"]
        for key in active_keys
    }
    if custom_directions:
        invalid = set(custom_directions) - set(active_keys)
        if invalid:
            raise ValueError(f"Invalid monitoring trigger directions: {sorted(invalid)}")
        directions.update(custom_directions)
    return directions


def direction_for_metric(
    indicator_keys: list[str],
    trigger_directions: dict[str, MonitoringTriggerDirection],
    metric: str,
) -> MonitoringTriggerDirection:
    key = next(
        (
            indicator_key
            for indicator_key in indicator_keys
            if INDICATORS.get(indicator_key, {}).get("metric") == metric
        ),
        None,
    )
    if key is None:
        return MonitoringTriggerDirection.EITHER
    return trigger_directions.get(key, INDICATORS[key]["default_direction"])
