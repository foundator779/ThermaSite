from __future__ import annotations

import asyncio
import json
import os
from datetime import date
from typing import Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

from terraforge.contracts.models import GeometrySpec, ResearchSpecification
from terraforge.knowledge import DATASETS
from terraforge.settings import Settings

DatasetRole = Literal[
    "local_station_temperature",
    "regional_gridded_temperature",
    "nearby_sea_ice",
    "wetland_station_climate",
    "wetland_regional_climate",
    "wetland_water_level",
    "area_station_climate",
    "area_regional_climate",
    "species_biodiversity",
    "wildfire_activity",
    "wetland_inventory",
    "sentinel_2_l2a",
]
AnalysisOperation = Literal[
    "annual_mean",
    "ols_trend_and_significance",
    "seasonal_aggregate",
    "sea_ice_trend",
    "pearson_association",
    "render_figures",
    "annual_water_level",
    "wetland_hydroperiod_anomaly",
    "precipitation_water_level_association",
    "cross_source_climate_agreement",
    "precipitation_trend",
    "habitat_climate_pressure",
    "species_richness_and_sampling",
    "wildfire_exposure",
    "wetland_inventory_summary",
    "ecological_evidence_synthesis",
    "satellite_vegetation_condition",
]


class AdkResearchDecision(BaseModel):
    """Structured Gemini output that directly controls the research workflow."""

    anchor_place: str
    region: str
    start_year: int = Field(ge=1900, le=2100)
    end_year: int = Field(ge=1900, le=2100)
    variables: list[str] = Field(min_length=1)
    derived_metrics: list[str] = Field(min_length=1)
    analysis_intent: str
    required_data_roles: list[DatasetRole] = Field(min_length=1)
    selected_dataset_ids: list[str] = Field(min_length=1)
    analysis_operations: list[AnalysisOperation] = Field(min_length=1)
    research_bbox: list[float] = Field(min_length=4, max_length=4)
    selection_rationale: str
    causal_claim_allowed: bool = False
    habitat_type: Literal["arctic_coastal", "everglades_wetland", "custom_habitat"] = (
        "arctic_coastal"
    )

    @model_validator(mode="after")
    def validate_decision(self):
        if self.causal_claim_allowed:
            raise ValueError("Correlation-only research cannot authorize a causal claim")
        if self.end_year < self.start_year:
            raise ValueError("end_year must be greater than or equal to start_year")
        available = {entry["dataset_id"]: entry["data_role"] for entry in DATASETS}
        unknown = set(self.selected_dataset_ids) - set(available)
        if unknown:
            raise ValueError(f"Gemini selected unknown dataset IDs: {sorted(unknown)}")
        selected_roles = {available[dataset_id] for dataset_id in self.selected_dataset_ids}
        missing_roles = set(self.required_data_roles) - selected_roles
        if missing_roles:
            raise ValueError(
                f"Selected datasets do not cover required roles: {sorted(missing_roles)}"
            )
        return self

    def to_research_specification(self, query: str) -> ResearchSpecification:
        return ResearchSpecification(
            question=query,
            variables=self.variables,
            derived_metrics=self.derived_metrics,
            anchor_place=self.anchor_place,
            region=self.region,
            start_date=date(self.start_year, 1, 1),
            end_date=date(self.end_year, 12, 31),
            analysis_intent=self.analysis_intent,
            required_data_roles=list(self.required_data_roles),
            causal_claim_allowed=False,
            habitat_type=self.habitat_type,
            research_geometry=GeometrySpec(
                type="BBox", coordinates=self.research_bbox, label=self.region
            ),
        )


class AdkScientificReview(BaseModel):
    """Independent ADK review of deterministic scientific outputs."""

    approved_for_reporting: bool
    confidence_adjustment: float = Field(ge=-0.3, le=0.0)
    reviewer_summary: str = Field(min_length=12, max_length=500)
    concerns: list[str] = Field(default_factory=list, max_length=8)
    action_constraints: list[str] = Field(default_factory=list, max_length=8)


