from __future__ import annotations

from typing import ClassVar

from terraforge.connectors.http import get_with_retry
from terraforge.contracts.models import AcquisitionResult, DatasetRequest
from terraforge.persistence.artifacts import ArtifactStore


class NasaPowerRegionalConnector:
    dataset_id = "nasa-power-merra2-north-slope"
    endpoint = "https://power.larc.nasa.gov/api/temporal/monthly/regional"
    bbox: ClassVar[dict[str, int]] = {
        "latitude-min": 69,
        "latitude-max": 71,
        "longitude-min": -160,
        "longitude-max": -150,
    }

    def __init__(self, artifacts: ArtifactStore, timeout: float = 60):
        self.artifacts = artifacts
        self.timeout = timeout

    def validate_request(self, request: DatasetRequest) -> None:
        if request.dataset_id != self.dataset_id:
            raise ValueError("Connector dataset mismatch")
        if "air_temperature" not in request.variables:
            raise ValueError("NASA POWER connector requires air_temperature")
        if self.bbox["longitude-max"] - self.bbox["longitude-min"] > 10:
            raise ValueError("NASA POWER regional longitude span may not exceed 10 degrees")

    async def fetch(self, run_id: str, request: DatasetRequest) -> AcquisitionResult:
        self.validate_request(request)
        params = {
            **self.bbox,
            "parameters": "T2M",
            "community": "SB",
            "start": request.start_date.year,
            "end": request.end_date.year,
            "format": "JSON",
        }
        response = await get_with_retry(self.endpoint, params=params, timeout=self.timeout)
        payload = response.json()
        features = payload.get("features", [])
        if not features:
            raise ValueError("NASA POWER returned no regional grid features")
        file = await self.artifacts.put_raw(
            run_id,
            self.dataset_id,
            "power_merra2_north_slope.json",
            response.content,
            "application/json",
        )
        return AcquisitionResult(
            dataset_id=self.dataset_id,
            provider="NASA Langley Research Center POWER",
            source_request={"url": str(response.request.url), "parameters": params},
            files=[file],
            metadata={
                "parameter": "T2M",
                "units": "degrees Celsius",
                "sampling_frequency": "monthly",
                "spatial_resolution": "0.5° × 0.625° MERRA-2 grid",
                "coordinate_system": "WGS84 longitude/latitude",
                "bbox": self.bbox,
                "time_zone": "UTC-derived monthly product",
                "missing_value": -999,
                "grid_cell_count": len(features),
            },
        )

    async def metadata(self) -> dict:
        return {"dataset_id": self.dataset_id, "provider": "NASA POWER", "parameter": "T2M"}
