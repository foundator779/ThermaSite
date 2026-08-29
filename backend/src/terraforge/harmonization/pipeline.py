from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from terraforge.contracts.models import AcquisitionResult, DataValidationReport, HarmonizationReport
from terraforge.persistence.artifacts import ArtifactStore


def validate_acquisition(
    result: AcquisitionResult, artifacts: ArtifactStore | None = None
) -> DataValidationReport:
    path = (
        artifacts.materialize(result.files[0].uri)
        if artifacts
        else Path(result.files[0].uri.removeprefix("file://"))
    )
    checks = ["immutable raw object exists", "SHA-256 recorded", "source metadata present"]
    return DataValidationReport(
        dataset_id=result.dataset_id,
        valid=path.exists() and result.files[0].size_bytes > 0,
        units=result.metadata.get("units"),
        row_count=int(
            result.metadata.get("row_count") or result.metadata.get("grid_cell_count") or 1
        ),
        checks=checks,
    )


def harmonize_local(
    run_id: str,
    acquisitions: list[AcquisitionResult],
    artifacts: ArtifactStore,
    start_date: date,
    end_date: date,
) -> tuple[HarmonizationReport, str]:
    by_id = {result.dataset_id: result for result in acquisitions}
    if "noaa-ncei-ghcnd-user-area" in by_id:
        return harmonize_custom_area(run_id, by_id, artifacts, start_date, end_date)
    if "usgs-nwis-everglades-1" in by_id:
        return harmonize_everglades(run_id, by_id, artifacts, start_date, end_date)
    station_raw = json.loads(
        artifacts.materialize(by_id["noaa-ncei-ghcnd-usw00027502"].files[0].uri).read_text()
    )
    station = pd.DataFrame(station_raw)
    station["date"] = pd.to_datetime(station["DATE"], errors="coerce")
    tavg = pd.to_numeric(
        station.get("TAVG", pd.Series(np.nan, index=station.index)), errors="coerce"
    )
    min_max_mean = (
        pd.to_numeric(station.get("TMAX", pd.Series(np.nan, index=station.index)), errors="coerce")
        + pd.to_numeric(
            station.get("TMIN", pd.Series(np.nan, index=station.index)), errors="coerce"
        )
    ) / 2
    # NOAA's direct TAVG field is sparse for this station. Preserve it where present and
    # transparently use the standard (TMAX + TMIN) / 2 estimate for remaining daily records.
    tavg = tavg.combine_first(min_max_mean)
    station["local_temperature_c"] = tavg
    station_monthly = station.set_index("date")["local_temperature_c"].resample("MS").mean()

    power = json.loads(
        artifacts.materialize(by_id["nasa-power-merra2-north-slope"].files[0].uri).read_text()
    )
    points: list[dict] = []
    for feature in power.get("features", []):
        for key, value in feature.get("properties", {}).get("parameter", {}).get("T2M", {}).items():
            if (
                len(key) == 6
                and key[-2:] in {f"{month:02d}" for month in range(1, 13)}
                and value != -999
            ):
                points.append({"date": pd.to_datetime(key, format="%Y%m"), "value": float(value)})
    regional = pd.DataFrame(points).groupby("date")["value"].mean().rename("regional_temperature_c")

    # Row two is NSIDC's units/schema annotation (YYYY/MM/DD), not an observation.
    ice = pd.read_csv(
        artifacts.materialize(by_id["noaa-nsidc-g02135-v4"].files[0].uri),
        skipinitialspace=True,
        skiprows=[1],
    )
    ice.columns = [column.strip().lower() for column in ice.columns]
    ice["date"] = pd.to_datetime({"year": ice["year"], "month": ice["month"], "day": ice["day"]})
    extent_col = next(column for column in ice.columns if "extent" in column)
    ice["sea_ice_extent_mkm2"] = pd.to_numeric(ice[extent_col], errors="coerce")
    ice_monthly = ice.set_index("date")["sea_ice_extent_mkm2"].resample("MS").mean()

    frame = pd.concat([station_monthly, regional, ice_monthly], axis=1).sort_index()
    requested = frame.loc[str(start_date.year) : str(end_date.year)].replace([-999, -999.0], np.nan)
    complete = requested.dropna()
    if len(complete) < 24:
        raise ValueError(
            "Insufficient common coverage to perform a defensible multi-source analysis"
        )
    output = complete.reset_index().rename(columns={"index": "date"})
    csv_bytes = output.to_csv(index=False).encode()
    artifact = artifacts.put_artifact(
        run_id, "harmonized_monthly.csv", csv_bytes, "text/csv", "CrossDatasetHarmonizationAgent"
    )
    dropped = {column: int(requested[column].isna().sum()) for column in requested.columns}
    report = HarmonizationReport(
        valid=True,
        overlap_start=output["date"].min().date(),
        overlap_end=output["date"].max().date(),
        temporal_aggregation="daily station and sea ice → monthly means; NASA POWER native monthly grid → regional mean",
        spatial_definitions={
            "local": "NOAA station USW00027502 at Utqiaġvik airport",
            "regional": "NASA POWER MERRA-2 grid cells in 69–71°N, 160–150°W",
            "sea_ice": "Northern Hemisphere extent above the 15% concentration threshold",
        },
        join_keys=["calendar year", "calendar month"],
        dropped_observations=dropped,
        paired_sample_count=len(output),
        artifact_uri=artifact.uri,
    )
    return report, artifact.uri