class AdkOperationalActionDecision(BaseModel):
    """ADK decision at the authorized monitoring-to-action boundary."""

    create_incident: bool
    severity: Literal["info", "attention"]
    title: str = Field(min_length=5, max_length=120)
    message: str = Field(min_length=12, max_length=600)
    field_actions: list[str] = Field(default_factory=list, max_length=6)
    notification_recommended: bool = False
    rationale: str = Field(min_length=12, max_length=500)

    @model_validator(mode="after")
    def validate_action(self):
        if self.create_incident and self.severity != "attention":
            raise ValueError("Monitoring incidents require attention severity")
        if not self.create_incident and self.severity != "info":
            raise ValueError("Non-incidents must use info severity")
        if self.notification_recommended and not self.create_incident:
            raise ValueError("Notifications can only be recommended for validated incidents")
        return self


AgentOutput = TypeVar("AgentOutput", bound=BaseModel)


class GoogleAdkRuntime:
    """Google ADK agent backed only by the Gemini Developer API and Google GenAI SDK."""

    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def ready(self) -> bool:
        return self.settings.gemini_enabled and self.settings.gemini_model.startswith("gemini-")

    def assert_ready(self) -> None:
        if not self.settings.gemini_enabled:
            raise RuntimeError("GOOGLE_API_KEY is required to run Gemini research agents")
        if not self.settings.gemini_model.startswith("gemini-"):
            raise RuntimeError("GEMINI_MODEL must identify a Gemini model")

    def _configure_api_key(self) -> None:
        self.assert_ready()
        os.environ["GOOGLE_API_KEY"] = self.settings.google_api_key.get_secret_value()

    def build_genai_client(self):
        """Create the explicit Google GenAI SDK client used for connectivity checks."""
        from google import genai

        self.assert_ready()
        return genai.Client(api_key=self.settings.google_api_key.get_secret_value())

    async def check_connection(self) -> str:
        client = self.build_genai_client()
        try:
            model = await asyncio.to_thread(
                client.models.get,
                model=self.settings.gemini_model,
            )
            return model.name or self.settings.gemini_model
        finally:
            client.close()

    def build_research_planner(self):
        from google.adk.agents import LlmAgent

        registry = json.dumps(DATASETS, separators=(",", ":"), ensure_ascii=False)
        return LlmAgent(
            name="terraforge_research_coordinator",
            description="Plans evidence-linked climate research using registered datasets only.",
            model=self.settings.gemini_model,
            output_schema=AdkResearchDecision,
            output_key="research_decision",
            instruction=(
                "You are HabiWatch's scientific research coordinator. Convert the user's question "
                "into the required structured decision. Use only datasets in the registry below. "
                "Select complementary sources for every required data role. A local station alone "
                "cannot represent a regional climate question. If sea ice is requested, select the "
                "nearby sea-ice role and include sea_ice_trend and pearson_association. "
                "For an Everglades, Florida, wetland, marsh, or water-level question, use only the "
                "three wetland roles and their Everglades datasets; set habitat_type to "
                "everglades_wetland and include annual_water_level, wetland_hydroperiod_anomaly, "
                "precipitation_water_level_association, cross_source_climate_agreement, and "
                "render_figures. For the Utqiagvik/North Slope scenario, set habitat_type to "
                "arctic_coastal and use only the three Arctic roles. "
                "If the question contains an authoritative user-drawn study area, set habitat_type "
                "to custom_habitat, use the two area climate roles plus species_biodiversity, "
                "wildfire_activity, and wetland_inventory. "
                "include annual_mean, ols_trend_and_significance, seasonal_aggregate, "
                "precipitation_trend, habitat_climate_pressure, cross_source_climate_agreement, "
                "species_richness_and_sampling, wildfire_exposure, wetland_inventory_summary, "
                "ecological_evidence_synthesis, and render_figures. The submitted geometry is authoritative. Preserve the "
                "requested years, use a defensible bounding box, and never permit a causal claim from "
                "correlation. Include the operations necessary to calculate annual and seasonal trends, "
                "statistical significance, paired association, and figures when requested. Do not invent "
                f"dataset identifiers. Authoritative registry: {registry}"
            ),
        )

    def build_scientific_reviewer(self):
        from google.adk.agents import LlmAgent

        return LlmAgent(
            name="terraforge_scientific_reviewer",
            description=(
                "Independently challenges habitat findings after deterministic validation."
            ),
            model=self.settings.gemini_model,
            output_schema=AdkScientificReview,
            output_key="scientific_review",
            instruction=(
                "You are HabiWatch's independent Scientific Reviewer. Review only the supplied "
                "structured metrics, deterministic summary, warnings, source coverage, and recorded "
                "disagreements. Approve reporting only when the summary is supported by those inputs. "
                "Never introduce a number, species, location, source, or causal claim that is not in "
                "the supplied evidence. GBIF observations measure documented sampling rather than "
                "absence, abundance, or population change. Reduce confidence when sources are missing "
                "or disagree. State constraints that the Operational Action Agent must preserve."
            ),
        )

    def build_operational_action_agent(self):
        from google.adk.agents import LlmAgent

        return LlmAgent(
            name="terraforge_operational_action_agent",
            description=(
                "Turns validated monitoring comparisons into bounded habitat incidents and field steps."
            ),
            model=self.settings.gemini_model,
            output_schema=AdkOperationalActionDecision,
            output_key="operational_action",
            instruction=(
                "You are HabiWatch's Operational Action Agent. Use only the supplied monitoring "
                "policy, deterministic comparisons, and approved scientific review. Create an incident "
                "only when at least one comparison is marked meaningful and the evidence supports a "
                "field-verification response. A species-count change alone is sampling-dependent and "
                "must not be described as population loss or gain. Recommend concise, non-destructive "
                "field-verification steps. Never contact an agency or claim that delivery occurred; "
                "the runtime separately enforces authorized notification channels."
            ),
        )

    async def _run_agent(
        self,
        agent,
        prompt: str,
        run_id: str,
        output_model: type[AgentOutput],
    ) -> AgentOutput:
        from google.adk.runners import InMemoryRunner
        from google.genai import types

        self._configure_api_key()
        app_name = f"terraforge_{agent.name}"
        runner = InMemoryRunner(agent=agent, app_name=app_name)
        session = await runner.session_service.create_session(
            app_name=app_name, user_id="research-user", session_id=f"{run_id}-{agent.name}"
        )
        responses: list[str] = []
        message = types.Content(role="user", parts=[types.Part(text=prompt)])
        try:
            async for event in runner.run_async(
                user_id="research-user", session_id=session.id, new_message=message
            ):
                if event.content and event.content.parts:
                    text = " ".join(
                        part.text for part in event.content.parts if getattr(part, "text", None)
                    )
                    if text:
                        responses.append(text)
        finally:
            await runner.close()
        if not responses:
            raise RuntimeError(f"Google ADK agent {agent.name} completed without structured output")
        return output_model.model_validate_json(responses[-1])

    async def coordinate(self, query: str, run_id: str) -> AdkResearchDecision:
        """Run the Google ADK agent and return its validated Gemini decision."""
        return await self._run_agent(
            self.build_research_planner(), query, run_id, AdkResearchDecision
        )

    async def review_science(
        self,
        *,
        run_id: str,
        proposed_summary: str,
        metrics: dict,
        confidence: float,
        disagreements: list[dict],
        warnings: list[str],
    ) -> AdkScientificReview:
        prompt = json.dumps(
            {
                "proposed_summary": proposed_summary,
                "structured_metrics": metrics,
                "deterministic_confidence": confidence,
                "source_disagreements": disagreements,
                "execution_warnings": warnings,
            },
            ensure_ascii=False,
            default=str,
        )
        return await self._run_agent(
            self.build_scientific_reviewer(), prompt, run_id, AdkScientificReview
        )

    async def decide_monitoring_action(
        self,
        *,
        run_id: str,
        policy: dict,
        comparisons: list[dict],
        scientific_review: dict,
    ) -> AdkOperationalActionDecision:
        prompt = json.dumps(
            {
                "monitoring_policy": policy,
                "deterministic_comparisons": comparisons,
                "scientific_review": scientific_review,
            },
            ensure_ascii=False,
            default=str,
        )
        return await self._run_agent(
            self.build_operational_action_agent(),
            prompt,
            run_id,
            AdkOperationalActionDecision,
        )
