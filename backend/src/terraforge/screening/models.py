from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl, model_validator

from terraforge.contracts.models import ArtifactRecord, RunEvent


def utc_now() -> datetime:
    return datetime.now(UTC)


class ScreeningStatus(StrEnum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    ACQUIRING_HEAT = "ACQUIRING_HEAT"
    RESEARCHING_SITES = "RESEARCHING_SITES"
    SCORING = "SCORING"
    AUDITING = "AUDITING"
    REPORTING = "REPORTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SourceCitation(BaseModel):
    title: str
    url: HttpUrl
    publisher: str
    retrieved_at: datetime = Field(default_factory=utc_now)
    fact: str
    official: bool = True


class EvidenceFact(BaseModel):
    category: Literal["power", "water", "permitting", "logistics"]
    fact: str
    source_url: HttpUrl
    confidence: float = Field(ge=0, le=1)


class SiteEvidence(BaseModel):
    summary: str
    permitting_readiness: Literal[
        "explicit_by_right",
        "administrative_or_special_review",
        "discretionary_multi_agency",
        "moratorium_or_prohibition",
        "unknown",
    ] = "unknown"
    infrastructure_readiness: Literal["established", "documented", "limited", "unknown"] = "unknown"
    industrial_energy_price_cents_kwh: float | None = Field(default=None, gt=0, le=100)
    facts: list[EvidenceFact] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)


class FactorWeights(BaseModel):
    thermal: float = Field(default=40, ge=0, le=100)
    power: float = Field(default=25, ge=0, le=100)
    water: float = Field(default=15, ge=0, le=100)
    permitting: float = Field(default=10, ge=0, le=100)
    logistics: float = Field(default=10, ge=0, le=100)

    @model_validator(mode="after")
    def require_weight(self):
        if self.total <= 0:
            raise ValueError("At least one screening factor must have a positive weight")
        return self

    @property
    def total(self) -> float:
        return self.thermal + self.power + self.water + self.permitting + self.logistics

    def normalized(self) -> dict[str, float]:
        return {key: round(value / self.total, 6) for key, value in self.model_dump().items()}


class CoolingScenario(BaseModel):
    it_load_mw: float = Field(default=50, gt=0, le=1000)
    utilization: float = Field(default=0.85, gt=0, le=1)
    baseline_pue: float = Field(default=1.20, ge=1, le=3)
    reference_temperature_c: float = Field(default=18, ge=-20, le=40)
    pue_sensitivity_per_c: float = Field(default=0.006, ge=0, le=0.1)
    annualize: bool = False


CoolingSystem = Literal["dry", "evaporative", "hybrid", "liquid"]


class ResourceEstimatorRequest(BaseModel):
    """Engineering-scenario inputs for a user-drawn candidate footprint."""

    site_id: str = Field(min_length=2, max_length=160)
    polygon: dict[str, Any]
    it_load_mw: float = Field(default=50, gt=0, le=1000)
    utilization: float = Field(default=0.85, gt=0, le=1)
    baseline_pue: float = Field(default=1.20, ge=1, le=3)
    reference_temperature_c: float = Field(default=18, ge=-20, le=40)
    pue_sensitivity_per_c: float = Field(default=0.006, ge=0, le=0.1)
    cooling_system: CoolingSystem = "hybrid"
    it_density_mw_per_acre: float | None = Field(default=None, gt=0, le=10)


class ResourceEstimate(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    site_id: str
    created_at: datetime = Field(default_factory=utc_now)
    polygon: dict[str, Any]
    area_acres: float = Field(gt=0)
    area_sq_mi: float = Field(gt=0, le=10)
    cooling_system: CoolingSystem
    it_density_mw_per_acre: float | None = None
    it_load_mw: float
    utilization: float
    baseline_pue: float
    heat_adjusted_pue: float
    peak_pue: float
    average_facility_power_mw: float
    peak_facility_power_mw: float
    window_it_energy_mwh: float
    window_facility_energy_mwh: float
    window_water_liters_low: float
    window_water_liters_high: float
    window_water_gallons_low: float
    window_water_gallons_high: float
    illustrative_annual_energy_mwh: float
    illustrative_annual_water_gallons_low: float
    illustrative_annual_water_gallons_high: float
    wue_l_kwh_low: float
    wue_l_kwh_high: float
    thermal: ThermalMetrics
    confidence: float = Field(ge=0, le=1)
    assumptions: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "Scenario estimate only; not an engineering design, utility-capacity commitment, "
        "or water-rights determination."
    )


