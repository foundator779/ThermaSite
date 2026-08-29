from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    terraforge_env: str = "local"
    terraforge_process_role: str = "all"
    terraforge_api_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    terraforge_data_dir: Path = Path(".terraforge-data")
    max_repair_attempts: int = 3
    max_workflow_attempts: int = 5
    google_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.6-flash"
    gemma_model: str = "gemma-4-26b-a4b-it"
    gemma_timeout_seconds: float = 60.0
    veo_model: str = "veo-3.1-generate-preview"
    veo_poll_interval_seconds: float = 10.0
    veo_timeout_seconds: float = 600.0
    lyria_model: str = "lyria-3-clip-preview"
    lyria_timeout_seconds: float = 180.0
    max_media_attempts: int = 3
    gcp_project_id: str = ""
    gcp_region: str = "us-central1"
    firestore_database: str = "(default)"
    artifact_bucket: str = ""
    pubsub_topic: str = "terraforge-run-events"
    workflow_topic: str = "terraforge-workflow-tasks"
    media_topic: str = "terraforge-media-tasks"
    analysis_job_name: str = "terraforge-analysis-job"
    request_timeout_seconds: float = 60.0
    allowed_frontend_origins: list[str] = Field(default_factory=list)
    otel_service_name: str = "terraforge-api"
    otel_exporter_otlp_endpoint: str = ""
    internal_invoker_email: str = ""
    monitoring_webhook_url: SecretStr | None = None
    firms_map_key: SecretStr | None = None
    sentinel_stac_url: str = "https://earth-search.aws.element84.com/v1"
    sentinel_max_cloud_cover: float = 40.0
    sentinel_analysis_enabled: bool = True
    fortyguard_api_key: SecretStr | None = None
    fortyguard_base_url: str = "https://api.fortyguard.com"
    fortyguard_request_timeout_seconds: float = 60.0
    fortyguard_poll_interval_seconds: float = 5.0
    fortyguard_poll_timeout_seconds: float = 600.0

    @property
    def cors_origins(self) -> list[str]:
        return self.allowed_frontend_origins or [
            origin.strip() for origin in self.terraforge_api_origins.split(",") if origin.strip()
        ]

    @property
    def cloud_enabled(self) -> bool:
        return self.terraforge_env in {"staging", "production"} and bool(self.gcp_project_id)

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.google_api_key and self.google_api_key.get_secret_value())

    @property
    def veo_enabled(self) -> bool:
        return self.gemini_enabled and self.veo_model.startswith("veo-")

    @property
    def gemma_enabled(self) -> bool:
        return self.gemini_enabled and self.gemma_model.startswith("gemma-")

    @property
    def lyria_enabled(self) -> bool:
        return self.gemini_enabled and self.lyria_model.startswith("lyria-")

    @property
    def fortyguard_enabled(self) -> bool:
        return bool(self.fortyguard_api_key and self.fortyguard_api_key.get_secret_value())

@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.terraforge_data_dir.mkdir(parents=True, exist_ok=True)
    return settings
