from __future__ import annotations

from .models import DecisionAnalysis, FactorWeights, ScreeningRecord, StrategyResult
from .scoring import score_candidates

STRESS_STRATEGIES: tuple[tuple[str, str, FactorWeights | None], ...] = (
    ("Current investment lens", "User-selected priorities", None),
    (
        "Thermal resilience",
        "Heat and cooling continuity",
        FactorWeights(thermal=60, power=15, water=10, permitting=5, logistics=10),
    ),
    (
        "Power economics",
        "Industrial electricity exposure",
        FactorWeights(thermal=20, power=50, water=10, permitting=5, logistics=15),
    ),
    (
        "Water constrained",
        "Local water-risk sensitivity",
        FactorWeights(thermal=25, power=15, water=45, permitting=5, logistics=10),
    ),
    (
        "Delivery speed",
        "Permitting and infrastructure readiness",
        FactorWeights(thermal=20, power=20, water=10, permitting=30, logistics=20),
    ),
)


def _window_energy_cost(energy_mwh: float, cents_per_kwh: float | None) -> float | None:
    if cents_per_kwh is None:
        return None
    return round(energy_mwh * cents_per_kwh * 10, 2)


def build_decision_analysis(record: ScreeningRecord) -> DecisionAnalysis | None:
    """Build an auditable investment case from stored facts and deterministic scores."""

    leader = next(
        (
            item
            for item in record.recommendations
            if item.rank == 1 and item.rankable and item.eligible
        ),
        None,
    )
    if leader is None:
        return None

    sites = {site.id: site for site in record.candidates}
    estimates = {}
    for estimate in record.resource_estimates:
        estimates.setdefault(estimate.site_id, estimate)
    leader_estimate = estimates.get(leader.site_id)
    if leader_estimate is None:
        return None

    comparable = [estimate for site_id, estimate in estimates.items() if site_id in sites]
    if not comparable:
        return None
    hottest = max(
        comparable,
        key=lambda item: (item.thermal.mean_temperature_c, item.window_facility_energy_mwh),
    )

    costs = {
        estimate.site_id: _window_energy_cost(
            estimate.window_facility_energy_mwh,
            sites[estimate.site_id].industrial_energy_price_cents_kwh,
        )
        for estimate in comparable
    }
    costed = [(site_id, cost) for site_id, cost in costs.items() if cost is not None]
    costliest_site_id, costliest_cost = (
        max(costed, key=lambda item: item[1]) if costed else (None, None)
    )
    leader_cost = costs.get(leader.site_id)

    strategies: list[StrategyResult] = []
    leader_wins = 0
    for name, emphasis, fixed_weights in STRESS_STRATEGIES:
        weights = fixed_weights or record.request.weights
        ranked = score_candidates(
            record.candidates,
            weights,
            record.request.constraints,
            record.request.cooling,
            record.request.thermal_window,
        )
        eligible = [item for item in ranked if item.rankable and item.eligible]
        winner = eligible[0] if eligible else None
        runner_up = eligible[1] if len(eligible) > 1 else None
        if winner and winner.site_id == leader.site_id:
            leader_wins += 1
        margin = (
            round((winner.score or 0) - (runner_up.score or 0), 2)
            if winner and runner_up
            else None
        )
        strategies.append(
            StrategyResult(
                name=name,
                emphasis=emphasis,
                weights=weights,
                winner_site_id=winner.site_id if winner else None,
                winner_score=winner.score if winner else None,
                margin_to_second=margin,
            )
        )

    total = len(strategies)
    robustness_label = (
        "resilient" if leader_wins >= 4 else "competitive" if leader_wins >= 3 else "sensitive"
    )
    return DecisionAnalysis(
        leader_site_id=leader.site_id,
        hottest_site_id=hottest.site_id,
        costliest_site_id=costliest_site_id,
        window_days=(
            record.request.thermal_window.end_date - record.request.thermal_window.start_date
        ).days
        + 1,
        leader_window_energy_cost_usd=leader_cost,
        costliest_window_energy_cost_usd=costliest_cost,
        window_cost_advantage_usd=(
            round(max(0, costliest_cost - leader_cost), 2)
            if costliest_cost is not None and leader_cost is not None
            else None
        ),
        window_energy_avoided_mwh=round(
            max(0, hottest.window_facility_energy_mwh - leader_estimate.window_facility_energy_mwh),
            2,
        ),
        window_water_avoided_gallons_low=round(
            max(0, hottest.window_water_gallons_low - leader_estimate.window_water_gallons_low),
            2,
        ),
        window_water_avoided_gallons_high=round(
            max(0, hottest.window_water_gallons_high - leader_estimate.window_water_gallons_high),
            2,
        ),
        robustness_wins=leader_wins,
        robustness_total=total,
        robustness_label=robustness_label,
        strategies=strategies,
        assumptions=[
            "Selected-window electricity spend multiplies heat-adjusted facility energy by the cited EIA state industrial average; it excludes demand charges, taxes, incentives, and contracted tariffs.",
            "Avoided energy and direct water compare the recommended site with the hottest rankable finalist using the same facility, utilization, PUE sensitivity, cooling architecture, and July window.",
            "The five strategy tests reweight stored evidence only. They trigger no model-authored scores and no additional provider calls.",
        ],
    )
