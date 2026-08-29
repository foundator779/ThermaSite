import json
import os
import time
from datetime import date

import httpx
import pytest
from pydantic import ValidationError

from terraforge.screening.catalog import get_catalog_site, select_catalog_shortlist
from terraforge.screening.decision import build_decision_analysis
from terraforge.screening.estimator import calculate_resource_estimate, normalize_polygon
from terraforge.screening.fortyguard import FortyGuardClient, FortyGuardError, candidate_polygon
from terraforge.screening.models import (
    CandidateInput,
    CandidateSite,
    CoolingScenario,
    EvidenceFact,
    FacilityRequirements,
    FactorWeights,
    ResourceEstimatorRequest,
    ScreeningConstraints,
    ScreeningRecord,
    ScreeningRequest,
    SiteEvidence,
    SourceCitation,
    ThermalMetrics,
    ThermalWindow,
)
from terraforge.screening.research import GroundedSiteResearch
from terraforge.screening.scoring import cooling_cost, score_candidates, score_site
from terraforge.screening.service import ScreeningService
from terraforge.settings import Settings


def thermal(mean: float = 30, maximum: float = 42, exceedance: float = 0.25):
    return ThermalMetrics(
        activity_ids=["activity-tcm", "activity-exceedance"],
        mean_temperature_c=mean,
        maximum_temperature_c=maximum,
        exceedance_ratio=exceedance,
        threshold_c=35,
        map_data={"type": "FeatureCollection", "features": []},
    )


def test_facility_profile_derives_capacity_and_shortlists_five_markets():
    request = ScreeningRequest(
        facility=FacilityRequirements(
            facility_size_acres=80,
            it_density_mw_per_acre=1.5,
            cooling_system="liquid",
        )
    )
    assert request.cooling.it_load_mw == 120
    shortlist = select_catalog_shortlist(request.weights, request.constraints)
    assert len(shortlist) == 5
    assert len({site.id for site in shortlist}) == 5
    assert all(site.shortlist_reason and "FortyGuard" in site.shortlist_reason for site in shortlist)


def test_catalog_uses_named_industrial_edge_search_zones_not_city_centroids():
    expected = {
        "phoenix-az": ("Buckeye", 33.4435, -112.5870),
        "columbus-oh": ("New Albany", 40.1120, -82.7490),
        "hillsboro-or": ("Hillsboro", 45.5700, -122.9680),
        "council-bluffs-ia": ("Council Bluffs", 41.1980, -95.7890),
        "ashburn-va": ("Loudoun Gateway", 38.9580, -77.5115),
    }
    for site_id, (metro, latitude, longitude) in expected.items():
        site = get_catalog_site(site_id)
        assert site is not None
        assert "Edge" in site.name
        assert site.metro == metro
        assert site.latitude == pytest.approx(latitude)
        assert site.longitude == pytest.approx(longitude)


def test_weights_normalize_and_missing_heat_is_unranked():
    assert sum(FactorWeights(thermal=80, power=20).normalized().values()) == pytest.approx(1)
    site = get_catalog_site("phoenix-az")
    result = score_site(
        site,
        FactorWeights(),
        ScreeningConstraints(),
        CoolingScenario(),
        ThermalWindow(),
    )
    assert result.rankable is False
    assert result.score is None
    assert "FortyGuard" in result.constraint_failures[0]


def test_scoring_is_deterministic_and_hard_constraints_block_recommendation():
    phoenix = get_catalog_site("phoenix-az")
    columbus = get_catalog_site("columbus-oh")
    phoenix.thermal = thermal(mean=36, maximum=47, exceedance=0.7)
    columbus.thermal = thermal(mean=27, maximum=36, exceedance=0.1)
    constraints = ScreeningConstraints(max_water_risk=3)
    first = score_candidates(
        [phoenix, columbus], FactorWeights(), constraints, CoolingScenario(), ThermalWindow()
    )
    second = score_candidates(
        [phoenix, columbus], FactorWeights(), constraints, CoolingScenario(), ThermalWindow()
    )
    assert first == second
    assert first[0].site_id == "columbus-oh"
    phoenix_result = next(item for item in first if item.site_id == "phoenix-az")
    assert phoenix_result.eligible is False
    assert "water-risk" in phoenix_result.constraint_failures[0].lower()


def test_missing_secondary_factor_regresses_to_neutral_with_zero_confidence():
    site = get_catalog_site("columbus-oh")
    site.thermal = thermal()
    site.water_risk_0_5 = None
    result = score_site(
        site, FactorWeights(), ScreeningConstraints(), CoolingScenario(), ThermalWindow()
    )
    water = next(item for item in result.factor_scores if item.factor == "water")
    assert water.score == 50
    assert water.confidence == 0
    assert result.decision_readiness < 1


