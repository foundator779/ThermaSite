from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from google.cloud import run_v2

from terraforge.contracts.models import ExecutionResult
from terraforge.persistence.artifacts import ArtifactStore
from terraforge.settings import Settings


class AnalysisExecutor:
    def __init__(self, settings: Settings, artifacts: ArtifactStore):
        self.settings = settings
        self.artifacts = artifacts

    async def execute_local(self, run_id: UUID, code: str, harmonized_uri: str, attempt: int = 1):
        run_root = (self.settings.terraforge_data_dir / "work" / str(run_id)).resolve()
        input_dir, output_dir = run_root / "input", run_root / f"output-{attempt}"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        source = self.artifacts.resolve_local(harmonized_uri)
        shutil.copy2(source, input_dir / "harmonized_monthly.csv")
        code_path = run_root / f"analysis-{attempt}.py"
        code_path.write_text(code, encoding="utf-8")
        runtime = Path(__file__).resolve().parents[4] / "analysis_runtime" / "runner.py"
        completed = await asyncio.to_thread(
            subprocess.run,
            [
                sys.executable,
                str(runtime),
                "--code",
                str(code_path),
                "--input-dir",
                str(input_dir),
                "--output-dir",
                str(output_dir),
                "--timeout",
                "180",
            ],
            capture_output=True,
            text=True,
            timeout=200,
            check=False,
        )
        if completed.returncode != 0 or not (output_dir / "result.json").exists():
            stderr_file = output_dir / "stderr.log"
            stderr = (
                stderr_file.read_text(encoding="utf-8")
                if stderr_file.exists()
                else completed.stderr
            )
            return ExecutionResult(
                status="failed",
                attempt=attempt,
                error_class=_classify(stderr),
                stderr_excerpt=stderr[-2000:],
            ), output_dir
        payload = json.loads((output_dir / "result.json").read_text(encoding="utf-8"))
        payload["attempt"] = attempt
        result = ExecutionResult.model_validate(payload)
        return result, output_dir

    async def launch_cloud_run_job(self, run_id: UUID, code_uri: str, input_uris: list[str]) -> str:
        client = run_v2.JobsAsyncClient()
        name = client.job_path(
            self.settings.gcp_project_id, self.settings.gcp_region, self.settings.analysis_job_name
        )
        code_object = code_uri.removeprefix(f"gs://{self.settings.artifact_bucket}/")
        input_object = input_uris[0].removeprefix(f"gs://{self.settings.artifact_bucket}/")
        output_prefix = f"runs/{run_id}/job-output"
        request = run_v2.RunJobRequest(
            name=name,
            overrides=run_v2.RunJobRequest.Overrides(
                container_overrides=[
                    run_v2.RunJobRequest.Overrides.ContainerOverride(
                        args=[
                            "--bucket",
                            self.settings.artifact_bucket,
                            "--code-object",
                            code_object,
                            "--input-object",
                            input_object,
                            "--output-prefix",
                            output_prefix,
                            "--timeout",
                            "180",
                        ]
                    )
                ]
            ),
        )
        operation = await client.run_job(request=request)
        execution = await operation.result()
        return execution.name

    async def execute_cloud(
        self, run_id: UUID, code_uri: str, harmonized_uri: str, attempt: int = 1
    ):
        await self.launch_cloud_run_job(run_id, code_uri, [harmonized_uri])
        from google.cloud import storage

        output_dir = (
            self.settings.terraforge_data_dir / "work" / str(run_id) / f"cloud-output-{attempt}"
        ).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        client = storage.Client(project=self.settings.gcp_project_id)
        blobs = list(
            client.list_blobs(self.settings.artifact_bucket, prefix=f"runs/{run_id}/job-output/")
        )
        for blob in blobs:
            if blob.name.endswith("/"):
                continue
            blob.download_to_filename(output_dir / Path(blob.name).name)
        result_path = output_dir / "result.json"
        if not result_path.exists():
            stderr_path = output_dir / "stderr.log"
            stderr = (
                stderr_path.read_text(encoding="utf-8")
                if stderr_path.exists()
                else "Cloud Run Job did not produce result.json"
            )
            return ExecutionResult(
                status="failed",
                attempt=attempt,
                error_class=_classify(stderr),
                stderr_excerpt=stderr[-2000:],
            ), output_dir
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        payload["attempt"] = attempt
        return ExecutionResult.model_validate(payload), output_dir


def _classify(stderr: str) -> str:
    for name in ("KeyError", "SyntaxError", "ValueError", "ModuleNotFoundError", "TimeoutError"):
        if name in stderr:
            return name
    return "ExecutionError"
