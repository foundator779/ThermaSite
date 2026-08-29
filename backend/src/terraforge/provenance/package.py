from __future__ import annotations

import io
import json
import platform
import zipfile

from terraforge.contracts.models import AnalysisPlan, ProvenanceManifest, RunRecord
from terraforge.knowledge import REGISTRY_VERSION
from terraforge.persistence.artifacts import ArtifactStore


def build_reproducibility_package(
    run: RunRecord,
    acquisitions: list,
    plan: AnalysisPlan,
    code: str,
    artifacts: ArtifactStore,
):
    manifest = ProvenanceManifest(
        run_id=run.id,
        research_question=run.user_query,
        created_at=run.created_at,
        knowledge_registry_version=REGISTRY_VERSION,
        datasets=[result.model_dump(mode="json") for result in acquisitions],
        transformations=[run.harmonization.model_dump(mode="json") if run.harmonization else {}],
        analysis={
            "plan": plan.model_dump(mode="json"),
            "execution_attempt": max(1, run.repair_attempts + 1),
            "causal_claim_allowed": False,
            "confidence": run.confidence,
            "evidence_disagreements": run.evidence_disagreements,
            "operational_impact": run.operational_impact,
        },
        artifacts=[artifact.model_dump(mode="json") for artifact in run.artifacts],
        software={
            "python": platform.python_version(),
            "runtime": "terraforge-analysis-job",
            "dependencies": ["pandas", "numpy", "scipy", "matplotlib", "rasterio"],
        },
    )
    manifest_bytes = manifest.model_dump_json(indent=2).encode()
    manifest_artifact = artifacts.put_artifact(
        str(run.id),
        "provenance_manifest.json",
        manifest_bytes,
        "application/json",
        "ProvenanceReportingAgent",
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("README.md", _bundle_readme(run))
        bundle.writestr("provenance_manifest.json", manifest_bytes)
        bundle.writestr("analysis_plan.json", plan.model_dump_json(indent=2))
        bundle.writestr("analysis.py", code)
        bundle.writestr("result_metrics.json", json.dumps(run.metrics, indent=2))
        bundle.writestr("interactive_chart_data.json", json.dumps(run.chart_data, indent=2))
        if run.vegetation:
            bundle.writestr(
                "vegetation_analysis.json",
                run.vegetation.model_dump_json(indent=2),
            )
    bundle_artifact = artifacts.put_artifact(
        str(run.id),
        "habiwatch_reproducibility_bundle.zip",
        buffer.getvalue(),
        "application/zip",
        "ProvenanceReportingAgent",
    )
    return manifest_artifact, bundle_artifact


def _bundle_readme(run: RunRecord) -> str:
    return f"""# HabiWatch reproducibility package

Run: `{run.id}`

Research question: {run.user_query}

The package records source requests, immutable SHA-256 hashes, harmonization rules,
generated code, execution metadata, structured metrics, and product artifacts.
Association metrics must not be interpreted as causal effects.
"""
