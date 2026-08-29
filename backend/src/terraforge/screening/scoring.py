from __future__ import annotations

from .models import (
    CandidateSite,
    CoolingScenario,
    FactorScore,
    FactorWeights,
    ScreeningConstraints,
    SiteRecommendation,
    ThermalWindow,
)


def clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def lower_is_better(value: float, low: float, high: float) -> float:
    if high <= low:
        return 50
    return clamp(100 * (1 - ((value - low) / (high - low))))


def thermal_suitability(site: CandidateSite) -> tuple[float | None, str]:
    metrics = site.thermal
    if metrics is None:
        return None, "FortyGuard thermal evidence is required before this site can be ranked."
    mean_score = lower_is_better(metrics.mean_temperature_c, 15, 40)
    maximum_score = lower_is_better(metrics.maximum_temperature_c, 25, 50)
    exceedance_score = clamp(100 * (1 - metrics.exceedance_ratio))
    score = 0.3 * mean_score + 0.2 * maximum_score + 0.5 * exceedance_score
    return round(score, 2), (
        f"{metrics.mean_temperature_c:.1f}°C mean, {metrics.maximum_temperature_c:.1f}°C max, "
        f"{metrics.exceedance_ratio * 100:.1f}% of modeled tiles/hours above {metrics.threshold_c:.0f}°C."
    )


def cooling_cost(
    site: CandidateSite,
    scenario: CoolingScenario,
    window: ThermalWindow,
) -> tuple[float | None, float | None]:
    if site.thermal is None or site.industrial_energy_price_cents_kwh is None:
        return None, None
    hours = ((window.end_date - window.start_date).days + 1) * 24
    delta = max(0, site.thermal.mean_temperature_c - scenario.reference_temperature_c)
    adjusted_pue = scenario.baseline_pue + delta * scenario.pue_sensitivity_per_c
    cooling_mwh = scenario.it_load_mw * hours * scenario.utilization * max(adjusted_pue - 1, 0)
    cost = cooling_mwh * site.industrial_energy_price_cents_kwh * 10
    thermal_score, _ = thermal_suitability(site)
    burden = None if thermal_score is None else round(100 - thermal_score, 2)
    return burden, round(cost, 2)


def score_site(
    site: CandidateSite,
    weights: FactorWeights,
    constraints: ScreeningConstraints,
    cooling: CoolingScenario,
    window: ThermalWindow,
) -> SiteRecommendation:
    normalized = weights.normalized()
    thermal_score, thermal_detail = thermal_suitability(site)
    if thermal_score is None:
        return SiteRecommendation(
            site_id=site.id,
            rankable=False,
            eligible=False,
            constraint_failures=[thermal_detail],
        )

    raw: dict[str, tuple[float | None, float, str]] = {
        "thermal": (thermal_score, 1.0, thermal_detail),
        "power": (
            lower_is_better(site.industrial_energy_price_cents_kwh, 5, 20)
            if site.industrial_energy_price_cents_kwh is not None
            else None,
            0.9 if site.industrial_energy_price_cents_kwh is not None else 0,
            (
                f"EIA state industrial average: {site.industrial_energy_price_cents_kwh:.2f}¢/kWh."
                if site.industrial_energy_price_cents_kwh is not None
                else "No sourced electricity price is available."
            ),
        ),
        "water": (
            lower_is_better(site.water_risk_0_5, 0, 5) if site.water_risk_0_5 is not None else None,
            0.7 if site.water_risk_0_5 is not None else 0,
            (
                f"Aqueduct screening risk: {site.water_risk_0_5:.1f}/5; local supply verification remains required."
                if site.water_risk_0_5 is not None
                else "No sourced water-risk screening is available."
            ),
        ),
        "permitting": (
            site.permitting_score,
            0.65 if site.permitting_score is not None else 0,
            f"Permit readiness: {site.permitting_status}; verify timing and zoning with the authority.",
        ),
        "logistics": (
            site.logistics_score,
            0.65 if site.logistics_score is not None else 0,
            "Screening proxy for transport, fiber ecosystem, workforce, and industrial readiness.",
        ),
    }

    factors: list[FactorScore] = []
    total_score = 0.0
    readiness = 0.0
    for factor, weight in normalized.items():
        value, confidence, detail = raw[factor]
        effective = 50.0 if value is None else value
        contribution = weight * ((effective * confidence) + (50 * (1 - confidence)))
        total_score += contribution
        readiness += weight * confidence
        factors.append(
            FactorScore(
                factor=factor,
                score=round(effective, 2),
                confidence=confidence,
                weight=weight,
                contribution=round(contribution, 2),
                detail=detail,
            )
        )

    failures: list[str] = []
    if (
        constraints.max_energy_price_cents_kwh is not None
        and site.industrial_energy_price_cents_kwh is not None
        and site.industrial_energy_price_cents_kwh > constraints.max_energy_price_cents_kwh
    ):
        failures.append(
            f"Energy price {site.industrial_energy_price_cents_kwh:.2f}¢/kWh exceeds the configured maximum."
        )
    if (
        constraints.max_water_risk is not None
        and site.water_risk_0_5 is not None
        and site.water_risk_0_5 > constraints.max_water_risk
    ):
        failures.append(
            f"Water-risk score {site.water_risk_0_5:.1f}/5 exceeds the configured maximum."
        )
    if constraints.exclude_permitting_moratoria and "moratorium" in site.permitting_status.lower():
        failures.append("A documented data-center permitting moratorium fails the configured gate.")

    burden, selected_cost = cooling_cost(site, cooling, window)
    window_days = (window.end_date - window.start_date).days + 1
    annual_cost = (
        round(selected_cost * 365 / window_days, 2)
        if cooling.annualize and selected_cost is not None
        else None
    )
    return SiteRecommendation(
        site_id=site.id,
        score=round(total_score, 2),
        decision_readiness=round(readiness, 3),
        rankable=True,
        eligible=not failures,
        constraint_failures=failures,
        factor_scores=factors,
        cooling_burden_index=burden,
        selected_window_cooling_cost_usd=selected_cost,
        illustrative_annual_cooling_cost_usd=annual_cost,
    )


def score_candidates(
    sites: list[CandidateSite],
    weights: FactorWeights,
    constraints: ScreeningConstraints,
    cooling: CoolingScenario,
    window: ThermalWindow,
) -> list[SiteRecommendation]:
    results = [score_site(site, weights, constraints, cooling, window) for site in sites]
    rankable = sorted(
        (item for item in results if item.rankable),
        key=lambda item: (item.eligible, item.score or 0, item.decision_readiness),
        reverse=True,
    )
    for rank, item in enumerate(rankable, start=1):
        item.rank = rank
    return sorted(results, key=lambda item: item.rank or 999)
