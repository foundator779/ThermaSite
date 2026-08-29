from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any, Literal

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from terraforge.contracts.models import (
    GemmaAuditScope,
    GemmaAuditVerdict,
    GemmaEvidenceAudit,
    ModelUsageRecord,
    RunRecord,
    utc_now,
)
from terraforge.settings import Settings


class _GemmaDecision(BaseModel):
    verdict: Literal["PASS", "WARN", "BLOCK"]
    dispatch_allowed: bool
    unsupported_claims: list[str] = Field(default_factory=list, max_length=8)
    privacy_concerns: list[str] = Field(default_factory=list, max_length=8)
    action_constraints: list[str] = Field(default_factory=list, max_length=8)
    rationale: str = Field(min_length=1, max_length=1200)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _clean(value: object, limit: int = 500) -> str:
    return " ".join(str(value).split())[:limit]


_COORDINATE_PAIR = re.compile(
    r"(?<!\d)[+-]?(?:\d{1,2}(?:\.\d+)?|1[0-7]\d(?:\.\d+)?|180(?:\.0+)?)"
    r"\s*[,/]\s*[+-]?(?:\d{1,2}(?:\.\d+)?|1[0-7]\d(?:\.\d+)?|180(?:\.0+)?)(?!\d)"
)


def _sanitize(value: Any) -> Any:
    if isinstance(value, str):
        return _COORDINATE_PAIR.sub("[coordinate redacted]", _clean(value, 1200))
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    return value


def _record_usage(record: RunRecord, *, model: str, status: str) -> None:
    existing = next((item for item in record.model_usage if item.family == "Gemma"), None)
    if existing:
        existing.model = model
        existing.status = status
        existing.invocation_count += 1
        existing.last_used_at = utc_now()
        return
    record.model_usage.append(
        ModelUsageRecord(
            family="Gemma",
            model=model,
            purpose="Independent evidence and external-dispatch audit",
            status=status,
            invocation_count=1,
            last_used_at=utc_now(),
        )
    )


