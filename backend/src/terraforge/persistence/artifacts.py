from __future__ import annotations

import hashlib
from pathlib import Path

from google.cloud import storage

from terraforge.contracts.models import AcquiredFile, ArtifactRecord
from terraforge.settings import Settings


class ArtifactStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.local_root = settings.terraforge_data_dir.resolve()
        self._client = (
            storage.Client(project=settings.gcp_project_id) if settings.cloud_enabled else None
        )

    def _safe_local_path(self, key: str) -> Path:
        path = (self.local_root / key).resolve()
        if self.local_root not in path.parents:
            raise ValueError("Artifact path escapes the configured data directory")
        return path

    async def put_raw(
        self, run_id: str, dataset_id: str, filename: str, content: bytes, content_type: str
    ) -> AcquiredFile:
        digest = hashlib.sha256(content).hexdigest()
        key = f"runs/{run_id}/raw/{dataset_id}/{digest}/{filename}"
        uri = self._put(key, content, content_type)
        return AcquiredFile(
            filename=filename,
            uri=uri,
            sha256=digest,
            size_bytes=len(content),
            content_type=content_type,
        )

    def put_artifact(
        self, run_id: str, relative_path: str, content: bytes, content_type: str, created_by: str
    ) -> ArtifactRecord:
        digest = hashlib.sha256(content).hexdigest()
        key = f"runs/{run_id}/artifacts/{digest}/{Path(relative_path).name}"
        uri = self._put(key, content, content_type)
        return ArtifactRecord(
            type=_artifact_type(relative_path),
            name=Path(relative_path).stem.replace("_", " ").title(),
            uri=uri,
            sha256=digest,
            content_type=content_type,
            size_bytes=len(content),
            created_by=created_by,
        )

    def resolve_local(self, uri: str) -> Path:
        if not uri.startswith("file://"):
            raise ValueError("Only local artifacts can be resolved directly")
        return Path(uri.removeprefix("file://"))

    def materialize(self, uri: str) -> Path:
        if uri.startswith("file://"):
            return self.resolve_local(uri)
        if not uri.startswith("gs://") or not self._client:
            raise ValueError("Artifact URI cannot be materialized by the configured store")
        bucket_name, blob_name = uri.removeprefix("gs://").split("/", 1)
        cache_path = self._safe_local_path(f"cache/{bucket_name}/{blob_name}")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if not cache_path.exists():
            self._client.bucket(bucket_name).blob(blob_name).download_to_filename(cache_path)
        return cache_path

    def read_bytes(self, uri: str) -> bytes:
        return self.materialize(uri).read_bytes()

    def _put(self, key: str, content: bytes, content_type: str) -> str:
        if self._client:
            bucket = self._client.bucket(self.settings.artifact_bucket)
            blob = bucket.blob(key)
            if not blob.exists():
                blob.upload_from_string(content, content_type=content_type, if_generation_match=0)
            return f"gs://{self.settings.artifact_bucket}/{key}"
        path = self._safe_local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(content)
        return f"file://{path.as_posix()}"


def _artifact_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    return {
        ".png": "plot",
        ".zip": "bundle",
        ".json": "manifest",
        ".py": "code",
        ".mp4": "video",
        ".mp3": "audio",
        ".tif": "raster",
        ".tiff": "raster",
        ".npz": "data",
    }.get(suffix, "data")
