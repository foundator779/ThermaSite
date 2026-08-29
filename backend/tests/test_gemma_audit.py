import os
from types import SimpleNamespace

import pytest

from terraforge.audit import GemmaAuditService
from terraforge.contracts.models import GemmaAuditVerdict, RunRecord
from terraforge.settings import Settings

pytestmark = pytest.mark.asyncio


class FakeGemmaClient:
    def __init__(self, arguments=None):
        self.arguments = arguments
        self.models = self

    def generate_content(self, **kwargs):
        self.kwargs = kwargs
        calls = []
        if self.arguments is not None:
            calls = [SimpleNamespace(name="submit_evidence_audit", args=self.arguments)]
        return SimpleNamespace(function_calls=calls)

    def close(self):
        return None


async def test_gemma_forces_typed_tool_call_and_passes_sanitized_finding(tmp_path):
    client = FakeGemmaClient(
        {
            "verdict": "PASS",
            "dispatch_allowed": True,
            "unsupported_claims": [],
            "privacy_concerns": [],
            "action_constraints": ["Verify conditions in the field."],
            "rationale": "Claims stay within the supplied evidence.",
        }
    )
    record = RunRecord(user_query="Assess validated habitat conditions in this selected area")
    record.metrics = {"median_ndvi": 0.42}
    service = GemmaAuditService(
        Settings(google_api_key="test", terraforge_data_dir=tmp_path),
        client_factory=lambda: client,
    )

    audit = await service.audit_finding(record, "Vegetation greenness was below baseline.")

    assert audit.verdict == GemmaAuditVerdict.PASS
    assert audit.dispatch_allowed is True
    assert audit.input_sha256 and audit.output_sha256
    config = client.kwargs["config"]
    assert len(config.tools[0].function_declarations) == 1
    assert config.thinking_config.thinking_level.value == "MINIMAL"
    assert record.model_usage[-1].family == "Gemma"


async def test_gemma_malformed_result_fails_dispatch_closed(tmp_path):
    record = RunRecord(user_query="Assess validated habitat conditions in this selected area")
    service = GemmaAuditService(
        Settings(google_api_key="test", terraforge_data_dir=tmp_path),
        client_factory=lambda: FakeGemmaClient(None),
    )

    audit = await service.audit_dispatch(
        record,
        title="Review habitat change",
        message="A threshold changed.",
        field_actions=["Inspect the area non-destructively."],
        comparison_metrics=["ndvi_anomaly"],
    )

    assert audit.verdict == GemmaAuditVerdict.ERROR
    assert audit.dispatch_allowed is False
    assert "Do not deliver externally" in audit.action_constraints[0]


@pytest.mark.skipif(
    not os.getenv("LIVE_GOOGLE_AI_MODELS"),
    reason="Set LIVE_GOOGLE_AI_MODELS=1 for a real hosted Gemma audit",
)
async def test_live_gemma_exact_configured_model():
    settings = Settings()
    if not settings.google_api_key:
        pytest.skip("GOOGLE_API_KEY is not configured")
    record = RunRecord(user_query="Assess habitat condition from validated measurements")
    record.metrics = {"vegetation_ndvi_anomaly": -0.08, "vegetation_valid_coverage_pct": 91.0}
    audit = await GemmaAuditService(settings).audit_finding(
        record,
        "NDVI was 0.08 below the seasonal baseline with 91 percent valid coverage.",
    )
    assert audit.model == settings.gemma_model
    assert audit.verdict != GemmaAuditVerdict.ERROR
    assert audit.output_sha256
