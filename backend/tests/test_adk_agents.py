from terraforge.adk import GoogleAdkRuntime
from terraforge.settings import Settings


def test_google_adk_runtime_builds_three_separated_decision_agents():
    runtime = GoogleAdkRuntime(Settings(google_api_key="test-api-key"))

    planner = runtime.build_research_planner()
    reviewer = runtime.build_scientific_reviewer()
    action = runtime.build_operational_action_agent()

    assert planner.name == "terraforge_research_coordinator"
    assert reviewer.name == "terraforge_scientific_reviewer"
    assert action.name == "terraforge_operational_action_agent"
    assert len({planner.output_key, reviewer.output_key, action.output_key}) == 3
