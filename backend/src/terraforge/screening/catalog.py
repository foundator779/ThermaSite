from __future__ import annotations

from copy import deepcopy

from .models import CandidateSite, FactorWeights, ScreeningConstraints, SourceCitation

EIA_URL = "https://www.eia.gov/electricity/annual/table.php?t=epa_02_10.html"
WRI_URL = "https://www.wri.org/aqueduct"


CATALOG_VERSION = "2026.08.3"


SITE_CATALOG: dict[str, CandidateSite] = {
    "phoenix-az": CandidateSite(
        id="phoenix-az",
        name="Buckeye West Valley Industrial Edge",
        metro="Buckeye",
        state="AZ",
        latitude=33.4435,
        longitude=-112.5870,
        industrial_energy_price_cents_kwh=7.90,
        water_risk_0_5=4.5,
        permitting_score=72,
        logistics_score=90,
        permitting_status="administrative review",
        citations=[
            SourceCitation(
                title="Average Price of Electricity to Ultimate Customers by State, 2024",
                url=EIA_URL,
                publisher="U.S. Energy Information Administration",
                fact="Arizona 2024 average industrial electricity price: 7.90 cents/kWh.",
            ),
            SourceCitation(
                title="Aqueduct 4.0 Water Risk Atlas",
                url=WRI_URL,
                publisher="World Resources Institute",
                fact="Baseline water-stress screening requires a local deep dive; this catalog flags the Buckeye search zone as very high risk.",
            ),
            SourceCitation(
                title="Buckeye Development Services",
                url="https://www.buckeyeaz.gov/government/development-services",
                publisher="City of Buckeye",
                fact="Official starting point for zoning, plan review, and permitting verification in the West Valley search zone.",
            ),
        ],
    ),
    "columbus-oh": CandidateSite(
        id="columbus-oh",
        name="New Albany International Business Park Edge",
        metro="New Albany",
        state="OH",
        latitude=40.1120,
        longitude=-82.7490,
        industrial_energy_price_cents_kwh=7.10,
        water_risk_0_5=1.4,
        permitting_score=82,
        logistics_score=88,
        permitting_status="documented development review",
        citations=[
            SourceCitation(
                title="Average Price of Electricity to Ultimate Customers by State, 2024",
                url=EIA_URL,
                publisher="U.S. Energy Information Administration",
                fact="Ohio 2024 average industrial electricity price: 7.10 cents/kWh.",
            ),
            SourceCitation(
                title="Aqueduct 4.0 Water Risk Atlas",
                url=WRI_URL,
                publisher="World Resources Institute",
                fact="Catalog screening marks the Columbus candidate as low-to-medium baseline water stress; verify locally.",
            ),
            SourceCitation(
                title="New Albany Community Development",
                url="https://newalbanyohio.org/answers/community-development/",
                publisher="City of New Albany",
                fact="Official source for development review, zoning, and permit requirements.",
            ),
        ],
    ),
    "hillsboro-or": CandidateSite(
        id="hillsboro-or",
        name="North Hillsboro Industrial Edge",
        metro="Hillsboro",
        state="OR",
        latitude=45.5700,
        longitude=-122.9680,
        industrial_energy_price_cents_kwh=8.05,
        water_risk_0_5=1.8,
        permitting_score=78,
        logistics_score=94,
        permitting_status="established industrial review",
        citations=[
            SourceCitation(
                title="Average Price of Electricity to Ultimate Customers by State, 2024",
                url=EIA_URL,
                publisher="U.S. Energy Information Administration",
                fact="Oregon 2024 average industrial electricity price: 8.05 cents/kWh.",
            ),
            SourceCitation(
                title="Aqueduct 4.0 Water Risk Atlas",
                url=WRI_URL,
                publisher="World Resources Institute",
                fact="Catalog screening marks the Hillsboro candidate as low-to-medium baseline water stress; verify locally.",
            ),
            SourceCitation(
                title="Hillsboro Development Services",
                url="https://www.hillsboro-oregon.gov/our-city/departments/community-development",
                publisher="City of Hillsboro",
                fact="Official source for land use and development permit verification.",
            ),
        ],
    ),
    "council-bluffs-ia": CandidateSite(
        id="council-bluffs-ia",
        name="South Council Bluffs Industrial Edge",
        metro="Council Bluffs",
        state="IA",
        latitude=41.1980,
        longitude=-95.7890,
        industrial_energy_price_cents_kwh=7.20,
        water_risk_0_5=1.3,
        permitting_score=84,
        logistics_score=92,
        permitting_status="documented development review",
        citations=[
            SourceCitation(
                title="Average Price of Electricity to Ultimate Customers by State, 2024",
                url=EIA_URL,
                publisher="U.S. Energy Information Administration",
                fact="The catalog pins a 7.20 cents/kWh Iowa industrial-price planning snapshot; verify the current tariff.",
            ),
            SourceCitation(
                title="Aqueduct 4.0 Water Risk Atlas",
                url=WRI_URL,
                publisher="World Resources Institute",
                fact="Catalog screening marks the Council Bluffs candidate as low-to-medium baseline water stress; verify locally.",
            ),
            SourceCitation(
                title="Council Bluffs Community Development",
                url="https://www.councilbluffs-ia.gov/164/Community-Development",
                publisher="City of Council Bluffs",
                fact="Official starting point for planning, zoning, and development review verification.",
            ),
        ],
    ),
    "ashburn-va": CandidateSite(
        id="ashburn-va",
        name="Loudoun Route 606 Industrial Edge",
        metro="Loudoun Gateway",
        state="VA",
        latitude=38.9580,
        longitude=-77.5115,
        industrial_energy_price_cents_kwh=9.00,
        water_risk_0_5=1.8,
        permitting_score=70,
        logistics_score=98,
        permitting_status="discretionary multi-agency review",
        citations=[
            SourceCitation(
                title="Average Price of Electricity to Ultimate Customers by State, 2024",
                url=EIA_URL,
                publisher="U.S. Energy Information Administration",
                fact="The catalog pins a 9.00 cents/kWh Virginia industrial-price planning snapshot; verify the current tariff.",
            ),
            SourceCitation(
                title="Aqueduct 4.0 Water Risk Atlas",
                url=WRI_URL,
                publisher="World Resources Institute",
                fact="Catalog screening marks the Ashburn candidate as low-to-medium baseline water stress; verify locally.",
            ),
            SourceCitation(
                title="Data Center Standards and Locations",
                url="https://www.loudoun.gov/5990/Data-Center-Standards-Locations",
                publisher="Loudoun County",
                fact="Official source for current data-center siting standards, special-exception rules, and mapped verification.",
            ),
        ],
    ),
    "dallas-tx": CandidateSite(
        id="dallas-tx",
        name="Lancaster South DFW Industrial Edge",
        metro="Lancaster",
        state="TX",
        latitude=32.5670,
        longitude=-96.7790,
        industrial_energy_price_cents_kwh=7.55,
        water_risk_0_5=3.8,
        permitting_score=76,
        logistics_score=96,
        permitting_status="administrative review",
        citations=[
            SourceCitation(
                title="Average Price of Electricity to Ultimate Customers by State, 2024",
                url=EIA_URL,
                publisher="U.S. Energy Information Administration",
                fact="The catalog pins a 7.55 cents/kWh Texas industrial-price planning snapshot; verify the current tariff.",
            ),
            SourceCitation(
                title="Aqueduct 4.0 Water Risk Atlas",
                url=WRI_URL,
                publisher="World Resources Institute",
                fact="Catalog screening flags the south DFW candidate for elevated baseline water stress and local-provider diligence.",
            ),
            SourceCitation(
                title="Lancaster Development Services",
                url="https://www.lancaster-tx.com/263/Development-Services",
                publisher="City of Lancaster",
                fact="Official starting point for zoning, plan review, and permitting verification in the south DFW search zone.",
            ),
        ],
    ),
    "atlanta-ga": CandidateSite(
        id="atlanta-ga",
        name="Douglasville Industrial Edge",
        metro="Douglasville",
        state="GA",
        latitude=33.7140,
        longitude=-84.6250,
        industrial_energy_price_cents_kwh=8.00,
        water_risk_0_5=2.3,
        permitting_score=74,
        logistics_score=90,
        permitting_status="administrative review",
        citations=[
            SourceCitation(
                title="Average Price of Electricity to Ultimate Customers by State, 2024",
                url=EIA_URL,
                publisher="U.S. Energy Information Administration",
                fact="The catalog pins an 8.00 cents/kWh Georgia industrial-price planning snapshot; verify the current tariff.",
            ),
            SourceCitation(
                title="Aqueduct 4.0 Water Risk Atlas",
                url=WRI_URL,
                publisher="World Resources Institute",
                fact="Catalog screening marks Atlanta as medium baseline water stress; verify locally.",
            ),
            SourceCitation(
                title="Douglas County Comprehensive Plan",
                url="https://www.douglascountyga.gov/727/Comprehensive-Plan-Update",
                publisher="Douglas County, Georgia",
                fact="Official source for industrial character areas and local land-use diligence in the western Atlanta search zone.",
            ),
        ],
    ),
    "reno-nv": CandidateSite(
        id="reno-nv",
        name="Tahoe–Reno Industrial Center Edge",
        metro="Storey County",
        state="NV",
        latitude=39.5870,
        longitude=-119.4370,
        industrial_energy_price_cents_kwh=8.45,
        water_risk_0_5=4.2,
        permitting_score=80,
        logistics_score=88,
        permitting_status="documented development review",
        citations=[
            SourceCitation(
                title="Average Price of Electricity to Ultimate Customers by State, 2024",
                url=EIA_URL,
                publisher="U.S. Energy Information Administration",
                fact="The catalog pins an 8.45 cents/kWh Nevada industrial-price planning snapshot; verify the current tariff.",
            ),
            SourceCitation(
                title="Aqueduct 4.0 Water Risk Atlas",
                url=WRI_URL,
                publisher="World Resources Institute",
                fact="Catalog screening flags the Tahoe–Reno industrial search zone for high baseline water stress and local-provider diligence.",
            ),
            SourceCitation(
                title="Tahoe–Reno Industrial Center Development Agreement",
                url="https://www.storeycounty.org/647/Tahoe-Reno-Industrial-Center-Development",
                publisher="Storey County",
                fact="Official source for the industrial center development agreement, zoning, roads, water, sewer, and drainage maps.",
            ),
        ],
    ),
}


