from terraforge.contracts.models import (
    AnalysisPlan,
    AnalysisStep,
    HarmonizationReport,
    ResearchSpecification,
)


def create_analysis_plan(spec: ResearchSpecification, report: HarmonizationReport) -> AnalysisPlan:
    return create_adk_analysis_plan(spec, report, None)


def create_adk_analysis_plan(
    spec: ResearchSpecification,
    report: HarmonizationReport,
    requested_operations: list[str] | None,
) -> AnalysisPlan:
    if spec.habitat_type == "everglades_wetland":
        return _create_wetland_plan(report, requested_operations)
    if spec.habitat_type == "custom_habitat":
        return _create_custom_habitat_plan(report, requested_operations)
    required_operations = {
        "annual_mean",
        "ols_trend_and_significance",
        "seasonal_aggregate",
        "render_figures",
    }
    if "nearby_sea_ice" in spec.required_data_roles:
        required_operations.update({"sea_ice_trend", "pearson_association"})
    if requested_operations is not None:
        missing = required_operations - set(requested_operations)
        if missing:
            raise ValueError(f"Gemini analysis plan omitted required operations: {sorted(missing)}")
    return AnalysisPlan(
        steps=[
            AnalysisStep(
                id="01",
                operation="load_declared_inputs",
                inputs=["harmonized_monthly.csv"],
                output="dataframe",
            ),
            AnalysisStep(
                id="02",
                operation="annual_mean",
                inputs=["dataframe"],
                output="annual_temperature.csv",
            ),
            AnalysisStep(
                id="03",
                operation="ols_trend_and_significance",
                inputs=["annual_temperature.csv"],
                output="trend_metrics",
            ),
            AnalysisStep(
                id="04",
                operation="seasonal_aggregate",
                inputs=["dataframe"],
                output="seasonal_trends",
            ),
            AnalysisStep(
                id="05", operation="sea_ice_trend", inputs=["dataframe"], output="sea_ice_metrics"
            ),
            AnalysisStep(
                id="06",
                operation="pearson_association",
                inputs=["dataframe"],
                output="association_metrics",
            ),
            AnalysisStep(
                id="07",
                operation="render_figures",
                inputs=["trend_metrics", "seasonal_trends", "association_metrics"],
                output="plots",
            ),
        ],
        expected_artifacts=[
            "annual_temperature_trend.png",
            "seasonal_change.png",
            "sea_ice_trend.png",
            "temperature_sea_ice_association.png",
            "result.json",
        ],
    )


def _create_wetland_plan(
    report: HarmonizationReport, requested_operations: list[str] | None
) -> AnalysisPlan:
    required_operations = {
        "annual_water_level",
        "wetland_hydroperiod_anomaly",
        "precipitation_water_level_association",
        "cross_source_climate_agreement",
        "render_figures",
    }
    if requested_operations is not None:
        missing = required_operations - set(requested_operations)
        if missing:
            raise ValueError(f"Gemini wetland plan omitted operations: {sorted(missing)}")
    return AnalysisPlan(
        steps=[
            AnalysisStep(
                id="01",
                operation="load_declared_inputs",
                inputs=["harmonized_monthly.csv"],
                output="wetland_dataframe",
            ),
            AnalysisStep(
                id="02",
                operation="annual_water_level",
                inputs=["wetland_dataframe"],
                output="hydrology_trend",
            ),
            AnalysisStep(
                id="03",
                operation="wetland_hydroperiod_anomaly",
                inputs=["wetland_dataframe"],
                output="habitat_pressure_metrics",
            ),
            AnalysisStep(
                id="04",
                operation="precipitation_water_level_association",
                inputs=["wetland_dataframe"],
                output="precipitation_association",
            ),
            AnalysisStep(
                id="05",
                operation="cross_source_climate_agreement",
                inputs=["wetland_dataframe"],
                output="source_agreement",
            ),
            AnalysisStep(
                id="06",
                operation="render_figures",
                inputs=["hydrology_trend", "habitat_pressure_metrics", "source_agreement"],
                output="plots_and_change_layer",
            ),
        ],
        expected_artifacts=[
            "annual_water_level.png",
            "wetland_habitat_pressure.png",
            "precipitation_water_level_association.png",
            "climate_source_agreement.png",
            "habitat_change_layer.geojson",
            "result.json",
        ],
    )


def _create_custom_habitat_plan(
    report: HarmonizationReport, requested_operations: list[str] | None
) -> AnalysisPlan:
    required_operations = {
        "annual_mean",
        "ols_trend_and_significance",
        "seasonal_aggregate",
        "precipitation_trend",
        "habitat_climate_pressure",
        "cross_source_climate_agreement",
        "species_richness_and_sampling",
        "wildfire_exposure",
        "wetland_inventory_summary",
        "ecological_evidence_synthesis",
        "render_figures",
    }
    if requested_operations is not None:
        missing = required_operations - set(requested_operations)
        if missing:
            raise ValueError(f"Gemini custom-area plan omitted operations: {sorted(missing)}")
    return AnalysisPlan(
        steps=[
            AnalysisStep(
                id="01",
                operation="load_declared_inputs",
                inputs=["harmonized_monthly.csv"],
                output="area_dataframe",
            ),
            AnalysisStep(
                id="02", operation="annual_mean", inputs=["area_dataframe"], output="annual_climate"
            ),
            AnalysisStep(
                id="03",
                operation="ols_trend_and_significance",
                inputs=["annual_climate"],
                output="temperature_trend",
            ),
            AnalysisStep(
                id="04",
                operation="seasonal_aggregate",
                inputs=["area_dataframe"],
                output="seasonal_trends",
            ),
            AnalysisStep(
                id="05",
                operation="precipitation_trend",
                inputs=["annual_climate"],
                output="precipitation_trend",
            ),
            AnalysisStep(
                id="06",
                operation="habitat_climate_pressure",
                inputs=["annual_climate"],
                output="pressure_indicators",
            ),
            AnalysisStep(
                id="07",
                operation="cross_source_climate_agreement",
                inputs=["annual_climate"],
                output="source_agreement",
            ),
            AnalysisStep(
                id="08",
                operation="species_richness_and_sampling",
                inputs=["area_dataframe"],
                output="biodiversity_indicators",
            ),
            AnalysisStep(
                id="09",
                operation="wildfire_exposure",
                inputs=["area_dataframe"],
                output="wildfire_indicators",
            ),
            AnalysisStep(
                id="10",
                operation="wetland_inventory_summary",
                inputs=["area_dataframe"],
                output="wetland_indicators",
            ),
            AnalysisStep(
                id="11",
                operation="ecological_evidence_synthesis",
                inputs=[
                    "pressure_indicators",
                    "biodiversity_indicators",
                    "wildfire_indicators",
                    "wetland_indicators",
                ],
                output="ecological_assessment",
            ),
            AnalysisStep(
                id="12",
                operation="render_figures",
                inputs=[
                    "temperature_trend",
                    "precipitation_trend",
                    "seasonal_trends",
                    "source_agreement",
                    "ecological_assessment",
                ],
                output="plots_and_change_layer",
            ),
        ],
        expected_artifacts=[
            "area_temperature_trend.png",
            "area_precipitation_trend.png",
            "seasonal_change.png",
            "climate_source_agreement.png",
            "biodiversity_observations.png",
            "wildfire_wetlands.png",
            "habitat_change_layer.geojson",
            "species_biodiversity_layer.geojson",
            "wildfire_layer.geojson",
            "wetlands_layer.geojson",
            "result.json",
        ],
    )
