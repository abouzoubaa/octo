"""Application configuration.

Every external dependency (database, redis, object storage, AI providers,
platform APIs) is configured here so that swapping vendors is configuration,
not code — see the portability principles in docs/IMPLEMENTATION_PLAN.md §2.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CCI_", extra="ignore")

    # --- core infrastructure -------------------------------------------------
    database_url: str = "postgresql+psycopg://cci:cci@localhost:5432/cci"
    redis_url: str = "redis://localhost:6379/0"

    # S3-compatible object storage (MinIO locally)
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "cci-media"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"

    # --- serving --------------------------------------------------------------
    public_base_url: str = "http://localhost:8000"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # v1 single-operator admin auth (manual onboarding)
    admin_token: str = "change-me"

    # --- AI providers (thin interfaces, swap by config) ------------------------
    llm_provider: str = "fake"  # fake | anthropic | openai-compatible
    llm_model: str = "claude-sonnet-4-6"
    llm_api_key: str = ""
    llm_base_url: str = ""  # for openai-compatible gateways (LiteLLM etc.)

    embedding_provider: str = "fake"  # fake | openai-compatible
    embedding_model: str = "text-embedding-3-small"
    embedding_version: str = "1"
    embedding_dims: int = 1536
    embedding_api_key: str = ""
    embedding_base_url: str = ""

    transcription_provider: str = "fake"  # fake | faster-whisper
    whisper_model: str = "small"

    ocr_provider: str = "fake"  # fake | paddleocr

    # --- platform APIs ----------------------------------------------------------
    ig_app_id: str = ""
    ig_app_secret: str = ""
    ig_graph_base: str = "https://graph.instagram.com/v23.0"
    ig_webhook_verify_token: str = "change-me-too"
    yt_api_key: str = ""

    # --- retrieval / answer tuning ---------------------------------------------
    search_top_k: int = 8
    rerank_candidates: int = 30
    answer_min_confidence: float = 0.45  # below this → "no strong answer"
    dm_min_confidence: float = 0.60  # below this → archive-link fallback
    # Compliance: Instagram private replies (one per comment, ≤7 days) and
    # automated-DM throughput cap (~200/hour/account) — queue the rest.
    dm_hourly_cap: int = 200
    dm_reply_window_days: int = 7


@lru_cache
def get_settings() -> Settings:
    return Settings()