def test_selected_window_cooling_math_is_labeled_scenario():
    site = get_catalog_site("columbus-oh")
    site.thermal = thermal(mean=28)
    window = ThermalWindow(start_date=date(2026, 7, 1), end_date=date(2026, 7, 31))
    burden, cost = cooling_cost(site, CoolingScenario(), window)
    expected_pue = 1.2 + (28 - 18) * 0.006
    expected = 50 * 31 * 24 * 0.85 * (expected_pue - 1) * 7.10 * 10
    assert burden is not None
    assert cost == pytest.approx(expected, abs=0.01)
    annualized = score_site(
        site,
        FactorWeights(),
        ScreeningConstraints(),
        CoolingScenario(annualize=True),
        window,
    )
    assert annualized.illustrative_annual_cooling_cost_usd == pytest.approx(
        cost * 365 / 31, abs=0.01
    )


def test_candidate_validation_enforces_us_dates_and_basic_plan_area():
    with pytest.raises(ValidationError, match="United States"):
        CandidateInput(
            name="Toronto site", metro="Toronto", state="ON", latitude=43.65, longitude=-79.38
        )
    with pytest.raises(ValidationError, match="2021-01-01"):
        ThermalWindow(start_date=date(2020, 7, 1), end_date=date(2020, 7, 2))
    site = get_catalog_site("phoenix-az")
    site.area_sq_mi = 10
    assert candidate_polygon(site)["features"][0]["geometry"]["type"] == "Polygon"


def footprint(longitude=-112.074, latitude=33.4484, half_side=0.003):
    ring = [
        [longitude - half_side, latitude - half_side],
        [longitude + half_side, latitude - half_side],
        [longitude + half_side, latitude + half_side],
        [longitude - half_side, latitude + half_side],
        [longitude - half_side, latitude - half_side],
    ]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        ],
    }


def test_drawn_footprint_is_server_sized_and_limited_to_us_basic_plan():
    polygon, area = normalize_polygon(footprint(), "phoenix-az")
    assert polygon["features"][0]["properties"]["purpose"] == "resource_estimator"
    assert 0 < area < 10
    with pytest.raises(ValueError, match="10 square miles"):
        normalize_polygon(footprint(half_side=0.05), "phoenix-az")
    with pytest.raises(ValueError, match="selected U.S. candidate"):
        normalize_polygon(
            footprint(longitude=-79.38, latitude=43.65),
            "phoenix-az",
            expected_latitude=33.4484,
            expected_longitude=-112.074,
        )


def test_resource_estimator_produces_transparent_power_and_water_ranges():
    request = ResourceEstimatorRequest(site_id="phoenix-az", polygon=footprint())
    polygon, area = normalize_polygon(request.polygon, request.site_id)
    result = calculate_resource_estimate(
        request, polygon, area, thermal(mean=36, maximum=47), ThermalWindow()
    )
    expected_pue = 1.2 + (36 - 18) * 0.006
    assert result.heat_adjusted_pue == pytest.approx(expected_pue, abs=0.001)
    assert result.average_facility_power_mw == pytest.approx(
        50 * 0.85 * expected_pue, abs=0.01
    )
    assert result.peak_facility_power_mw > result.average_facility_power_mw
    assert result.window_water_gallons_high > result.window_water_gallons_low > 0
    assert "extrapolate" in " ".join(result.assumptions).lower()


def test_decision_analysis_quantifies_impact_and_stress_tests_the_winner():
    phoenix = get_catalog_site("phoenix-az")
    columbus = get_catalog_site("columbus-oh")
    phoenix.thermal = thermal(mean=37, maximum=48, exceedance=0.72)
    columbus.thermal = thermal(mean=24, maximum=35, exceedance=0.05)
    record = ScreeningRecord(request=ScreeningRequest(), candidates=[phoenix, columbus])
    for site in record.candidates:
        polygon = candidate_polygon(site)
        estimate = calculate_resource_estimate(
            ResourceEstimatorRequest(
                site_id=site.id,
                polygon=polygon,
                it_load_mw=record.request.cooling.it_load_mw,
                utilization=record.request.cooling.utilization,
                baseline_pue=record.request.cooling.baseline_pue,
                reference_temperature_c=record.request.cooling.reference_temperature_c,
                pue_sensitivity_per_c=record.request.cooling.pue_sensitivity_per_c,
                cooling_system=record.request.facility.cooling_system,
                it_density_mw_per_acre=record.request.facility.it_density_mw_per_acre,
            ),
            polygon,
            site.area_sq_mi,
            site.thermal,
            record.request.thermal_window,
        )
        record.resource_estimates.append(estimate)
    record.recommendations = score_candidates(
        record.candidates,
        record.request.weights,
        record.request.constraints,
        record.request.cooling,
        record.request.thermal_window,
    )
    record.decision_analysis = build_decision_analysis(record)

    assert record.decision_analysis is not None
    assert record.decision_analysis.leader_site_id == "columbus-oh"
    assert record.decision_analysis.hottest_site_id == "phoenix-az"
    assert record.decision_analysis.window_energy_avoided_mwh > 0
    assert record.decision_analysis.window_water_avoided_gallons_high > 0
    assert record.decision_analysis.window_cost_advantage_usd is not None
    assert record.decision_analysis.robustness_total == 5
    assert len(record.decision_analysis.strategies) == 5
    assert record.decision_analysis.robustness_wins >= 3

    assert ScreeningService._audit(record)["passed"] is True
    record.decision_analysis.window_energy_avoided_mwh += 1
    audit = ScreeningService._audit(record)
    assert audit["passed"] is False
    assert any("decision-impact" in warning for warning in audit["warnings"])


