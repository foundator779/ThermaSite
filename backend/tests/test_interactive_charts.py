from terraforge.analysis.codegen import (
    CUSTOM_HABITAT_ANALYSIS,
    GENERATED_ANALYSIS,
    WETLAND_ANALYSIS,
)
from terraforge.contracts.models import RunRecord


def test_generated_analysis_templates_emit_structured_chart_data():
    for name, source in (
        ("default", GENERATED_ANALYSIS),
        ("custom", CUSTOM_HABITAT_ANALYSIS),
        ("wetland", WETLAND_ANALYSIS),
    ):
        compile(source, name, "exec")
        assert "chart_data" in source
        assert '"data":' in source
        assert '"series":' in source


def test_archived_runs_without_chart_data_remain_compatible():
    record = RunRecord(user_query="Inspect an archived habitat run")
    assert record.chart_data == {}
