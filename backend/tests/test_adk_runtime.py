import pytest
from pydantic import ValidationError

from terraforge.adk.runtime import AdkResearchDecision


def valid_decision(**overrides):
    payload = {
        "anchor_place": "Utqiaġvik, Alaska",
        "region": "Alaska North Slope and adjacent Arctic waters",
        "start_year": 2005,
        "end_year": 2025,
        "variables": ["air_temperature", "sea_ice_extent"],
        "derived_metrics": ["annual_temperature_trend", "seasonal_temperature_trends"],
        "analysis_intent": "multi_dataset_climate_change_analysis",
        "required_data_roles": [
            "local_station_temperature",
            "regional_gridded_temperature",
            "nearby_sea_ice",
        ],
        "selected_dataset_ids": [
            "noaa-ncei-ghcnd-usw00027502",
            "nasa-power-merra2-north-slope",
            "noaa-nsidc-g02135-v4",
        ],
        "analysis_operations": [
            "annual_mean",
            "ols_trend_and_significance",
            "seasonal_aggregate",
            "sea_ice_trend",
            "pearson_association",
            "render_figures",
        ],
        "research_bbox": [-160.0, 69.0, -150.0, 72.0],
        "selection_rationale": "Three complementary authoritative sources are required.",
        "causal_claim_allowed": False,
    }
    payload.update(overrides)
    return payload


def test_adk_decision_becomes_typed_research_specification():
    decision = AdkResearchDecision.model_validate(valid_decision())
    spec = decision.to_research_specification("How did the regional climate change?")
    assert spec.start_date.year == 2005
    assert spec.end_date.year == 2025
    assert spec.required_data_roles == decision.required_data_roles
    assert spec.causal_claim_allowed is False


def test_adk_decision_rejects_unknown_dataset():
    with pytest.raises(ValidationError, match="unknown dataset IDs"):
        AdkResearchDecision.model_validate(
            valid_decision(selected_dataset_ids=["invented-dataset"])
        )


def test_adk_decision_supports_everglades_wetland_evidence_roles():
    decision = AdkResearchDecision.model_validate(
        valid_decision(
            anchor_place="Everglades National Park, Florida",
            region="Everglades National Park and C-111 basin",
            habitat_type="everglades_wetland",
            variables=["air_temperature", "precipitation", "water_level"],
            required_data_roles=[
                "wetland_station_climate",
                "wetland_regional_climate",
                "wetland_water_level",
            ],
            selected_dataset_ids=[
                "noaa-ncei-ghcnd-usc00087760",
                "nasa-power-merra2-everglades",
                "usgs-nwis-everglades-1",
            ],
            analysis_operations=[
                "annual_water_level",
                "wetland_hydroperiod_anomaly",
                "precipitation_water_level_association",
                "cross_source_climate_agreement",
                "render_figures",
            ],
            research_bbox=[-81.15, 24.75, -80.15, 26.15],
        )
    )
    spec = decision.to_research_specification("Assess wetland habitat pressure.")
    assert spec.habitat_type == "everglades_wetland"
    assert "wetland_water_level" in spec.required_data_roles
