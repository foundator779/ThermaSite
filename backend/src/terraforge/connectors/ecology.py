from __future__ import annotations

import csv
import io
import json
from collections import Counter
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

from terraforge.connectors.http import get_with_retry
from terraforge.contracts.models import AcquisitionResult, DatasetRequest
from terraforge.persistence.artifacts import ArtifactStore
from terraforge.settings import Settings


def _ring(request: DatasetRequest) -> list[list[float]]:
    return [[float(point[0]), float(point[1])] for point in request.geometry.coordinates[0]]


def _bounds(request: DatasetRequest) -> tuple[float, float, float, float]:
    ring = _ring(request)
    return (
        min(point[0] for point in ring),
        min(point[1] for point in ring),
        max(point[0] for point in ring),
        max(point[1] for point in ring),
    )


def _counter_clockwise_ring(request: DatasetRequest) -> list[list[float]]:
    """Return a closed exterior ring in the orientation required by GBIF."""
    ring = _ring(request)
    if ring[0] != ring[-1]:
        ring.append(ring[0].copy())

    signed_area_twice = sum(
        current[0] * following[1] - following[0] * current[1]
        for current, following in pairwise(ring)
    )
    if signed_area_twice < 0:
        ring.reverse()
    return ring


def _wkt(request: DatasetRequest) -> str:
    coordinates = ",".join(
        f"{longitude} {latitude}" for longitude, latitude in _counter_clockwise_ring(request)
    )
    return f"POLYGON(({coordinates}))"


class _EcologyConnector:
    provider = ""
    filename = "evidence.json"
    content_type = "application/json"

    def __init__(self, artifacts: ArtifactStore, settings: Settings):
        self.artifacts = artifacts
        self.settings = settings
        self.timeout = settings.request_timeout_seconds

    def validate_request(self, request: DatasetRequest) -> None:
        if request.dataset_id != self.dataset_id:
            raise ValueError("Connector dataset mismatch")
        if request.geometry.type != "Polygon":
            raise ValueError("Ecological acquisition requires polygon geometry")

    async def _result(
        self,
        run_id: str,
        payload: dict[str, Any],
        source_request: dict[str, Any],
        *,
        warnings: list[str] | None = None,
        row_count: int | None = None,
    ) -> AcquisitionResult:
        content = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        file = await self.artifacts.put_raw(
            run_id, self.dataset_id, self.filename, content, self.content_type
        )
        return AcquisitionResult(
            dataset_id=self.dataset_id,
            provider=self.provider,
            source_request=source_request,
            files=[file],
            metadata={
                "row_count": row_count if row_count is not None else 1,
                "units": "geospatial ecological observations",
                "available": bool(payload.get("available", True)),
            },
            warnings=warnings or [],
        )


class GbifSpeciesConnector(_EcologyConnector):
    dataset_id = "gbif-occurrences-user-area"
    provider = "Global Biodiversity Information Facility"
    filename = "gbif_occurrences.json"
    endpoint = "https://api.gbif.org/v1/occurrence/search"

    async def fetch(self, run_id: str, request: DatasetRequest) -> AcquisitionResult:
        self.validate_request(request)
        params = {
            "geometry": _wkt(request),
            "hasCoordinate": "true",
            "occurrenceStatus": "PRESENT",
            "year": f"{request.start_date.year},{request.end_date.year}",
            "limit": 300,
        }
        try:
            response = await get_with_retry(self.endpoint, params=params, timeout=self.timeout)
            raw = response.json()
        except Exception as exc:  # noqa: BLE001 - optional source cannot abort the full workflow
            return await self._result(
                run_id,
                {"available": False, "occurrences": [], "reason": type(exc).__name__},
                {"url": self.endpoint, "parameters": {**params, "geometry": "submitted polygon"}},
                warnings=["GBIF occurrence evidence was temporarily unavailable."],
                row_count=0,
            )
        occurrences = []
        for item in raw.get("results", []):
            longitude, latitude = item.get("decimalLongitude"), item.get("decimalLatitude")
            if longitude is None or latitude is None:
                continue
            occurrences.append(
                {
                    "gbif_id": item.get("key"),
                    "species": item.get("species")
                    or item.get("scientificName")
                    or "Unresolved taxon",
                    "species_key": item.get("speciesKey") or item.get("taxonKey"),
                    "kingdom": item.get("kingdom"),
                    "basis_of_record": item.get("basisOfRecord"),
                    "event_date": item.get("eventDate"),
                    "year": item.get("year"),
                    "dataset": item.get("datasetTitle"),
                    "coordinates": [float(longitude), float(latitude)],
                    "coordinate_uncertainty_m": item.get("coordinateUncertaintyInMeters"),
                }
            )
        payload = {
            "available": True,
            "matched_record_count": int(raw.get("count", len(occurrences))),
            "sampled_record_count": len(occurrences),
            "occurrences": occurrences,
            "sampling_note": (
                "Occurrence records measure documented sampling, not a complete species census."
            ),
        }
        return await self._result(
            run_id,
            payload,
            {"url": self.endpoint, "parameters": {**params, "geometry": "submitted polygon"}},
            row_count=len(occurrences),
        )


