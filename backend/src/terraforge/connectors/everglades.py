from __future__ import annotations

import json

from terraforge.connectors.http import get_with_retry
from terraforge.contracts.models import AcquisitionResult, DatasetRequest
from terraforge.persistence.artifacts import ArtifactStore


class EvergladesNoaaConnector:
    dataset_id = "noaa-ncei-ghcnd-usc00087760"
    endpoint = "https://www.ncei.noaa.gov/access/services/data/v1"
    station_id = "USC00087760"

    def __init__(self, artifacts: ArtifactStore, timeout: float = 60):
        self.artifacts = artifacts
        self.timeout = timeout

    def validate_request(self, request: DatasetRequest) -> None:
        if request.dataset_id != self.dataset_id:
            raise ValueError("Connector dataset mismatch")
        if not set(request.variables) & {"air_temperature", "precipitation"}:
            raise ValueError("Everglades NOAA connector requires climate variables")

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
            raise ValueError("NOAA Everglades station returned no observations")
        if not any("PRCP" in record for record in records):
            raise ValueError("NOAA Everglades station returned no precipitation observations")
        content = json.dumps(records, separators=(",", ":")).encode()
        file = await self.artifacts.put_raw(
            run_id, self.dataset_id, "ghcnd_usc00087760.json", content, "application/json"
        )
        return AcquisitionResult(
            dataset_id=self.dataset_id,
            provider="NOAA National Centers for Environmental Information",
            source_request={"url": str(response.request.url), "parameters": params},
            files=[file],
            metadata={
                "station_id": self.station_id,
                "station_name": "Royal Palm Ranger Station",
                "coordinates": {"latitude": 25.3867, "longitude": -80.5936},
                "units": "degrees Celsius and millimeters",
                "sampling_frequency": "daily",
                "row_count": len(records),
                "license": "U.S. Government work / NOAA data",
            },
        )

    async def metadata(self) -> dict:
        return {"dataset_id": self.dataset_id, "provider": "NOAA NCEI"}


class EvergladesNasaPowerConnector:
    dataset_id = "nasa-power-merra2-everglades"
    endpoint = "https://power.larc.nasa.gov/api/temporal/monthly/point"

    def __init__(self, artifacts: ArtifactStore, timeout: float = 60):
        self.artifacts = artifacts
        self.timeout = timeout

    def validate_request(self, request: DatasetRequest) -> None:
        if request.dataset_id != self.dataset_id:
            raise ValueError("Connector dataset mismatch")
        if not set(request.variables) & {"air_temperature", "precipitation"}:
            raise ValueError("NASA POWER wetland connector requires climate variables")

    async def fetch(self, run_id: str, request: DatasetRequest) -> AcquisitionResult:
        self.validate_request(request)
        params = {
            "latitude": 25.34,
            "longitude": -80.55,
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
            raise ValueError("NASA POWER returned an incomplete Everglades climate response")
        file = await self.artifacts.put_raw(
            run_id,
            self.dataset_id,
            "power_merra2_everglades.json",
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
                "spatial_resolution": "MERRA-2 point centered in Everglades National Park",
                "coordinates": {"latitude": 25.34, "longitude": -80.55},
                "row_count": len(parameters["T2M"]),
            },
        )

    async def metadata(self) -> dict:
        return {"dataset_id": self.dataset_id, "provider": "NASA POWER"}


class EvergladesUsgsWaterConnector:
    dataset_id = "usgs-nwis-everglades-1"
    endpoint = "https://waterservices.usgs.gov/nwis/dv/"
    site_id = "251946080254800"

    def __init__(self, artifacts: ArtifactStore, timeout: float = 60):
        self.artifacts = artifacts
        self.timeout = timeout

    def validate_request(self, request: DatasetRequest) -> None:
        if request.dataset_id != self.dataset_id:
            raise ValueError("Connector dataset mismatch")
        if "water_level" not in request.variables:
            raise ValueError("USGS Everglades connector requires water_level")

    async def fetch(self, run_id: str, request: DatasetRequest) -> AcquisitionResult:
        self.validate_request(request)
        params = {
            "format": "json",
            "sites": self.site_id,
            "startDT": request.start_date.isoformat(),
            "endDT": request.end_date.isoformat(),
            "parameterCd": "00065",
            "siteStatus": "all",
        }
        response = await get_with_retry(self.endpoint, params=params, timeout=self.timeout)
        payload = response.json()
        series = payload.get("value", {}).get("timeSeries", [])
        if not series or not series[0].get("values", [{}])[0].get("value"):
            raise ValueError("USGS Everglades gauge returned no daily water levels")
        values = series[0]["values"][0]["value"]
        file = await self.artifacts.put_raw(
            run_id,
            self.dataset_id,
            "usgs_everglades_1_gage_height.json",
            response.content,
            "application/json",
        )
        return AcquisitionResult(
            dataset_id=self.dataset_id,
            provider="U.S. Geological Survey Water Data for the Nation",
            source_request={"url": str(response.request.url), "parameters": params},
            files=[file],
            metadata={
                "site_id": self.site_id,
                "site_name": series[0]["sourceInfo"]["siteName"],
                "parameter": "00065 mean daily gage height",
                "units": "feet",
                "sampling_frequency": "daily",
                "row_count": len(values),
                "provisional_notice": "Recent USGS observations may be provisional and revised.",
            },
        )

    async def metadata(self) -> dict:
        return {"dataset_id": self.dataset_id, "provider": "USGS", "site": self.site_id}
