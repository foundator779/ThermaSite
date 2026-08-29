from __future__ import annotations

import json
import math

from terraforge.connectors.http import get_with_retry
from terraforge.contracts.models import AcquisitionResult, DatasetRequest
from terraforge.persistence.artifacts import ArtifactStore

_STATION_CATALOG: list[tuple[str, float, float]] | None = None


def _geometry_bounds(request: DatasetRequest) -> tuple[float, float, float, float]:
    ring = request.geometry.coordinates[0]
    longitudes = [float(point[0]) for point in ring]
    latitudes = [float(point[1]) for point in ring]
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


def _geometry_center(request: DatasetRequest) -> tuple[float, float]:
    west, south, east, north = _geometry_bounds(request)
    return (west + east) / 2, (south + north) / 2


class AreaNoaaClimateConnector:
    dataset_id = "noaa-ncei-ghcnd-user-area"
    endpoint = "https://www.ncei.noaa.gov/access/services/data/v1"
    station_catalog_endpoint = (
        "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt"
    )

    def __init__(self, artifacts: ArtifactStore, timeout: float = 60):
        self.artifacts = artifacts
        self.timeout = timeout

    def validate_request(self, request: DatasetRequest) -> None:
        if request.dataset_id != self.dataset_id:
            raise ValueError("Connector dataset mismatch")
        if request.geometry.type != "Polygon":
            raise ValueError("Area NOAA acquisition requires polygon geometry")
        if not {"air_temperature", "precipitation"}.intersection(request.variables):
            raise ValueError("Area NOAA acquisition requires climate variables")

    async def _station_catalog(self) -> list[tuple[str, float, float]]:
        global _STATION_CATALOG
        if _STATION_CATALOG is not None:
            return _STATION_CATALOG
        response = await get_with_retry(self.station_catalog_endpoint, timeout=self.timeout)
        stations: list[tuple[str, float, float]] = []
        for line in response.text.splitlines():
            if len(line) < 30 or not line.startswith("US"):
                continue
            try:
                stations.append(
                    (line[0:11].strip(), float(line[12:20]), float(line[21:30]))
                )
            except ValueError:
                continue
        if not stations:
            raise ValueError("NOAA GHCN station catalog contained no U.S. stations")
        _STATION_CATALOG = stations
        return stations

    async def _nearby_station_ids(
        self,
        west: float,
        south: float,
        east: float,
        north: float,
        padding: float,
    ) -> list[str]:
        center_lng = (west + east) / 2
        center_lat = (south + north) / 2
        candidates = [
            station
            for station in await self._station_catalog()
            if south - padding <= station[1] <= north + padding
            and west - padding <= station[2] <= east + padding
        ]

        def distance(station: tuple[str, float, float]) -> float:
            latitude_miles = (station[1] - center_lat) * 69.0
            longitude_miles = (
                (station[2] - center_lng) * 69.0 * math.cos(math.radians(center_lat))
            )
            return math.hypot(latitude_miles, longitude_miles)

        return [station[0] for station in sorted(candidates, key=distance)[:8]]

    async def fetch(self, run_id: str, request: DatasetRequest) -> AcquisitionResult:
        self.validate_request(request)
        west, south, east, north = _geometry_bounds(request)
        center_lng, center_lat = _geometry_center(request)
        records: list[dict] = []
        response = None
        params: dict[str, object] = {}
        # A small expansion provides a defensible nearby station when the drawn habitat
        # contains no long-running GHCN station itself.
        for padding in (0.0, 0.15, 0.35, 0.7):
            station_ids = await self._nearby_station_ids(west, south, east, north, padding)
            if not station_ids:
                continue
            params = {
                "dataset": "daily-summaries",
                "stations": ",".join(station_ids),
                "dataTypes": "TAVG,TMAX,TMIN,PRCP",
                "startDate": request.start_date.isoformat(),
                "endDate": request.end_date.isoformat(),
                "format": "json",
                "units": "metric",
                "includeAttributes": "false",
                "includeStationName": "true",
                "includeStationLocation": "true",
            }
            response = await get_with_retry(self.endpoint, params=params, timeout=self.timeout)
            payload = response.json()
            records = payload if isinstance(payload, list) else []
            if records and any(
                "TAVG" in item or ("TMAX" in item and "TMIN" in item) for item in records
            ):
                break
        if not records:
            raise ValueError("NOAA found no usable GHCN observations near the selected area")
        stations = sorted({str(item.get("STATION", "unknown")) for item in records})
        content = json.dumps(records, separators=(",", ":")).encode()
        file = await self.artifacts.put_raw(
            run_id, self.dataset_id, "ghcnd_user_area.json", content, "application/json"
        )
        return AcquisitionResult(
            dataset_id=self.dataset_id,
            provider="NOAA National Centers for Environmental Information",
            source_request={"url": str(response.request.url), "parameters": params},
            files=[file],
            metadata={
                "station_ids": stations,
                "station_count": len(stations),
                "coordinates": {"latitude": center_lat, "longitude": center_lng},
                "units": "degrees Celsius and millimeters",
                "sampling_frequency": "daily",
                "row_count": len(records),
                "selection": "GHCN stations inside or nearest to the user-drawn area",
                "license": "U.S. Government work / NOAA data",
            },
        )


class AreaNasaPowerConnector:
    dataset_id = "nasa-power-merra2-user-area"
    endpoint = "https://power.larc.nasa.gov/api/temporal/monthly/point"

    def __init__(self, artifacts: ArtifactStore, timeout: float = 60):
        self.artifacts = artifacts
        self.timeout = timeout

    def validate_request(self, request: DatasetRequest) -> None:
        if request.dataset_id != self.dataset_id:
            raise ValueError("Connector dataset mismatch")
        if request.geometry.type != "Polygon":
            raise ValueError("Area NASA acquisition requires polygon geometry")

    async def fetch(self, run_id: str, request: DatasetRequest) -> AcquisitionResult:
        self.validate_request(request)
        longitude, latitude = _geometry_center(request)
        params = {
            "latitude": round(latitude, 5),
            "longitude": round(longitude, 5),
            "parameters": "T2M,PRECTOTCORR",
            "community": "AG",
            "start": request.start_date.year,
            "end": request.end_date.year,
            "format": "JSON",
        }
        response = await get_with_retry(self.endpoint, params=params, timeout=self.timeout)
        payload = response.json()
        parameters = payload.get("properties", {}).get("parameter", {})
        if not {"T2M", "PRECTOTCORR"}.issubset(parameters):
            raise ValueError("NASA POWER returned incomplete climate data for the selected area")
        file = await self.artifacts.put_raw(
            run_id,
            self.dataset_id,
            "power_merra2_user_area.json",
            response.content,
            "application/json",
        )
        return AcquisitionResult(
            dataset_id=self.dataset_id,
            provider="NASA Langley Research Center POWER",
            source_request={"url": str(response.request.url), "parameters": params},
            files=[file],
            metadata={
                "parameters": ["T2M", "PRECTOTCORR"],
                "units": "degrees Celsius and millimeters per month",
                "sampling_frequency": "monthly",
                "spatial_resolution": "MERRA-2 point at the selected-area centroid",
                "coordinates": {"latitude": latitude, "longitude": longitude},
                "row_count": len(parameters["T2M"]),
            },
        )
