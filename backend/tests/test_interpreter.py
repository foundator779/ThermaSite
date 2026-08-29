from terraforge.agents.interpreter import interpret_research_question


def test_golden_prompt_becomes_multi_source_specification():
    spec = interpret_research_question(
        "How has climate around Utqiaġvik changed from 2005–2025, which seasons changed most, "
        "is warming statistically significant, and how is nearby sea ice related?"
    )
    assert spec.start_date.year == 2005
    assert spec.end_date.year == 2025
    assert spec.required_data_roles == [
        "local_station_temperature",
        "regional_gridded_temperature",
        "nearby_sea_ice",
    ]
    assert spec.causal_claim_allowed is False


def test_missing_dates_get_bounded_defaults():
    spec = interpret_research_question("Analyze the temperature trend around Utqiaġvik, Alaska.")
    assert spec.start_date.year == 2005
    assert spec.end_date.year >= 2025
