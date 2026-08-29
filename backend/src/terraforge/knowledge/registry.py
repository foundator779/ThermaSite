from __future__ import annotations

from terraforge.contracts.models import DatasetCandidate, ResearchSpecification

REGISTRY_VERSION = "2026.08.5"

DATASETS = [
    {
        "dataset_id": "sentinel-2-l2a-vegetation-user-area",
        "name": "Sentinel-2 Seasonal Vegetation Condition",
        "provider": "Copernicus Sentinel-2 via Earth Search",
        "data_role": "sentinel_2_l2a",
        "authority_score": 0.98,
        "temporal_resolution": "up to five-day revisit",
        "spatial_resolution": "20 m harmonized analysis grid",
        "documentation_url": "https://registry.opendata.aws/sentinel-2-l2a-cogs/",
        "rationale": "Calculates cloud-masked NDVI, NDMI, and same-season vegetation stress from public multispectral surface reflectance.",
        "footprint": None,
    },
    {
        "dataset_id": "gbif-occurrences-user-area",
        "name": "GBIF Species Occurrences in User-Drawn Area",
        "provider": "Global Biodiversity Information Facility",
        "data_role": "species_biodiversity",
        "authority_score": 0.92,
        "temporal_resolution": "event observations",
        "spatial_resolution": "georeferenced occurrence points",
        "documentation_url": "https://techdocs.gbif.org/en/openapi/v1/occurrence",
        "rationale": "Measures documented species occurrences, taxonomic richness, and sampling coverage inside the submitted geometry.",
        "footprint": None,
    },
    {
        "dataset_id": "nasa-firms-user-area",
        "name": "NASA FIRMS Active-Fire Detections",
        "provider": "NASA LANCE FIRMS",
        "data_role": "wildfire_activity",
        "authority_score": 0.98,
        "temporal_resolution": "near real time",
        "spatial_resolution": "VIIRS active-fire detections",
        "documentation_url": "https://firms2.modaps.eosdis.nasa.gov/api/",
        "rationale": "Screens the selected habitat for recent satellite-detected fire activity and fire radiative power.",
        "footprint": None,
    },
    {
        "dataset_id": "usfws-nwi-user-area",
        "name": "USFWS National Wetlands Inventory Features",
        "provider": "U.S. Fish and Wildlife Service",
        "data_role": "wetland_inventory",
        "authority_score": 1.0,
        "temporal_resolution": "inventory updated biannually",
        "spatial_resolution": "mapped wetland polygons",
        "documentation_url": "https://www.fws.gov/program/national-wetlands-inventory/data-download",
        "rationale": "Identifies mapped wetland extent, type, and Cowardin classifications intersecting the study area.",
        "footprint": None,
    },
    {
        "dataset_id": "noaa-ncei-ghcnd-user-area",
        "name": "NOAA GHCN-Daily Stations Near User-Drawn Area",
        "provider": "NOAA National Centers for Environmental Information",
        "data_role": "area_station_climate",
        "authority_score": 1.0,
        "temporal_resolution": "daily",
        "spatial_resolution": "stations inside or nearest to selected area",
        "documentation_url": "https://www.ncei.noaa.gov/access/search/data-search/daily-summaries",
        "rationale": "Selects in-situ temperature and precipitation observations from the submitted geometry.",
        "footprint": None,
    },
    {
        "dataset_id": "nasa-power-merra2-user-area",
        "name": "NASA POWER MERRA-2 Selected-Area Climate",
        "provider": "NASA Langley Research Center",
        "data_role": "area_regional_climate",
        "authority_score": 0.96,
        "temporal_resolution": "monthly",
        "spatial_resolution": "MERRA-2 point at selected-area centroid",
        "documentation_url": "https://power.larc.nasa.gov/docs/services/api/temporal/monthly/",
        "rationale": "Provides independent modeled temperature and precipitation context for any submitted area.",
        "footprint": None,
    },
    {
        "dataset_id": "noaa-ncei-ghcnd-usw00027502",
        "name": "GHCN-Daily — Utqiaġvik Wiley Post–Will Rogers Airport",
        "provider": "NOAA National Centers for Environmental Information",
        "data_role": "local_station_temperature",
        "authority_score": 1.0,
        "temporal_resolution": "daily",
        "spatial_resolution": "station (71.283°N, 156.782°W)",
        "documentation_url": "https://www.ncei.noaa.gov/access/search/data-search/daily-summaries",
        "rationale": "Quality-controlled in-situ observations at Utqiaġvik's primary long-term station.",
        "footprint": {"type": "Point", "coordinates": [-156.782, 71.283]},
    },
    {
        "dataset_id": "nasa-power-merra2-north-slope",
        "name": "NASA POWER MERRA-2 Regional Temperature",
        "provider": "NASA Langley Research Center",
        "data_role": "regional_gridded_temperature",
        "authority_score": 0.96,
        "temporal_resolution": "monthly",
        "spatial_resolution": "0.5° × 0.625° grid",
        "documentation_url": "https://power.larc.nasa.gov/docs/services/api/temporal/monthly/",
        "rationale": "Analysis-ready MERRA-2 temperature grid supplies regional North Slope context.",
        "footprint": {
            "type": "Polygon",
            "coordinates": [[[-160, 69], [-150, 69], [-150, 71], [-160, 71], [-160, 69]]],
        },
    },
    {
        "dataset_id": "noaa-nsidc-g02135-v4",
        "name": "NOAA/NSIDC Sea Ice Index, Version 4",
        "provider": "NOAA at the National Snow and Ice Data Center",
        "data_role": "nearby_sea_ice",
        "authority_score": 1.0,
        "temporal_resolution": "daily",
        "spatial_resolution": "Northern Hemisphere extent; 25 km source grid",
        "documentation_url": "https://nsidc.org/data/g02135/versions/4",
        "rationale": "Consistently processed authoritative Arctic sea-ice extent record since 1978.",
        "footprint": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-180, 66],
                    [-90, 66],
                    [0, 66],
                    [90, 66],
                    [180, 66],
                    [180, 90],
                    [-180, 90],
                    [-180, 66],
                ]
            ],
        },
    },
    {
        "dataset_id": "noaa-ncei-ghcnd-usc00087760",
        "name": "GHCN-Daily — Royal Palm Ranger Station",
        "provider": "NOAA National Centers for Environmental Information",
        "data_role": "wetland_station_climate",
        "authority_score": 1.0,
        "temporal_resolution": "daily",
        "spatial_resolution": "station (25.387°N, 80.594°W)",
        "documentation_url": "https://www.ncei.noaa.gov/pub/data/cdo/documentation/GHCND_documentation.pdf",
        "rationale": "Long-running in-situ temperature and precipitation observations inside the Everglades landscape.",
        "footprint": {"type": "Point", "coordinates": [-80.5936, 25.3867]},
    },
    {
        "dataset_id": "nasa-power-merra2-everglades",
        "name": "NASA POWER MERRA-2 Everglades Climate",
        "provider": "NASA Langley Research Center",
        "data_role": "wetland_regional_climate",
        "authority_score": 0.96,
        "temporal_resolution": "monthly",
        "spatial_resolution": "MERRA-2 point product",
        "documentation_url": "https://power.larc.nasa.gov/docs/services/api/temporal/monthly/",
        "rationale": "Independent temperature and corrected-precipitation context for corroborating station observations.",
        "footprint": {"type": "Point", "coordinates": [-80.55, 25.34]},
    },
    {
        "dataset_id": "usgs-nwis-everglades-1",
        "name": "USGS Everglades 1 Daily Water Level",
        "provider": "U.S. Geological Survey Water Data for the Nation",
        "data_role": "wetland_water_level",
        "authority_score": 1.0,
        "temporal_resolution": "daily",
        "spatial_resolution": "gage in C-111 basin near Homestead",
        "documentation_url": "https://waterdata.usgs.gov/nwis/dv?site_no=251946080254800",
        "rationale": "Continuous wetland hydrology evidence with coverage from 1985 to present.",
        "footprint": {"type": "Point", "coordinates": [-80.4305, 25.3294]},
    },
]


def discover(spec: ResearchSpecification) -> list[DatasetCandidate]:
    candidates: list[DatasetCandidate] = []
    for entry in DATASETS:
        required = entry["data_role"] in spec.required_data_roles
        # 0.30 variable + 0.20 temporal + 0.20 spatial + 0.10 resolution +
        # 0.10 authority + 0.05 access reliability + 0.05 preprocessing compatibility.
        score = 0.30 + 0.20 + 0.20 + 0.10 + 0.10 * entry["authority_score"] + 0.05 + 0.05
        candidates.append(
            DatasetCandidate(
                dataset_id=entry["dataset_id"],
                name=entry["name"],
                provider=entry["provider"],
                match_score=round(score if required else score - 0.3, 3),
                variable_match=required,
                temporal_fit=True,
                spatial_fit=True,
                access_type="https",
                temporal_resolution=entry["temporal_resolution"],
                spatial_resolution=entry["spatial_resolution"],
                rationale=entry["rationale"],
                data_role=entry["data_role"],
                documentation_url=entry["documentation_url"],
                footprint=entry["footprint"],
            )
        )
    return sorted(candidates, key=lambda candidate: candidate.match_score, reverse=True)
