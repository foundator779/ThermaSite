from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from safety import UnsafeCodeError, validate_code


def safe_child(parent: Path, child: Path) -> Path:
    resolved_parent = parent.resolve()
    resolved_child = child.resolve()
    if (
        resolved_child != resolved_parent
        and resolved_parent not in resolved_child.parents
    ):
        raise ValueError(
            f"Path {resolved_child} escapes declared boundary {resolved_parent}"
        )
    return resolved_child


def run(code: Path, input_dir: Path, output_dir: Path, timeout: int) -> int:
    source = code.read_text(encoding="utf-8")
    validate_code(source)
    input_dir = input_dir.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    child_env = {
        "PATH": str(Path(sys.executable).parent),
        "PYTHONPATH": "",
        "MPLCONFIGDIR": str(output_dir / ".matplotlib"),
        "PYTHONNOUSERSITE": "1",
    }
    for name in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG"):
        if name in os.environ:
            child_env[name] = os.environ[name]
    completed = subprocess.run(
        [
            sys.executable,
            str(code.resolve()),
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
        ],
        cwd=str(output_dir),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=child_env,
    )
    (output_dir / "stdout.log").write_text(completed.stdout[-20_000:], encoding="utf-8")
    (output_dir / "stderr.log").write_text(completed.stderr[-20_000:], encoding="utf-8")
    manifest = {
        "return_code": completed.returncode,
        "timeout_seconds": timeout,
        "network_access": False,
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
    }
    (output_dir / "execution_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return completed.returncode


def run_cloud(
    bucket_name: str,
    code_object: str,
    input_object: str,
    output_prefix: str,
    timeout: int,
) -> int:
    from google.cloud import storage

    workspace = Path("/workspace").resolve()
    input_dir, output_dir = workspace / "input", workspace / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    code = safe_child(workspace, workspace / "analysis.py")
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    bucket.blob(code_object).download_to_filename(code)
    bucket.blob(input_object).download_to_filename(input_dir / "harmonized_monthly.csv")
    return_code = run(code, input_dir, output_dir, timeout)
    for output in output_dir.iterdir():
        if output.is_file():
            bucket.blob(
                f"{output_prefix.rstrip('/')}/{output.name}"
            ).upload_from_filename(output)
    return return_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--code")
    parser.add_argument("--input-dir")
    parser.add_argument("--output-dir")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--bucket")
    parser.add_argument("--code-object")
    parser.add_argument("--input-object")
    parser.add_argument("--output-prefix")
    args = parser.parse_args()
    try:
        if args.bucket:
            raise SystemExit(
                run_cloud(
                    args.bucket,
                    args.code_object,
                    args.input_object,
                    args.output_prefix,
                    args.timeout,
                )
            )
        if not args.code or not args.input_dir or not args.output_dir:
            parser.error("local mode requires --code, --input-dir, and --output-dir")
        raise SystemExit(
            run(
                Path(args.code),
                Path(args.input_dir),
                Path(args.output_dir),
                args.timeout,
            )
        )
    except (UnsafeCodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(64)
