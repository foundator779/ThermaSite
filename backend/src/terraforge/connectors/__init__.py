from terraforge.connectors.area import AreaNasaPowerConnector, AreaNoaaClimateConnector
from terraforge.connectors.ecology import (
    FirmsWildfireConnector,
    GbifSpeciesConnector,
    NwiWetlandsConnector,
)
from terraforge.connectors.everglades import (
    EvergladesNasaPowerConnector,
    EvergladesNoaaConnector,
    EvergladesUsgsWaterConnector,
)
from terraforge.connectors.nasa_power import NasaPowerRegionalConnector
from terraforge.connectors.noaa_station import NoaaStationConnector
from terraforge.connectors.nsidc import NsidcSeaIceConnector
from terraforge.connectors.sentinel import Sentinel2VegetationConnector


def build_connectors(artifacts, settings):
    connectors = [
        AreaNoaaClimateConnector(artifacts, settings.request_timeout_seconds),
        AreaNasaPowerConnector(artifacts, settings.request_timeout_seconds),
        NoaaStationConnector(artifacts, settings.request_timeout_seconds),
        NasaPowerRegionalConnector(artifacts, settings.request_timeout_seconds),
        NsidcSeaIceConnector(artifacts, settings.request_timeout_seconds),
        EvergladesNoaaConnector(artifacts, settings.request_timeout_seconds),
        EvergladesNasaPowerConnector(artifacts, settings.request_timeout_seconds),
        EvergladesUsgsWaterConnector(artifacts, settings.request_timeout_seconds),
        GbifSpeciesConnector(artifacts, settings),
        FirmsWildfireConnector(artifacts, settings),
        NwiWetlandsConnector(artifacts, settings),
        Sentinel2VegetationConnector(artifacts, settings),
    ]
    return {connector.dataset_id: connector for connector in connectors}


__all__ = [
    "AreaNasaPowerConnector",
    "AreaNoaaClimateConnector",
    "EvergladesNasaPowerConnector",
    "EvergladesNoaaConnector",
    "EvergladesUsgsWaterConnector",
    "FirmsWildfireConnector",
    "GbifSpeciesConnector",
    "NasaPowerRegionalConnector",
    "NoaaStationConnector",
    "NsidcSeaIceConnector",
    "NwiWetlandsConnector",
    "Sentinel2VegetationConnector",
    "build_connectors",
]