def test_firestore_screening_envelope_round_trips_nested_geojson():
    site = get_catalog_site("phoenix-az")
    site.thermal = thermal()
    site.thermal.map_data = footprint()
    record = ScreeningRecord(request=ScreeningRequest(), candidates=[site])
    document = {
        "payload": record.model_dump_json(),
        "owner_id": None,
        "status": record.status.value,
        "updated_at": record.updated_at,
    }
    from terraforge.screening.store import ScreeningStore

    restored = ScreeningStore._decode_document(document)
    assert restored == record
    assert restored.candidates[0].thermal.map_data["features"][0]["geometry"]["coordinates"]


def fortyguard_transport(captured: list[httpx.Request], malformed: bool = False):
    def handler(request: httpx.Request):
        captured.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            activity = "tcm-id" if body["analytic_type"] == "tcm" else "exceedance-id"
            return httpx.Response(202, json={"data": {"activity_id": activity}})
        activity = request.url.path.rsplit("/", 1)[-1]
        features = (
            []
            if malformed
            else [
                {"type": "Feature", "properties": {"value": 0}, "geometry": None},
                {"type": "Feature", "properties": {"value": 1}, "geometry": None},
            ]
        )
        result = {
            "map_data": {"type": "FeatureCollection", "features": features}
            if not malformed
            else {"features": []},
        }
        if activity == "tcm-id":
            result["stats_data"] = {"Temperature_stats": {"Mean": 31.5, "Maximum": 44}}
        return httpx.Response(
            200,
            json={"data": {"status": "completed", "result": result}},
        )

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_fortyguard_uses_secret_header_polls_and_preserves_activity_ids(tmp_path):
    captured: list[httpx.Request] = []
    settings = Settings(
        _env_file=None,
        terraforge_data_dir=tmp_path,
        fortyguard_api_key="super-secret",
        fortyguard_base_url="https://fortyguard.test",
        fortyguard_poll_interval_seconds=0.001,
        fortyguard_poll_timeout_seconds=1,
    )
    async with httpx.AsyncClient(transport=fortyguard_transport(captured)) as client:
        metrics = await FortyGuardClient(settings, client).analyze(
            get_catalog_site("phoenix-az"), ThermalWindow()
        )
    assert metrics.mean_temperature_c == 31.5
    assert metrics.exceedance_ratio == 0.5
    assert set(metrics.activity_ids) == {"tcm-id", "exceedance-id"}
    assert len([request for request in captured if request.method == "POST"]) == 2
    assert all(request.headers["api-key"] == "super-secret" for request in captured)
    assert "super-secret" not in metrics.model_dump_json()


@pytest.mark.asyncio
async def test_fortyguard_rejects_malformed_geojson(tmp_path):
    settings = Settings(
        _env_file=None,
        terraforge_data_dir=tmp_path,
        fortyguard_api_key="secret",
        fortyguard_base_url="https://fortyguard.test",
        fortyguard_poll_interval_seconds=0.001,
        fortyguard_poll_timeout_seconds=1,
    )
    async with httpx.AsyncClient(transport=fortyguard_transport([], malformed=True)) as client:
        with pytest.raises(FortyGuardError, match="malformed GeoJSON"):
            await FortyGuardClient(settings, client).analyze(
                get_catalog_site("phoenix-az"), ThermalWindow()
            )


