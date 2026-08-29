from datetime import date
from pathlib import Path

import pytest
import respx
from httpx import Response

from terraforge.connectors import area
from terraforge.connectors.area import AreaNoaaClimateConnector
from terraforge.connectors.ecology import FirmsWildfireConnector, GbifSpeciesConnector
from terraforge.connectors.everglades import (
    EvergladesNasaPowerConnector,
    EvergladesNoaaConnector,
    EvergladesUsgsWaterConnector,
)
from terraforge.connectors.http import get_with_retry
from terraforge.connectors.nasa_power import NasaPowerRegionalConnector
from terraforge.connectors.noaa_station import NoaaStationConnector
from terraforge.connectors.nsidc import NsidcSeaIceConnector
from terraforge.contracts.models import DatasetRequest, GeometrySpec
from terraforge.persistence.artifacts import ArtifactStore
from terraforge.settings import Settings


@pytest.fixture
def artifacts(tmp_path: Path):
    return ArtifactStore(Settings(terraforge_data_dir=tmp_path))


def request(dataset_id: str, variables: list[str]):
    return DatasetRequest(
        dataset_id=dataset_id,
        variables=variables,
        start_date=date(2005, 1, 1),
        end_date=date(2005, 1, 3),
        geometry=GeometrySpec(type="BBox", coordinates=[-160, 69, -150, 72]),
    )


def area_request(dataset_id: str, variables: list[str]):
    return DatasetRequest(
        dataset_id=dataset_id,
        variables=variables,
        start_date=date(2005, 1, 1),
        end_date=date(2025, 12, 31),
        geometry=GeometrySpec(
            type="Polygon",
            coordinates=[
                [
                    [-112.15, 34.95],
                    [-112.05, 34.95],
                    [-112.05, 35.05],
                    [-112.15, 35.05],
                    [-112.15, 34.95],
                ]
            ],
        ),
    )


async def test_optional_ecology_credentials_degrade_to_traceable_unavailable_artifacts(artifacts):
    settings = artifacts.settings
    fire = FirmsWildfireConnector(artifacts, settings)
    fire_result = await fire.fetch("ecology", area_request(fire.dataset_id, ["active_fire"]))

    assert fire_result.metadata["available"] is False
    assert fire_result.files[0].sha256


@respx.mock
async def test_gbif_normalizes_clockwise_area_before_requesting_occurrences(artifacts):
    clockwise_request = DatasetRequest(
        dataset_id=GbifSpeciesConnector.dataset_id,
        variables=["species_occurrences"],
        start_date=date(2005, 1, 1),
        end_date=date(2025, 12, 31),
        geometry=GeometrySpec(
            type="Polygon",
            coordinates=[
                [
                    [-112.15, 34.95],
                    [-112.15, 35.05],
                    [-112.05, 35.05],
                    [-112.05, 34.95],
                    [-112.15, 34.95],
                ]
            ],
        ),
    )
    route = respx.get(GbifSpeciesConnector.endpoint).mock(
        return_value=Response(
            200,
            json={
                "count": 1,
                "results": [
                    {
                        "key": 1,
                        "species": "Test species",
                        "decimalLongitude": -112.1,
                        "decimalLatitude": 35.0,
                        "year": 2020,
                    }
                ],
            },
        )
    )
    connector = GbifSpeciesConnector(artifacts, artifacts.settings)

    result = await connector.fetch("species", clockwise_request)

    geometry = route.calls[0].request.url.params["geometry"]
    assert geometry == (
        "POLYGON((-112.15 34.95,-112.05 34.95,-112.05 35.05,-112.15 35.05,-112.15 34.95))"
    )
    assert result.metadata["available"] is True
    assert result.metadata["row_count"] == 1


@respx.mock
async def test_area_noaa_resolves_required_stations_before_requesting_data(artifacts):
    area._STATION_CATALOG = None
    catalog = (
        "USC00029359  35.2414 -112.1928 2100.0 AZ WILLIAMS\n"
        "USC00024453  34.7539 -112.1114 1500.0 AZ JEROME\n"
    )
    respx.get(AreaNoaaClimateConnector.station_catalog_endpoint).mock(
        return_value=Response(200, text=catalog)
    )
    data_route = respx.get(AreaNoaaClimateConnector.endpoint).mock(
        return_value=Response(
            200,
            json=[
                {
                    "STATION": "USC00029359",
                    "DATE": "2005-01-01",
                    "TAVG": 4.2,
                    "PRCP": 1.3,
                }
            ],
        )
    )
    connector = AreaNoaaClimateConnector(artifacts)

    result = await connector.fetch(
        "area", area_request(connector.dataset_id, ["air_temperature", "precipitation"])
    )

    assert result.metadata["station_ids"] == ["USC00029359"]
    requested_stations = set(data_route.calls[0].request.url.params["stations"].split(","))
    assert requested_stations == {"USC00024453", "USC00029359"}
    area._STATION_CATALOG = None