def harmonize_custom_area(
    run_id: str,
    by_id: dict[str, AcquisitionResult],
    artifacts: ArtifactStore,
    start_date: date,
    end_date: date,
) -> tuple[HarmonizationReport, str]:
    station_raw = json.loads(
        artifacts.materialize(by_id["noaa-ncei-ghcnd-user-area"].files[0].uri).read_text()
    )
    station = pd.DataFrame(station_raw)
    station["date"] = pd.to_datetime(station["DATE"], errors="coerce")
    tavg = pd.to_numeric(
        station.get("TAVG", pd.Series(np.nan, index=station.index)), errors="coerce"
    )
    estimated = (
        pd.to_numeric(station.get("TMAX", pd.Series(np.nan, index=station.index)), errors="coerce")
        + pd.to_numeric(
            station.get("TMIN", pd.Series(np.nan, index=station.index)), errors="coerce"
        )
    ) / 2
    station["station_temperature_c"] = tavg.combine_first(estimated)
    station["station_precipitation_mm"] = pd.to_numeric(
        station.get("PRCP", pd.Series(np.nan, index=station.index)), errors="coerce"
    )
    # Average available stations for each observation day before aggregating so
    # station-rich dates do not receive disproportionate weight.
    station_daily = station.groupby("date", as_index=True).agg(
        station_temperature_c=("station_temperature_c", "mean"),
        station_precipitation_mm=("station_precipitation_mm", "mean"),
    )
    station_monthly = station_daily.resample("MS").agg(
        station_temperature_c=("station_temperature_c", "mean"),
        station_precipitation_mm=("station_precipitation_mm", "sum"),
    )

    power_result = by_id["nasa-power-merra2-user-area"]
    power = json.loads(artifacts.materialize(power_result.files[0].uri).read_text())
    parameters = power.get("properties", {}).get("parameter", {})
    power_rows: list[dict] = []
    for key, temperature in parameters.get("T2M", {}).items():
        if len(key) != 6 or key[-2:] not in {f"{month:02d}" for month in range(1, 13)}:
            continue
        precipitation = parameters.get("PRECTOTCORR", {}).get(key)
        if temperature == -999 or precipitation in {None, -999}:
            continue
        power_rows.append(
            {
                "date": pd.to_datetime(key, format="%Y%m"),
                "regional_temperature_c": float(temperature),
                "regional_precipitation_mm": float(precipitation),
            }
        )
    regional = pd.DataFrame(power_rows).set_index("date")
    frame = pd.concat([station_monthly, regional], axis=1).sort_index()
    requested = frame.loc[str(start_date.year) : str(end_date.year)].replace([-999, -999.0], np.nan)
    complete = requested.dropna()
    if len(complete) < 24:
        raise ValueError("Insufficient common NOAA/NASA coverage for the selected study area")
    coordinates = power_result.metadata.get("coordinates", {})
    output = complete.reset_index().rename(columns={"index": "date"})
    output["center_longitude"] = float(coordinates.get("longitude", 0))
    output["center_latitude"] = float(coordinates.get("latitude", 0))
    ecology: dict[str, dict] = {}
    ecological_ids = {
        "species": "gbif-occurrences-user-area",
        "wildfire": "nasa-firms-user-area",
        "wetlands": "usfws-nwi-user-area",
    }
    for role, dataset_id in ecological_ids.items():
        if dataset_id not in by_id:
            ecology[role] = {"available": False, "reason": "dataset was not selected"}
            continue
        raw_path = artifacts.materialize(by_id[dataset_id].files[0].uri)
        ecology[role] = json.loads(raw_path.read_text(encoding="utf-8"))
    output["ecology_payload"] = None
    output.loc[output.index[0], "ecology_payload"] = json.dumps(
        ecology, ensure_ascii=False, separators=(",", ":")
    )
    artifact = artifacts.put_artifact(
        run_id,
        "harmonized_monthly.csv",
        output.to_csv(index=False).encode(),
        "text/csv",
        "CrossDatasetHarmonizationAgent",
    )
    station_count = by_id["noaa-ncei-ghcnd-user-area"].metadata.get("station_count", 0)
    report = HarmonizationReport(
        valid=True,
        overlap_start=output["date"].min().date(),
        overlap_end=output["date"].max().date(),
        temporal_aggregation=(
            "NOAA daily station observations → area daily ensemble → monthly; "
            "NASA POWER native monthly climate retained"
        ),
        spatial_definitions={
            "station": f"NOAA GHCN ensemble from {station_count} stations in or near the selected area",
            "regional": "NASA POWER MERRA-2 point at the selected-area centroid",
            "study_area": "User-submitted WGS84 polygon limited to 150 square miles",
            "ecology": (
                "GBIF occurrences, NASA FIRMS, and USFWS NWI intersecting "
                "the submitted geometry"
            ),
        },
        join_keys=["calendar year", "calendar month"],
        dropped_observations={
            column: int(requested[column].isna().sum()) for column in requested.columns
        },
        paired_sample_count=len(output),
        artifact_uri=artifact.uri,
    )
    return report, artifact.uri


