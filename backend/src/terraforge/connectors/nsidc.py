from __future__ import annotations

from terraforge.connectors.http import get_with_retry
from terraforge.contracts.models import AcquisitionResult, DatasetRequest
from terraforge.persistence.artifacts import ArtifactStore


class NsidcSeaIceConnector:
    dataset_id = "noaa-nsidc-g02135-v4"
    endpoint = (
        "https://noaadata.apps.nsidc.org/NOAA/G02135/north/daily/data/"
        "N_seaice_extent_daily_v4.0.csv"
    )

    def __init__(self, artifacts: ArtifactStore, timeout: float = 60):
        self.artifacts = artifacts
        self.timeout = timeout

    def validate_request(self, request: DatasetRequest) -> None:
        if request.dataset_id != self.dataset_id:
            raise ValueError("Connector dataset mismatch")
        if not set(request.variables) & {"sea_ice_concentration", "sea_ice_extent"}:
            raise ValueError("Sea Ice Index connector requires a sea-ice variable")

    async def fetch(self, run_id: str, request: DatasetRequest) -> AcquisitionResult:
        self.validate_request(request)
        response = await get_with_retry(self.endpoint, timeout=self.timeout)
        if b"Extent" not in response.content[:1000] and b"extent" not in response.content[:1000]:
            raise ValueError("Sea Ice Index response did not match the expected CSV schema")
        file = await self.artifacts.put_raw(
            run_id,
            self.dataset_id,
            "N_seaice_extent_daily_v4.0.csv",
            response.content,
            "text/csv",
        )
        return AcquisitionResult(
            dataset_id=self.dataset_id,
            provider="NOAA at NSIDC",
            source_request={"url": self.endpoint, "parameters": {}},
            files=[file],
            metadata={
                "product": "Sea Ice Index, Version 4 (G02135)",
                "units": "million square kilometers",
                "sampling_frequency": "daily",
                "spatial_definition": "Northern Hemisphere sea-ice extent at 15% concentration threshold",
                "source_grid": "25 km passive-microwave concentration grid",
                "coordinate_system": "polar stereographic source grid; hemispheric aggregate output",
                "time_zone": "calendar day",
                "missing_value": "CSV missing flag",
            },
        )

    async def metadata(self) -> dict:
        return {"dataset_id": self.dataset_id, "provider": "NOAA/NSIDC", "version": "4.0"}