@respx.mock
async def test_noaa_station_success_records_immutable_hash(artifacts):
    respx.get(NoaaStationConnector.endpoint).mock(
        return_value=Response(200, json=[{"DATE": "2005-01-01", "TAVG": "-20.2"}])
    )
    connector = NoaaStationConnector(artifacts)
    result = await connector.fetch("run", request(connector.dataset_id, ["air_temperature"]))
    assert result.files[0].sha256
    assert result.metadata["station_id"] == "USW00027502"


@respx.mock
async def test_noaa_station_empty_response_is_rejected(artifacts):
    respx.get(NoaaStationConnector.endpoint).mock(return_value=Response(200, json=[]))
    connector = NoaaStationConnector(artifacts)
    with pytest.raises(ValueError, match="no observations"):
        await connector.fetch("run", request(connector.dataset_id, ["air_temperature"]))


def test_noaa_station_invalid_variable_is_rejected(artifacts):
    connector = NoaaStationConnector(artifacts)
    with pytest.raises(ValueError, match="temperature"):
        connector.validate_request(request(connector.dataset_id, ["precipitation"]))


@respx.mock
async def test_nasa_power_success_requires_grid_features(artifacts):
    respx.get(NasaPowerRegionalConnector.endpoint).mock(
        return_value=Response(200, json={"features": [{"type": "Feature"}]})
    )
    connector = NasaPowerRegionalConnector(artifacts)
    result = await connector.fetch("run", request(connector.dataset_id, ["air_temperature"]))
    assert result.metadata["grid_cell_count"] == 1


@respx.mock
async def test_nasa_power_malformed_response_is_rejected(artifacts):
    respx.get(NasaPowerRegionalConnector.endpoint).mock(return_value=Response(200, json={}))
    connector = NasaPowerRegionalConnector(artifacts)
    with pytest.raises(ValueError, match="no regional grid"):
        await connector.fetch("run", request(connector.dataset_id, ["air_temperature"]))


@respx.mock
async def test_nsidc_success_checks_csv_schema(artifacts):
    respx.get(NsidcSeaIceConnector.endpoint).mock(
        return_value=Response(200, content=b"Year, Month, Day, Extent\n2005,1,1,12.0\n")
    )
    connector = NsidcSeaIceConnector(artifacts)
    result = await connector.fetch("run", request(connector.dataset_id, ["sea_ice_extent"]))
    assert result.metadata["product"].startswith("Sea Ice Index")


@respx.mock
async def test_rate_limit_is_bounded_and_reported(artifacts):
    route = respx.get(NsidcSeaIceConnector.endpoint).mock(return_value=Response(429))
    connector = NsidcSeaIceConnector(artifacts, timeout=1)
    with pytest.raises(RuntimeError, match="3 attempts"):
        await connector.fetch("run", request(connector.dataset_id, ["sea_ice_extent"]))
    assert route.call_count == 3


@respx.mock
async def test_malformed_compression_retries_with_identity_encoding():
    endpoint = "https://science.example.test/data"

    def response_for(request):
        if request.headers.get("accept-encoding") == "identity":
            return Response(200, content=b"usable scientific data")
        return Response(200, headers={"content-encoding": "gzip"}, content=b"not-gzip")

    route = respx.get(endpoint).mock(side_effect=response_for)
    response = await get_with_retry(endpoint, attempts=2, timeout=1)

    assert response.content == b"usable scientific data"
    assert route.call_count == 2


@respx.mock
async def test_everglades_authoritative_connectors_validate_expected_evidence(artifacts):
    respx.get(EvergladesNoaaConnector.endpoint).mock(
        return_value=Response(200, json=[{"DATE": "2005-01-01", "TAVG": "21", "PRCP": "3.2"}])
    )
    respx.get(EvergladesNasaPowerConnector.endpoint).mock(
        return_value=Response(
            200,
            json={
                "properties": {
                    "parameter": {
                        "T2M": {"200501": 21.1},
                        "PRECTOTCORR": {"200501": 85.2},
                    }
                }
            },
        )
    )
    respx.get(EvergladesUsgsWaterConnector.endpoint).mock(
        return_value=Response(
            200,
            json={
                "value": {
                    "timeSeries": [
                        {
                            "sourceInfo": {"siteName": "EVERGLADES 1"},
                            "values": [
                                {"value": [{"dateTime": "2005-01-01T00:00:00Z", "value": "4.2"}]}
                            ],
                        }
                    ]
                }
            },
        )
    )
    noaa = EvergladesNoaaConnector(artifacts)
    nasa = EvergladesNasaPowerConnector(artifacts)
    usgs = EvergladesUsgsWaterConnector(artifacts)

    noaa_result = await noaa.fetch(
        "wetland", request(noaa.dataset_id, ["air_temperature", "precipitation"])
    )
    nasa_result = await nasa.fetch(
        "wetland", request(nasa.dataset_id, ["air_temperature", "precipitation"])
    )
    usgs_result = await usgs.fetch("wetland", request(usgs.dataset_id, ["water_level"]))

    assert noaa_result.metadata["station_id"] == "USC00087760"
    assert nasa_result.metadata["parameters"] == ["T2M", "PRECTOTCORR"]
    assert usgs_result.metadata["site_id"] == "251946080254800"