@pytest.mark.asyncio
async def test_fortyguard_tolerates_transient_status_404(tmp_path):
    calls = 0

    def handler(request: httpx.Request):
        nonlocal calls
        if request.method == "POST":
            return httpx.Response(202, json={"data": {"activity_id": "warming-up"}})
        calls += 1
        if calls == 1:
            return httpx.Response(404)
        return httpx.Response(200, json={"data": {"status": "completed", "result": {}}})

    settings = Settings(
        _env_file=None,
        terraforge_data_dir=tmp_path,
        fortyguard_api_key="secret",
        fortyguard_base_url="https://fortyguard.test",
        fortyguard_poll_interval_seconds=0.001,
        fortyguard_poll_timeout_seconds=1,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await FortyGuardClient(settings, client)._submit_and_poll(
            client, {"analytic_type": "tcm"}
        )
    assert calls == 2
    assert result["data"]["activity_id"] == "warming-up"


@pytest.mark.asyncio
async def test_fortyguard_polling_timeout_is_bounded_and_retryable(tmp_path):
    def handler(request: httpx.Request):
        if request.method == "POST":
            return httpx.Response(202, json={"data": {"activity_id": "slow-job"}})
        return httpx.Response(200, json={"data": {"status": "running"}})

    settings = Settings(
        _env_file=None,
        terraforge_data_dir=tmp_path,
        fortyguard_api_key="secret",
        fortyguard_base_url="https://fortyguard.test",
        fortyguard_poll_interval_seconds=0.001,
        fortyguard_poll_timeout_seconds=0.01,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FortyGuardError, match="bounded polling timeout") as raised:
            await FortyGuardClient(settings, client)._submit_and_poll(
                client, {"analytic_type": "tcm"}
            )
    assert raised.value.retryable is True


@pytest.mark.parametrize(
    ("status", "message", "retryable"),
    [
        (401, "invalid", False),
        (403, "authorize", False),
        (429, "rate limit", True),
        (503, "failed", True),
    ],
)
def test_fortyguard_errors_are_actionable_and_redacted(status, message, retryable):
    response = httpx.Response(status, request=httpx.Request("GET", "https://fortyguard.test"))
    with pytest.raises(FortyGuardError) as raised:
        FortyGuardClient._raise(response)
    assert message in str(raised.value)
    assert raised.value.retryable is retryable
    assert "api-key" not in str(raised.value).lower()


@pytest.mark.asyncio
async def test_grounded_research_caches_typed_facts_and_prioritizes_official_sources(tmp_path):
    settings = Settings(_env_file=None, terraforge_data_dir=tmp_path, google_api_key="test-key")
    research = GroundedSiteResearch(settings)
    site = CandidateSite(
        id="custom-ne",
        name="Council Bluffs site",
        metro="Omaha",
        state="NE",
        latitude=41.26,
        longitude=-95.86,
        catalog=False,
    )
    evidence = SiteEvidence(
        summary="Administrative review and an established fiber ecosystem are documented.",
        permitting_readiness="administrative_or_special_review",
        infrastructure_readiness="established",
        facts=[
            EvidenceFact(
                category="permitting",
                fact="A development review is required.",
                source_url="https://omaha.gov/planning",
                confidence=0.9,
            )
        ],
    )
    citations = [
        SourceCitation(
            title="Operator source",
            url="https://example.com/fiber",
            publisher="Operator",
            fact="Fiber routes are documented.",
            official=False,
        ),
        SourceCitation(
            title="Planning source",
            url="https://omaha.gov/planning",
            publisher="City",
            fact="A development review is required.",
            official=True,
        ),
    ]
    research._research = lambda _: (evidence, citations)  # type: ignore[method-assign]
    await research.enrich(site)
    assert site.permitting_score == 70
    assert site.logistics_score == 90
    assert site.citations[0].official is True
    assert site.citations[0].fact == "A development review is required."

    cached_site = site.model_copy(deep=True)
    cached_site.citations = []
    cached_site.evidence = None
    research._research = lambda _: (_ for _ in ()).throw(AssertionError("cache missed"))  # type: ignore[method-assign]
    await research.enrich(cached_site)
    assert cached_site.evidence == evidence


@pytest.mark.asyncio
async def test_stale_grounded_research_is_not_silently_reused(tmp_path):
    settings = Settings(_env_file=None, terraforge_data_dir=tmp_path, google_api_key="test-key")
    research = GroundedSiteResearch(settings)
    site = CandidateSite(
        id="custom-tx",
        name="Texas site",
        metro="Dallas",
        state="TX",
        latitude=32.78,
        longitude=-96.8,
        catalog=False,
    )
    path = research._cache_path(site)
    path.write_text(json.dumps({"evidence": {"summary": "Old evidence"}, "citations": []}))
    stale_time = time.time() - 8 * 24 * 60 * 60
    os.utime(path, (stale_time, stale_time))
    research._research = lambda _: (_ for _ in ()).throw(RuntimeError("provider down"))  # type: ignore[method-assign]
    await research.enrich(site)
    assert site.evidence is None
    assert any("stale" in warning.lower() for warning in site.warnings)
    assert any("unavailable" in warning.lower() for warning in site.warnings)


def test_permitting_schema_rejects_unsupported_claim_categories():
    with pytest.raises(ValidationError):
        SiteEvidence(summary="Unverified", permitting_readiness="instant approval")
