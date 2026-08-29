from terraforge.agents.interpreter import interpret_research_question
from terraforge.knowledge.registry import discover


def test_registry_returns_one_authoritative_source_per_required_role():
    spec = interpret_research_question(
        "Assess Utqiaġvik temperature and sea ice from 2005 to 2025 by season and significance."
    )
    candidates = discover(spec)
    assert {candidate.data_role for candidate in candidates} >= set(spec.required_data_roles)
    matching = [
        candidate for candidate in candidates if candidate.data_role in spec.required_data_roles
    ]
    assert len(matching) == 3
    assert all(candidate.match_score > 0.9 for candidate in matching)
    assert all(str(candidate.documentation_url).startswith("https://") for candidate in candidates)