class ScreeningConstraints(BaseModel):
    max_energy_price_cents_kwh: float | None = Field(default=None, gt=0)
    max_water_risk: float | None = Field(default=None, ge=0, le=5)
    exclude_permitting_moratoria: bool = True


class ThermalWindow(BaseModel):
    start_date: date = date(2026, 7, 1)
    end_date: date = date(2026, 7, 31)
    threshold_c: float = Field(default=35, ge=-20, le=60)
    granularity_m: int = Field(default=100)

    @model_validator(mode="after")
    def validate_window(self):
        if self.start_date < date(2021, 1, 1):
            raise ValueError("FortyGuard hackathon analyses must start on or after 2021-01-01")
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if (self.end_date - self.start_date).days + 1 > 31:
            raise ValueError("Thermal screening windows may not exceed one month")
        if self.granularity_m not in {60, 80, 100}:
            raise ValueError("granularity_m must be 60, 80, or 100")
        return self


class CandidateInput(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    metro: str = Field(min_length=2, max_length=80)
    state: str = Field(min_length=2, max_length=2)
    latitude: float = Field(ge=18, le=72)
    longitude: float = Field(ge=-179, le=-66)
    area_sq_mi: float = Field(default=1, gt=0, le=10)

    @model_validator(mode="after")
    def require_us_coordinates(self):
        us_states = {
            "AL",
            "AK",
            "AZ",
            "AR",
            "CA",
            "CO",
            "CT",
            "DE",
            "FL",
            "GA",
            "HI",
            "ID",
            "IL",
            "IN",
            "IA",
            "KS",
            "KY",
            "LA",
            "ME",
            "MD",
            "MA",
            "MI",
            "MN",
            "MS",
            "MO",
            "MT",
            "NE",
            "NV",
            "NH",
            "NJ",
            "NM",
            "NY",
            "NC",
            "ND",
            "OH",
            "OK",
            "OR",
            "PA",
            "RI",
            "SC",
            "SD",
            "TN",
            "TX",
            "UT",
            "VT",
            "VA",
            "WA",
            "WV",
            "WI",
            "WY",
            "DC",
        }
        point = (self.latitude, self.longitude)
        regions = (
            (24.3, 49.6, -125.0, -66.0),  # contiguous United States
            (51.0, 72.0, -179.0, -129.0),  # Alaska
            (18.8, 22.6, -161.0, -154.0),  # Hawaii
        )
        in_region = any(
            south <= point[0] <= north and west <= point[1] <= east
            for south, north, west, east in regions
        )
        if self.state.upper() not in us_states or not in_region:
            raise ValueError("Candidate coordinates must fall within the United States")
        return self


class FacilityRequirements(BaseModel):
    """Physical and operating profile used to generate comparable candidate AOIs."""

    facility_size_acres: float = Field(default=40, ge=1, le=640)
    it_density_mw_per_acre: float = Field(default=1.25, ge=0.05, le=3)
    cooling_system: CoolingSystem = "hybrid"
    shortlist_size: int = Field(default=5, ge=5, le=5)

    @property
    def planned_it_load_mw(self) -> float:
        return round(self.facility_size_acres * self.it_density_mw_per_acre, 2)

    @model_validator(mode="after")
    def validate_planning_capacity(self):
        if self.planned_it_load_mw > 1000:
            raise ValueError("Facility size and IT density may not exceed 1,000 MW")
        return self


class ScreeningRequest(BaseModel):
    brief: str = Field(
        default=(
            "Find the five strongest U.S. markets for a planned data-center campus. "
            "Prioritize thermal resilience, power economics, water security, permitting, and infrastructure."
        ),
        min_length=12,
        max_length=4000,
    )
    candidate_ids: list[str] = Field(
        default_factory=list,
        max_length=5,
    )
    candidates: list[CandidateInput] = Field(default_factory=list, max_length=5)
    auto_shortlist: bool = True
    facility: FacilityRequirements = Field(default_factory=FacilityRequirements)
    weights: FactorWeights = Field(default_factory=FactorWeights)
    constraints: ScreeningConstraints = Field(default_factory=ScreeningConstraints)
    cooling: CoolingScenario = Field(default_factory=CoolingScenario)
    thermal_window: ThermalWindow = Field(default_factory=ThermalWindow)

    @model_validator(mode="after")
    def candidate_count(self):
        if not self.auto_shortlist and not self.candidate_ids and not self.candidates:
            raise ValueError("Select or add at least one candidate site")
        if len(self.candidate_ids) + len(self.candidates) > 5:
            raise ValueError("A screening may compare at most five candidate sites")
        self.cooling.it_load_mw = self.facility.planned_it_load_mw
        return self


class ThermalMetrics(BaseModel):
    activity_ids: list[str] = Field(default_factory=list)
    mean_temperature_c: float
    maximum_temperature_c: float
    minimum_temperature_c: float | None = None
    exceedance_ratio: float = Field(ge=0, le=1)
    threshold_c: float
    map_data: dict[str, Any] = Field(default_factory=dict)
    source: str = "FortyGuard Temperature API"


class CandidateSite(BaseModel):
    id: str
    name: str
    metro: str
    state: str
    latitude: float
    longitude: float
    area_sq_mi: float = Field(default=1, gt=0, le=10)
    catalog: bool = True
    industrial_energy_price_cents_kwh: float | None = None
    water_risk_0_5: float | None = Field(default=None, ge=0, le=5)
    permitting_score: float | None = Field(default=None, ge=0, le=100)
    logistics_score: float | None = Field(default=None, ge=0, le=100)
    permitting_status: str = "unknown"
    citations: list[SourceCitation] = Field(default_factory=list)
    research_summary: str | None = None
    evidence: SiteEvidence | None = None
    thermal: ThermalMetrics | None = None
    warnings: list[str] = Field(default_factory=list)
    shortlist_reason: str | None = None


class FactorScore(BaseModel):
    factor: str
    score: float = Field(ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    weight: float = Field(ge=0, le=1)
    contribution: float = Field(ge=0)
    detail: str


class SiteRecommendation(BaseModel):
    site_id: str
    rank: int | None = None
    score: float | None = Field(default=None, ge=0, le=100)
    decision_readiness: float = Field(default=0, ge=0, le=1)
    rankable: bool = False
    eligible: bool = True
    constraint_failures: list[str] = Field(default_factory=list)
    factor_scores: list[FactorScore] = Field(default_factory=list)
    cooling_burden_index: float | None = Field(default=None, ge=0, le=100)
    selected_window_cooling_cost_usd: float | None = Field(default=None, ge=0)
    illustrative_annual_cooling_cost_usd: float | None = Field(default=None, ge=0)


class ScreeningRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    owner_id: UUID | None = None
    status: ScreeningStatus = ScreeningStatus.CREATED
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    request: ScreeningRequest
    candidates: list[CandidateSite] = Field(default_factory=list)
    recommendations: list[SiteRecommendation] = Field(default_factory=list)
    resource_estimates: list[ResourceEstimate] = Field(default_factory=list)
    events: list[RunEvent] = Field(default_factory=list)
    progress: int = 0
    current_step: str = "created"
    summary: str | None = None
    due_diligence: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    audit: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    cancel_requested: bool = False


class CreateScreeningResponse(BaseModel):
    screening_id: UUID
    status: ScreeningStatus


class RescoreRequest(BaseModel):
    weights: FactorWeights | None = None
    cooling: CoolingScenario | None = None
    constraints: ScreeningConstraints | None = None