def list_catalog() -> list[CandidateSite]:
    return [deepcopy(site) for site in SITE_CATALOG.values()]


def get_catalog_site(site_id: str) -> CandidateSite | None:
    site = SITE_CATALOG.get(site_id)
    return deepcopy(site) if site else None


def select_catalog_shortlist(
    weights: FactorWeights,
    constraints: ScreeningConstraints,
    count: int = 5,
    excluded: set[str] | None = None,
) -> list[CandidateSite]:
    """Deterministic preflight used by the Shortlist Agent before paid heat calls."""

    excluded = excluded or set()
    factor_weights = {
        "power": weights.power,
        "water": weights.water,
        "permitting": weights.permitting,
        "logistics": weights.logistics,
    }
    total = sum(factor_weights.values()) or 1

    def lower_is_better(value: float, low: float, high: float) -> float:
        return max(0, min(100, 100 * (1 - ((value - low) / (high - low)))))

    ranked: list[tuple[bool, float, CandidateSite]] = []
    for site in list_catalog():
        if site.id in excluded:
            continue
        values = {
            "power": lower_is_better(site.industrial_energy_price_cents_kwh or 12.5, 5, 20),
            "water": lower_is_better(site.water_risk_0_5 or 2.5, 0, 5),
            "permitting": site.permitting_score or 50,
            "logistics": site.logistics_score or 50,
        }
        score = sum(values[key] * value / total for key, value in factor_weights.items())
        eligible = not (
            constraints.max_energy_price_cents_kwh is not None
            and (site.industrial_energy_price_cents_kwh or 100)
            > constraints.max_energy_price_cents_kwh
        ) and not (
            constraints.max_water_risk is not None
            and (site.water_risk_0_5 or 5) > constraints.max_water_risk
        )
        site.shortlist_reason = (
            f"Preflight {score:.1f}/100 from sourced power, water, permitting, and "
            "infrastructure evidence; FortyGuard heat decides the final rank."
        )
        ranked.append((eligible, score, site))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [site for _, _, site in ranked[:count]]
