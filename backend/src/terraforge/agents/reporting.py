from __future__ import annotations


def evidence_summary(metrics: dict) -> str:
    if "water_level_trend_ft_per_decade" in metrics:
        return wetland_evidence_summary(metrics)
    if "regional_precipitation_trend_mm_per_decade" in metrics:
        return custom_area_evidence_summary(metrics)
    slope = metrics.get("regional_temperature_trend_c_per_decade")
    p_value = metrics.get("regional_temperature_p_value")
    season = metrics.get("fastest_warming_season", "the leading season")
    correlation = metrics.get("temperature_sea_ice_correlation")
    if any(value is None for value in (slope, p_value, correlation)):
        return "The run completed, but one or more expected structured metrics were unavailable."
    significance = (
        "statistically significant"
        if p_value < 0.05
        else "not statistically significant at α = 0.05"
    )
    return (
        f"Regional temperature changed {slope:+.2f} °C per decade and was {significance}. "
        f"{season} showed the largest modeled seasonal change. The paired annual temperature and "
        f"Northern Hemisphere sea-ice extent series had r = {correlation:+.2f}; this is an association, "
        "not evidence that sea-ice change caused the measured temperature trend."
    )


def wetland_evidence_summary(metrics: dict) -> str:
    trend = metrics.get("water_level_trend_ft_per_decade")
    p_value = metrics.get("water_level_p_value")
    anomaly = metrics.get("latest_water_level_anomaly_ft")
    dry_change = metrics.get("dry_month_fraction_change")
    agreement = metrics.get("climate_source_agreement")
    if any(value is None for value in (trend, p_value, anomaly, dry_change, agreement)):
        return "The wetland run completed, but one or more structured habitat indicators were unavailable."
    significance = "statistically significant" if p_value < 0.05 else "not significant at α = 0.05"
    return (
        f"Everglades mean water level changed {trend:+.2f} ft per decade and was {significance}. "
        f"The latest five-year mean was {anomaly:+.2f} ft relative to the first five-year baseline, "
        f"while the dry-month fraction changed {dry_change:+.1%}. Independent NOAA and NASA "
        f"temperature anomalies agreed at r = {agreement:+.2f}. These are habitat-pressure "
        "indicators, not proof of ecological harm or causation."
    )


def custom_area_evidence_summary(metrics: dict) -> str:
    temperature_trend = metrics.get("regional_temperature_trend_c_per_decade")
    temperature_p = metrics.get("regional_temperature_p_value")
    precipitation_trend = metrics.get("regional_precipitation_trend_mm_per_decade")
    precipitation_p = metrics.get("regional_precipitation_p_value")
    recent_temperature = metrics.get("recent_temperature_anomaly_c")
    recent_precipitation = metrics.get("recent_precipitation_anomaly_pct")
    agreement = metrics.get("climate_source_agreement")
    species_count = metrics.get("observed_species_count", 0)
    fire_count = metrics.get("recent_fire_detection_count", 0)
    wetland_count = metrics.get("nwi_wetland_feature_count", 0)
    condition = metrics.get("ecological_condition_classification", "not classified")
    ecological_sources = metrics.get("ecological_evidence_available_count", 0)
    current_ndvi = metrics.get("vegetation_current_ndvi")
    baseline_ndvi = metrics.get("vegetation_baseline_ndvi")
    ndvi_anomaly = metrics.get("vegetation_ndvi_anomaly")
    current_ndmi = metrics.get("vegetation_current_ndmi")
    ndmi_anomaly = metrics.get("vegetation_ndmi_anomaly")
    stressed_area = metrics.get("vegetation_stressed_area_pct")
    satellite_coverage = metrics.get("vegetation_valid_coverage_pct")
    if any(
        value is None
        for value in (
            temperature_trend,
            temperature_p,
            precipitation_trend,
            precipitation_p,
            recent_temperature,
            recent_precipitation,
            agreement,
        )
    ):
        return "The selected-area run completed, but one or more habitat-climate indicators were unavailable."
    temperature_significance = (
        "statistically significant" if temperature_p < 0.05 else "not significant at α = 0.05"
    )
    precipitation_significance = (
        "statistically significant" if precipitation_p < 0.05 else "not significant at α = 0.05"
    )
    satellite_summary = ""
    if all(
        value is not None
        for value in (
            current_ndvi,
            baseline_ndvi,
            ndvi_anomaly,
            current_ndmi,
            ndmi_anomaly,
            stressed_area,
            satellite_coverage,
        )
    ):
        satellite_summary = (
            f" Sentinel-2 measured median NDVI {current_ndvi:.2f} against a same-season "
            f"five-year baseline of {baseline_ndvi:.2f} ({ndvi_anomaly:+.2f}), and median "
            f"NDMI {current_ndmi:.2f} ({ndmi_anomaly:+.2f} anomaly). "
            f"{stressed_area:.1f}% of baseline-vegetated area was below its seasonal 25th "
            f"percentile, with {satellite_coverage:.1f}% valid satellite coverage."
        )
    else:
        satellite_summary = (
            " Sentinel-2 vegetation evidence was unavailable or did not meet the minimum "
            "scene-count and cloud-free coverage gates."
        )
    return (
        f"Within the user-selected area, regional temperature changed {temperature_trend:+.2f} °C "
        f"per decade and was {temperature_significance}. Precipitation changed "
        f"{precipitation_trend:+.1f} mm per decade and was {precipitation_significance}. The latest "
        f"five-year period was {recent_temperature:+.2f} °C and {recent_precipitation:+.1f}% "
        f"precipitation relative to the first five-year baseline. Independent NOAA and NASA "
        f"temperature anomalies agreed at r = {agreement:+.2f}. These are climate-pressure "
        f"indicators. Across {ecological_sources}/3 ecological evidence roles, GBIF documented "
        f"{species_count} species in the retrieved occurrence sample; NASA FIRMS found "
        f"{fire_count} recent fire detections; and "
        f"USFWS NWI returned {wetland_count} intersecting mapped wetland features. The synthesized "
        f"condition is {condition}.{satellite_summary} Occurrences reflect sampling effort, and "
        "satellite indices indicate possible vegetation stress rather than proving its cause. "
        "These indicators do "
        "not prove population change, ecological harm, or causation."
    )
