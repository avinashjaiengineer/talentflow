import secrets
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_name: str = "TalentFlow"
    environment: Literal["development", "production"] = "development"
    database_url: str = "sqlite:///./talentflow.db"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    auto_migrate: bool = True  # run Alembic migrations at startup (prod runs them in the entrypoint)
    log_format: Literal["text", "json"] = "text"
    enable_docs: bool | None = None  # /docs and /openapi.json; default on in development only

    # Auth
    secret_key: str = ""  # signs session cookies; required in production
    session_hours: int = 12
    cookie_secure: bool = False  # set true when served over HTTPS
    admin_email: str | None = None  # bootstrap admin, created on startup when there are no users
    admin_password: str | None = None
    admin_name: str = "Admin"

    # Background worker
    embedded_worker: bool | None = None  # run the worker inside the API process; default on in development
    worker_poll_seconds: float = 1.0
    task_max_attempts: int = 5
    task_stale_minutes: int = 15  # a running task older than this is assumed dead and re-queued

    # LLM: "auto" uses Claude when ANTHROPIC_API_KEY is set, otherwise the offline mock.
    llm_provider: Literal["auto", "anthropic", "mock"] = "auto"
    anthropic_api_key: str | None = None
    default_model: str = "claude-opus-5"
    # Per-agent overrides, e.g. MODEL_SOURCING=claude-haiku-4-5
    model_sourcing: str | None = None
    model_screening: str | None = None
    model_outreach: str | None = None
    model_scheduling: str | None = None
    model_evaluation: str | None = None
    model_intake: str | None = None
    model_job_writer: str | None = None
    llm_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"

    # Embeddings: fastembed runs locally (no key); voyage is hosted; hash is a
    # dependency-free fallback used in tests.
    embedding_provider: Literal["fastembed", "voyage", "hash"] = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    embedding_cache_dir: str | None = None  # where fastembed keeps downloaded models
    voyage_api_key: str | None = None
    # Resumes are embedded in pieces (a profile summary, then each section and job) so the whole
    # resume is searchable. ~1500 characters is about 375 tokens, inside every model's input limit.
    embedding_chunk_chars: int = 1500

    # Original resume files. "local" keeps them in STORAGE_DIR (mount a volume in Docker);
    # "s3" uses any S3-compatible bucket: AWS S3, Cloudflare R2, MinIO; "none" keeps only the text.
    storage_provider: Literal["local", "s3", "none"] = "local"
    storage_dir: str = "./data/files"
    s3_bucket: str | None = None
    s3_endpoint_url: str | None = None  # e.g. https://<account-id>.r2.cloudflarestorage.com for R2
    s3_region: str | None = None  # "auto" for R2
    s3_access_key_id: str | None = None  # leave unset to use the AWS default credential chain
    s3_secret_access_key: str | None = None

    # Scheduling
    company_name: str = "Acme Corp"
    timezone: str = "UTC"  # IANA name for interview hours, e.g. "America/New_York", "Asia/Kolkata"
    interview_duration_minutes: int = 45
    working_hours_start: int = 10
    working_hours_end: int = 17

    @model_validator(mode="after")
    def _check_timezone(self) -> "Settings":
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"TIMEZONE {self.timezone!r} is not a valid IANA zone, e.g. 'Asia/Kolkata'") from e
        return self

    @model_validator(mode="after")
    def _check_production(self) -> "Settings":
        if self.environment == "production":
            if len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must be set to at least 32 random characters in production")
            if self.database_url.startswith("sqlite"):
                raise ValueError("Use Postgres (DATABASE_URL) in production")
        elif not self.secret_key:
            # Development: an ephemeral key means sessions reset when the server restarts.
            self.secret_key = secrets.token_urlsafe(48)
        return self

    @property
    def run_embedded_worker(self) -> bool:
        return self.embedded_worker if self.embedded_worker is not None else self.environment == "development"

    @property
    def docs_enabled(self) -> bool:
        return self.enable_docs if self.enable_docs is not None else self.environment == "development"

    # ---------------------------------------------------------------- integrations
    # Email: "outbox" stores messages in TalentFlow without sending (safe default);
    # "graph" sends through Microsoft 365 (Outlook).
    email_provider: Literal["outbox", "graph"] = "outbox"
    # Calendar: "local" proposes working-hours slots with no real calendar;
    # "graph" reads Outlook free/busy and books Teams meetings.
    calendar_provider: Literal["local", "graph"] = "local"
    # Microsoft 365 app registration (client-credentials flow). MS_SENDER is the mailbox
    # that sends email and organizes interviews, e.g. recruiting@yourcompany.com.
    ms_tenant_id: str | None = None
    ms_client_id: str | None = None
    ms_client_secret: str | None = None
    ms_sender: str | None = None

    # Voice: "simulated" runs calls as a text chat inside TalentFlow; "twilio" places
    # real phone calls (needs PUBLIC_BASE_URL on https so Twilio can reach wss://).
    voice_provider: Literal["simulated", "twilio"] = "simulated"
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None
    public_base_url: str | None = None  # e.g. https://talent.example.com
    voice_language: str = "en-US"
    model_caller: str | None = None  # live calls need fast replies; e.g. claude-haiku-4-5
    call_max_turns: int = 24
    reminder_hours_before: int = 24

    # Resume intake from job portals. Naukri, LinkedIn, Indeed, and most other portals email
    # each application (with the resume attached) to the recruiter. "graph" reads those
    # emails from an Outlook mailbox; "off" disables mailbox checks. The webhook, for
    # portals and automation tools that can push applications, is enabled by its token.
    intake_provider: Literal["off", "graph"] = "off"
    intake_mailbox: str | None = None  # defaults to MS_SENDER
    intake_folder: str = "inbox"
    intake_poll_minutes: int = 15  # 0 = only when someone clicks "Check inbox now"
    intake_lookback_days: int = 7
    intake_webhook_token: str | None = None  # enables POST /api/intake/webhook
    intake_auto_screen: bool = True  # screen applicants as soon as they're matched to a job

    @property
    def intake_mailbox_address(self) -> str | None:
        return self.intake_mailbox or self.ms_sender

    def model_for(self, agent: str) -> str:
        return getattr(self, f"model_{agent}", None) or self.default_model

    @property
    def use_mock_llm(self) -> bool:
        if self.llm_provider == "mock":
            return True
        if self.llm_provider == "anthropic":
            return False
        return not self.anthropic_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
