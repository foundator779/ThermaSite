from __future__ import annotations

import json

from terraforge.connectors.http import get_with_retry
from terraforge.contracts.models import AcquisitionResult, DatasetRequest
from terraforge.persistence.artifacts import ArtifactStore


class NoaaStationConnector:
    dataset_id = "noaa-ncei-ghcnd-usw00027502"
    endpoint = "https://www.ncei.noaa.gov/access/services/data/v1"
    station_id = "USW00027502"

    def __init__(self, artifacts: ArtifactStore, timeout: float = 60):
        self.artifacts = artifacts
        self.timeout = timeout

    def validate_request(self, request: DatasetRequest) -> None:
        if request.dataset_id != self.dataset_id:
            raise ValueError("Connector dataset mismatch")
        if not set(request.variables) & {"air_temperature", "TAVG", "TMAX", "TMIN"}:
            raise ValueError("GHCN connector requires an air temperature variable")
        if request.end_date < request.start_date:
            raise ValueError("End date must be after start date")

    async def fetch(self, run_id: str, request: DatasetRequest) -> AcquisitionResult:
        self.validate_request(request)
        params = {
            "dataset": "daily-summaries",
            "stations": self.station_id,
            "startDate": request.start_date.isoformat(),
            "endDate": request.end_date.isoformat(),
            "format": "json",
            "units": "metric",
            "includeAttributes": "true",
        }
        response = await get_with_retry(self.endpoint, params=params, timeout=self.timeout)
        records = response.json()
        if not isinstance(records, list) or not records:
            raise ValueError("NOAA station response contained no observations")
        if not any(
            "TAVG" in record or ("TMAX" in record and "TMIN" in record) for record in records
        ):
            raise ValueError("NOAA station response contained no usable temperature fields")
        content = json.dumps(records, separators=(",", ":")).encode()
        file = await self.artifacts.put_raw(
            run_id, self.dataset_id, "ghcnd_usw00027502.json", content, "application/json"
        )
        return AcquisitionResult(
            dataset_id=self.dataset_id,
            provider="NOAA National Centers for Environmental Information",
            source_request={"url": str(response.request.url), "parameters": params},
            files=[file],
            metadata={
                "station_id": self.station_id,
                "station_name": "Wiley Post–Will Rogers Memorial Airport, Utqiaġvik",
                "coordinates": {"latitude": 71.2834, "longitude": -156.7815},
                "units": "degrees Celsius",
                "sampling_frequency": "daily",
                "time_zone": "station observation day; NOAA daily-summary convention",
                "missing_value": "field absent or blank",
                "license": "U.S. Government work / NOAA data",
                "row_count": len(records),
            },
        )

    async def metadata(self) -> dict:
        return {"dataset_id": self.dataset_id, "provider": "NOAA NCEI", "station": self.station_id}
