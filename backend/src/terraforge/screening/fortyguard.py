from __future__ import annotations

import asyncio
import hashlib
import json
import math
from typing import Any

import httpx

from terraforge.persistence.local import atomic_write_text
from terraforge.settings import Settings

from .models import CandidateSite, ThermalMetrics, ThermalWindow


class FortyGuardError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


def candidate_polygon(site: CandidateSite) -> dict[str, Any]:
    if site.area_sq_mi > 10:
        raise ValueError("FortyGuard Basic-compatible AOIs may not exceed 10 square miles")
    half_side_miles = math.sqrt(site.area_sq_mi) / 2
    lat_delta = half_side_miles / 69.0
    lon_delta = half_side_miles / max(1, 69.172 * math.cos(math.radians(site.latitude)))
    west, east = site.longitude - lon_delta, site.longitude + lon_delta
    south, north = site.latitude - lat_delta, site.latitude + lat_delta
    ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"site_id": site.id},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        ],
    }


class FortyGuardClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client
        self._cache_dir = (settings.terraforge_data_dir / "cache" / "fortyguard").resolve()
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def ready(self) -> bool:
        return bool(
            self.settings.fortyguard_api_key and self.settings.fortyguard_api_key.get_secret_value()
        )

    def _headers(self) -> dict[str, str]:
        if not self.ready:
            raise FortyGuardError("FORTYGUARD_API_KEY is not configured", status_code=503)
        return {
            "api-key": self.settings.fortyguard_api_key.get_secret_value(),
            "Content-Type": "application/json",
        }

    async def analyze(self, site: CandidateSite, window: ThermalWindow) -> ThermalMetrics:
        return await self.analyze_polygon(candidate_polygon(site), site.id, window)

    async def analyze_polygon(
        self, polygon_aoi: dict[str, Any], site_id: str, window: ThermalWindow
    ) -> ThermalMetrics:
        payload_base = {
            "polygon_aoi": polygon_aoi,
            "date_time": {
                "start_date": window.start_date.isoformat(),
                "end_date": window.end_date.isoformat(),
                "filter_type": 4,
            },
            "granularity": window.granularity_m,
        }
        cache_key = hashlib.sha256(
            json.dumps(
                {
                    "aoi": payload_base["polygon_aoi"]["features"][0]["geometry"],
                    "site_id": site_id,
                    "date_time": payload_base["date_time"],
                    "granularity": window.granularity_m,
                    "analyses": ["tcm", "exceedance"],
                    "threshold": window.threshold_c,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        cache_path = self._cache_dir / f"{cache_key}.json"
        if cache_path.exists():
            return ThermalMetrics.model_validate_json(cache_path.read_text(encoding="utf-8"))

        own_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=self.settings.fortyguard_request_timeout_seconds
        )
        try:
            tcm_payload = {**payload_base, "analytic_type": "tcm"}
            exceedance_payload = {
                **payload_base,
                "analytic_type": "exceedance",
                "threshold": window.threshold_c,
                "direction": "above",
            }
            tcm, exceedance = await asyncio.gather(
                self._submit_and_poll(client, tcm_payload),
                self._submit_and_poll(client, exceedance_payload),
            )
        finally:
            if own_client:
                await client.aclose()

        tcm_result = self._result(tcm)
        exceedance_result = self._result(exceedance)
        stats = tcm_result.get("stats_data") or {}
        temperatures = stats.get("Temperature_stats") or stats.get("temperature_stats") or stats
        mean = self._find_number(temperatures, "mean")
        maximum = self._find_number(temperatures, "maximum", "max")
        minimum = self._find_number(temperatures, "minimum", "min")
        if mean is None or maximum is None:
            raise FortyGuardError("FortyGuard completed without required temperature statistics")
        map_data = tcm_result.get("map_data") or {}
        self._validate_geojson(map_data)
        exceedance_map = exceedance_result.get("map_data") or {}
        self._validate_geojson(exceedance_map)
        exceedance_values = self._numeric_values(exceedance_map)
        ratio = (
            sum(1 for value in exceedance_values if value > 0) / len(exceedance_values)
            if exceedance_values
            else 0
        )
        activity_ids = [
            str((tcm.get("data") or {}).get("activity_id", "")),
            str((exceedance.get("data") or {}).get("activity_id", "")),
        ]
        metrics = ThermalMetrics(
            activity_ids=[item for item in activity_ids if item],
            mean_temperature_c=mean,
            maximum_temperature_c=maximum,
            minimum_temperature_c=minimum,
            exceedance_ratio=round(ratio, 4),
            threshold_c=window.threshold_c,
            map_data=map_data,
        )
        await atomic_write_text(cache_path, metrics.model_dump_json(indent=2))
        return metrics

    async def _submit_and_poll(
        self, client: httpx.AsyncClient, payload: dict[str, Any]
    ) -> dict[str, Any]:
        response = await client.post(
            f"{self.settings.fortyguard_base_url.rstrip('/')}/v1/heatmap",
            headers=self._headers(),
            json=payload,
        )
        self._raise(response)
        body = response.json()
        activity_id = str((body.get("data") or {}).get("activity_id") or "")
        if not activity_id:
            raise FortyGuardError("FortyGuard did not return an activity_id")
        deadline = asyncio.get_running_loop().time() + self.settings.fortyguard_poll_timeout_seconds
        not_found_until = asyncio.get_running_loop().time() + 30
        while asyncio.get_running_loop().time() < deadline:
            status_response = await client.get(
                f"{self.settings.fortyguard_base_url.rstrip('/')}/v1/status/{activity_id}",
                headers=self._headers(),
            )
            if (
                status_response.status_code == 404
                and asyncio.get_running_loop().time() < not_found_until
            ):
                await asyncio.sleep(self.settings.fortyguard_poll_interval_seconds)
                continue
            self._raise(status_response)
            status_body = status_response.json()
            status = str((status_body.get("data") or {}).get("status") or "").lower()
            if status in {"completed", "succeeded"}:
                status_body.setdefault("data", {})["activity_id"] = activity_id
                return status_body
            if status in {"failed", "error"}:
                raise FortyGuardError(f"FortyGuard activity {activity_id} failed")
            await asyncio.sleep(self.settings.fortyguard_poll_interval_seconds)
        raise FortyGuardError(
            f"FortyGuard activity {activity_id} exceeded the bounded polling timeout",
            retryable=True,
        )

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        if response.is_success:
            return
        messages = {
            400: "FortyGuard rejected the screening input",
            401: "FortyGuard API key is missing or invalid",
            403: "The FortyGuard plan does not authorize this request",
            404: "FortyGuard activity was not found",
            422: "FortyGuard could not validate the screening input",
            429: "FortyGuard rate limit was reached",
        }
        raise FortyGuardError(
            messages.get(response.status_code, "FortyGuard service request failed"),
            status_code=response.status_code,
            retryable=response.status_code in {404, 429, 500, 502, 503, 504},
        )

    @staticmethod
    def _result(body: dict[str, Any]) -> dict[str, Any]:
        return (body.get("data") or {}).get("result") or {}

    @classmethod
    def _find_number(cls, data: Any, *keys: str) -> float | None:
        wanted = {key.lower() for key in keys}
        if isinstance(data, dict):
            for key, value in data.items():
                if key.lower() in wanted and isinstance(value, (int, float)):
                    return float(value)
            for value in data.values():
                found = cls._find_number(value, *keys)
                if found is not None:
                    return found
        elif isinstance(data, list):
            for value in data:
                found = cls._find_number(value, *keys)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _validate_geojson(data: dict[str, Any]) -> None:
        if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
            raise FortyGuardError("FortyGuard returned malformed GeoJSON map data")

    @classmethod
    def _numeric_values(cls, data: Any) -> list[float]:
        values: list[float] = []
        if isinstance(data, dict):
            for key, value in data.items():
                if key.lower() in {"value", "temperature", "hours", "count"} and isinstance(
                    value, (int, float)
                ):
                    values.append(float(value))
                else:
                    values.extend(cls._numeric_values(value))
        elif isinstance(data, list):
            for item in data:
                values.extend(cls._numeric_values(item))
        return values