class NwiWetlandsConnector(_EcologyConnector):
    dataset_id = "usfws-nwi-user-area"
    provider = "U.S. Fish and Wildlife Service National Wetlands Inventory"
    filename = "nwi_wetlands.geojson"
    endpoint = (
        "https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/"
        "Wetlands/MapServer/0/query"
    )

    async def fetch(self, run_id: str, request: DatasetRequest) -> AcquisitionResult:
        self.validate_request(request)
        geometry = {"rings": [_ring(request)], "spatialReference": {"wkid": 4326}}
        params = {
            "where": "1=1",
            "geometry": json.dumps(geometry, separators=(",", ":")),
            "geometryType": "esriGeometryPolygon",
            "spatialRel": "esriSpatialRelIntersects",
            "inSR": 4326,
            "outSR": 4326,
            "outFields": "ATTRIBUTE,WETLAND_TYPE,ACRES,SYSTEM_NAME,CLASS_NAME",
            "returnGeometry": "true",
            "resultRecordCount": 500,
            "maxAllowableOffset": 0.00005,
            "f": "geojson",
        }
        try:
            response = await get_with_retry(self.endpoint, params=params, timeout=self.timeout)
            payload = response.json()
        except Exception as exc:  # noqa: BLE001 - optional source cannot abort the full workflow
            return await self._result(
                run_id,
                {"available": False, "features": [], "reason": type(exc).__name__},
                {"url": self.endpoint, "parameters": {**params, "geometry": "submitted polygon"}},
                warnings=["USFWS NWI wetland evidence was temporarily unavailable."],
                row_count=0,
            )
        features = payload.get("features", [])[:500]
        wetland_types = Counter(
            str(feature.get("properties", {}).get("WETLAND_TYPE") or "Unclassified")
            for feature in features
        )
        acres = sum(float(feature.get("properties", {}).get("ACRES") or 0) for feature in features)
        result = {
            "available": True,
            "type": "FeatureCollection",
            "features": features,
            "feature_count": len(features),
            "mapped_acres_intersecting": acres,
            "wetland_types": dict(wetland_types),
            "coverage_note": "Mapped NWI features intersecting the submitted polygon; acreage is not clipped at its boundary.",
        }
        return await self._result(
            run_id,
            result,
            {"url": self.endpoint, "parameters": {**params, "geometry": "submitted polygon"}},
            row_count=len(features),
        )


class FirmsWildfireConnector(_EcologyConnector):
    dataset_id = "nasa-firms-user-area"
    provider = "NASA LANCE Fire Information for Resource Management System"
    filename = "firms_active_fire.json"
    endpoint = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

    async def fetch(self, run_id: str, request: DatasetRequest) -> AcquisitionResult:
        self.validate_request(request)
        secret = self.settings.firms_map_key
        map_key = secret.get_secret_value() if secret else ""
        if not map_key:
            return await self._result(
                run_id,
                {
                    "available": False,
                    "detections": [],
                    "reason": "FIRMS_MAP_KEY is not configured",
                },
                {"url": self.endpoint, "parameters": {"map_key": "not configured"}},
                warnings=[
                    "NASA FIRMS evidence was skipped because FIRMS_MAP_KEY is not configured."
                ],
                row_count=0,
            )
        west, south, east, north = _bounds(request)
        area = f"{west:.6f},{south:.6f},{east:.6f},{north:.6f}"
        today = datetime.now(UTC).date()
        end_date = min(request.end_date, today)
        source = "VIIRS_SNPP_NRT" if (today - end_date).days <= 60 else "VIIRS_SNPP_SP"
        url = f"{self.endpoint}/{map_key}/{source}/{area}/10/{end_date.isoformat()}"
        try:
            response = await get_with_retry(url, timeout=self.timeout)
            rows = list(csv.DictReader(io.StringIO(response.text)))
        except Exception as exc:  # noqa: BLE001 - optional evidence must degrade without failing a run
            return await self._result(
                run_id,
                {"available": False, "detections": [], "reason": type(exc).__name__},
                {
                    "url": self.endpoint,
                    "parameters": {"area": area, "days": 10, "source": source},
                },
                warnings=["NASA FIRMS did not return recent active-fire evidence for this run."],
                row_count=0,
            )
        detections = []
        for row in rows:
            try:
                detections.append(
                    {
                        "coordinates": [float(row["longitude"]), float(row["latitude"])],
                        "acquisition_date": row.get("acq_date"),
                        "acquisition_time": row.get("acq_time"),
                        "confidence": row.get("confidence"),
                        "frp": float(row.get("frp") or 0),
                        "satellite": row.get("satellite"),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
        return await self._result(
            run_id,
            {
                "available": True,
                "window_days": 10,
                "window_end": end_date.isoformat(),
                "source": source,
                "detections": detections,
            },
            {
                "url": self.endpoint,
                "parameters": {"area": area, "days": 10, "source": source},
            },
            row_count=len(detections),
        )
