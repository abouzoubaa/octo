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
    debug: bool = True  # set False in production to enforce fail-closed secrets
    # v1 single-operator admin auth (manual onboarding)
    admin_token: str = "change-me"
    # Fernet key for at-rest encryption of OAuth tokens; empty = passthrough (dev)
    encryption_key: str = ""
    # dedicated HMAC key for audience pseudonymisation; falls back to admin_token for
    # backward compatibility. Rotating this is a data-migration event (breaks
    # erase-by-pseudonym continuity), so set it once and keep it stable.
    pseudonym_secret: str = ""

    def assert_production_secrets(self) -> list[str]:
        """Return a list of insecure-default secrets; empty when safe for prod."""
        problems = []
        if self.admin_token in ("", "change-me"):
            problems.append("CCI_ADMIN_TOKEN is the default — set a strong secret")
        if not self.encryption_key:
            problems.append("CCI_ENCRYPTION_KEY is unset — OAuth tokens stored in plaintext")
        if self.ig_webhook_verify_token in ("", "change-me-too"):
            problems.append("CCI_IG_WEBHOOK_VERIFY_TOKEN is the default")
        return problems

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

    rerank_provider: str = "none"  # none | fake | llm | cross-encoder
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    cost_per_1k_tokens_cents: float = 0.5  # blended estimate for budgeting
    # hard ceiling on a creator's monthly anonymous answer-card spend, independent of
    # plan (the answer card is free, but a fan page can't be used to drive unbounded
    # LLM cost). Over this, the public page degrades to plain search (no LLM).
    anon_answer_monthly_cap_cents: float = 2000.0  # $20/creator/month

    # --- billing ----------------------------------------------------------------
    billing_provider: str = "fake"  # fake | stripe
    stripe_api_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_ids: dict = {}  # {"creator": "price_...", "pro": "price_..."}

    # --- platform APIs ----------------------------------------------------------
    ig_app_id: str = ""
    ig_app_secret: str = ""
    ig_graph_base: str = "https://graph.instagram.com/v23.0"
    ig_webhook_verify_token: str = "change-me-too"
    oauth_state_secret: str = ""  # dedicated HMAC key for OAuth state (falls back to admin_token)
    yt_api_key: str = ""

    # --- observability & limits -------------------------------------------------
    sentry_dsn: str = ""  # error tracking (optional)
    log_json: bool = False  # structured JSON logs in production
    public_rate_limit_per_min: int = 60  # per-IP cap on public endpoints (0 = off)

    # --- retrieval / answer tuning ---------------------------------------------
    # Postgres text-search config for full-text. 'english' (default) stems English;
    # set 'simple' for multilingual deployments (language-agnostic, no stemming).
    # Applies to BOTH the generated tsv column (at schema creation) and queries.
    fts_config: str = "english"
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
