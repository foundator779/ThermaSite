from __future__ import annotations

import re
from datetime import UTC, date, datetime

from terraforge.contracts.models import GeometrySpec, ResearchSpecification


def interpret_research_question(query: str) -> ResearchSpecification:
    """Typed local interpreter used for deterministic intake and as the ADK tool boundary."""
    years = [int(value) for value in re.findall(r"\b(19\d{2}|20\d{2})\b", query)]
    start_year, end_year = (min(years), max(years)) if years else (2005, datetime.now(UTC).year)
    sea_ice = "ice" in query.lower()
    seasonal = "season" in query.lower()
    significance = "signific" in query.lower()
    roles = ["local_station_temperature", "regional_gridded_temperature"]
    variables = ["air_temperature"]
    metrics = ["annual_mean_temperature", "annual_temperature_trend"]
    if seasonal:
        metrics.append("seasonal_temperature_trends")
    if significance:
        metrics.append("temperature_trend_significance")
    if sea_ice:
        variables.append("sea_ice_extent")
        roles.append("nearby_sea_ice")
        metrics += ["sea_ice_trend", "temperature_sea_ice_association"]
    return ResearchSpecification(
        question=query,
        variables=variables,
        derived_metrics=metrics,
        anchor_place="Utqiaġvik, Alaska",
        region="Alaska North Slope and adjacent Arctic waters",
        start_date=date(start_year, 1, 1),
        end_date=date(end_year, 12, 31),
        analysis_intent="multi_dataset_climate_change_analysis",
        required_data_roles=roles,
        causal_claim_allowed=False,
        research_geometry=GeometrySpec(
            type="BBox", coordinates=[-160.0, 69.0, -150.0, 72.0], label="North Slope study region"
        ),
    )