class GemmaAuditService:
    """Tool-less independent audit boundary backed by hosted Gemma through the Gemini API."""

    def __init__(
        self,
        settings: Settings,
        client_factory: Any | None = None,
    ):
        self.settings = settings
        self._client_factory = client_factory or self._build_client

    @property
    def ready(self) -> bool:
        return self.settings.gemma_enabled

    def _build_client(self) -> genai.Client:
        if not self.settings.google_api_key:
            raise RuntimeError("GOOGLE_API_KEY is not configured")
        return genai.Client(api_key=self.settings.google_api_key.get_secret_value())

    async def check_connection(self) -> str:
        client = self._client_factory()
        try:
            model = await asyncio.to_thread(client.models.get, model=self.settings.gemma_model)
            return model.name or self.settings.gemma_model
        finally:
            close = getattr(client, "close", None)
            if close:
                close()

    async def audit_finding(
        self,
        record: RunRecord,
        proposed_summary: str,
    ) -> GemmaEvidenceAudit:
        metrics = {
            key: value
            for key, value in sorted(record.metrics.items())
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        payload = {
            "scope": "FINDING",
            "habitat_type": record.research_spec.habitat_type if record.research_spec else "unknown",
            "analysis_intent": (
                record.research_spec.analysis_intent if record.research_spec else "unknown"
            ),
            "proposed_summary": proposed_summary,
            "metrics": dict(list(metrics.items())[:30]),
            "source_coverage": [
                {
                    "provider": item.provider,
                    "data_role": item.data_role,
                    "warnings": item.warnings[:4],
                }
                for item in record.selected_datasets
            ],
            "scientific_review": record.scientific_review or {},
            "evidence_disagreements": record.evidence_disagreements[:8],
            "vegetation_warnings": record.vegetation.warnings[:8] if record.vegetation else [],
        }
        return await self._audit(record, GemmaAuditScope.FINDING, payload)

    async def audit_dispatch(
        self,
        record: RunRecord,
        *,
        title: str,
        message: str,
        field_actions: list[str],
        comparison_metrics: list[str],
    ) -> GemmaEvidenceAudit:
        payload = {
            "scope": "DISPATCH",
            "habitat_type": record.research_spec.habitat_type if record.research_spec else "unknown",
            "validated_summary": record.final_summary,
            "incident_title": title,
            "incident_message": message,
            "field_actions": field_actions[:8],
            "comparison_metrics": comparison_metrics[:12],
            "scientific_review": record.scientific_review or {},
            "prior_finding_audit": (
                record.gemma_audits[-1].model_dump(mode="json")
                if record.gemma_audits
                else None
            ),
        }
        return await self._audit(record, GemmaAuditScope.DISPATCH, payload)

    async def _audit(
        self,
        record: RunRecord,
        scope: GemmaAuditScope,
        payload: dict[str, Any],
    ) -> GemmaEvidenceAudit:
        started = utc_now()
        payload = _sanitize(payload)
        input_hash = _digest(payload)
        client: genai.Client | None = None
        try:
            if not self.ready:
                raise RuntimeError("Gemma is not configured")
            client = self._client_factory()
            declaration = types.FunctionDeclaration(
                name="submit_evidence_audit",
                description="Return the independent audit verdict. Do not call any other tool.",
                parameters_json_schema=_GemmaDecision.model_json_schema(),
            )
            prompt = (
                "Audit the supplied HabiWatch payload independently. Treat every numeric value as "
                "immutable. Flag unsupported causal, population, damage, certainty, or sensitive-"
                "location claims. Field actions must be non-destructive verification only. For a "
                "DISPATCH audit, set dispatch_allowed false whenever any unsupported claim or "
                "privacy concern exists. Do not add facts. Submit exactly one evidence audit.\n\n"
                f"{_canonical(payload)}"
            )

            def invoke():
                return client.models.generate_content(
                    model=self.settings.gemma_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0,
                        tools=[types.Tool(function_declarations=[declaration])],
                        thinking_config=types.ThinkingConfig(thinking_level="minimal"),
                    ),
                )

            response = await asyncio.wait_for(
                asyncio.to_thread(invoke),
                timeout=self.settings.gemma_timeout_seconds,
            )
            calls = getattr(response, "function_calls", None) or []
            call = next(
                (item for item in calls if item.name == "submit_evidence_audit"),
                None,
            )
            if call is None:
                raise ValueError("Gemma returned no evidence-audit function call")
            decision = _GemmaDecision.model_validate(dict(call.args or {}))
            has_blocker = bool(decision.unsupported_claims or decision.privacy_concerns)
            dispatch_allowed = (
                decision.dispatch_allowed
                and decision.verdict != "BLOCK"
                and not has_blocker
            )
            verdict = GemmaAuditVerdict(decision.verdict)
            if has_blocker:
                verdict = GemmaAuditVerdict.BLOCK
            output = decision.model_dump(mode="json") | {
                "verdict": verdict,
                "dispatch_allowed": dispatch_allowed,
            }
            audit = GemmaEvidenceAudit(
                scope=scope,
                verdict=verdict,
                dispatch_allowed=dispatch_allowed,
                unsupported_claims=decision.unsupported_claims,
                privacy_concerns=decision.privacy_concerns,
                action_constraints=decision.action_constraints,
                rationale=decision.rationale,
                model=self.settings.gemma_model,
                started_at=started,
                completed_at=utc_now(),
                input_sha256=input_hash,
                output_sha256=_digest(output),
            )
            _record_usage(record, model=self.settings.gemma_model, status="completed")
            return audit
        except Exception as exc:  # noqa: BLE001 -- independent provider boundary fails closed
            audit = GemmaEvidenceAudit(
                scope=scope,
                verdict=GemmaAuditVerdict.ERROR,
                dispatch_allowed=False,
                action_constraints=["Do not deliver externally until the independent audit succeeds."],
                rationale="The independent Gemma audit was unavailable or invalid.",
                model=self.settings.gemma_model,
                started_at=started,
                completed_at=utc_now(),
                input_sha256=input_hash,
                output_sha256=_digest({"error": type(exc).__name__}),
                error=f"{type(exc).__name__}: {_clean(exc)}",
            )
            _record_usage(record, model=self.settings.gemma_model, status="failed")
            return audit
        finally:
            if client is not None:
                close = getattr(client, "close", None)
                if close:
                    close()