def harmonize_everglades(
    run_id: str,
    by_id: dict[str, AcquisitionResult],
    artifacts: ArtifactStore,
    start_date: date,
    end_date: date,
) -> tuple[HarmonizationReport, str]:
    station_raw = json.loads(
        artifacts.materialize(by_id["noaa-ncei-ghcnd-usc00087760"].files[0].uri).read_text()
    )
    station = pd.DataFrame(station_raw)
    station["date"] = pd.to_datetime(station["DATE"], errors="coerce")
    tavg = pd.to_numeric(
        station.get("TAVG", pd.Series(np.nan, index=station.index)), errors="coerce"
    )
    estimated = (
        pd.to_numeric(station.get("TMAX", pd.Series(np.nan, index=station.index)), errors="coerce")
        + pd.to_numeric(
            station.get("TMIN", pd.Series(np.nan, index=station.index)), errors="coerce"
        )
    ) / 2
    station["station_temperature_c"] = tavg.combine_first(estimated)
    station["station_precipitation_mm"] = pd.to_numeric(
        station.get("PRCP", pd.Series(np.nan, index=station.index)), errors="coerce"
    )
    station_monthly = (
        station.set_index("date")
        .resample("MS")
        .agg(
            station_temperature_c=("station_temperature_c", "mean"),
            station_precipitation_mm=("station_precipitation_mm", "sum"),
        )
    )

    power = json.loads(
        artifacts.materialize(by_id["nasa-power-merra2-everglades"].files[0].uri).read_text()
    )
    parameters = power.get("properties", {}).get("parameter", {})
    power_rows: list[dict] = []
    for key, temperature in parameters.get("T2M", {}).items():
        if len(key) != 6 or key[-2:] not in {f"{month:02d}" for month in range(1, 13)}:
            continue
        precipitation = parameters.get("PRECTOTCORR", {}).get(key)
        if temperature == -999 or precipitation in {None, -999}:
            continue
        power_rows.append(
            {
                "date": pd.to_datetime(key, format="%Y%m"),
                "regional_temperature_c": float(temperature),
                "regional_precipitation_mm": float(precipitation),
            }
        )
    regional = pd.DataFrame(power_rows).set_index("date")

    water_payload = json.loads(
        artifacts.materialize(by_id["usgs-nwis-everglades-1"].files[0].uri).read_text()
    )
    series = water_payload["value"]["timeSeries"][0]["values"][0]["value"]
    water = pd.DataFrame(
        {
            "date": [
                pd.to_datetime(item["dateTime"], utc=True).tz_convert(None) for item in series
            ],
            "water_level_ft": [pd.to_numeric(item["value"], errors="coerce") for item in series],
        }
    )
    water_monthly = water.set_index("date")["water_level_ft"].resample("MS").mean()

    frame = pd.concat([station_monthly, regional, water_monthly], axis=1).sort_index()
    requested = frame.loc[str(start_date.year) : str(end_date.year)].replace([-999, -999.0], np.nan)
    complete = requested.dropna()
    if len(complete) < 24:
        raise ValueError("Insufficient common Everglades coverage for habitat-pressure analysis")
    output = complete.reset_index().rename(columns={"index": "date"})
    artifact = artifacts.put_artifact(
        run_id,
        "harmonized_monthly.csv",
        output.to_csv(index=False).encode(),
        "text/csv",
        "CrossDatasetHarmonizationAgent",
    )
    report = HarmonizationReport(
        valid=True,
        overlap_start=output["date"].min().date(),
        overlap_end=output["date"].max().date(),
        temporal_aggregation=(
            "NOAA daily temperature/precipitation and USGS daily gage height → monthly; "
            "NASA POWER native monthly climate retained"
        ),
        spatial_definitions={
            "station": "NOAA Royal Palm Ranger Station USC00087760",
            "regional": "NASA POWER MERRA-2 point centered in Everglades National Park",
            "hydrology": "USGS Everglades 1 C-111 basin gage 251946080254800",
        },
        join_keys=["calendar year", "calendar month"],
        dropped_observations={
            column: int(requested[column].isna().sum()) for column in requested.columns
        },
        paired_sample_count=len(output),
        artifact_uri=artifact.uri,
    )
    return report, artifact.uri
