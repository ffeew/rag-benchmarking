import logging
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: str = "local"
    api_bearer_token: SecretStr
    allow_mock_providers: bool = False

    log_level: str = "INFO"
    log_format: Literal["auto", "json", "console"] = "auto"

    database_url: str = "postgresql+psycopg://rag:rag@localhost:5432/rag"
    redis_url: str = "redis://localhost:6379/0"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: SecretStr = SecretStr("minioadmin")
    minio_secure: bool = False
    raw_document_bucket: str = "sec-filings"
    artifact_bucket: str = "sec-filings"

    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_chat_model: str | None = None
    openrouter_judge_model: str | None = None
    openrouter_embedding_model: str | None = None
    openrouter_rerank_model: str | None = None
    openrouter_site_url: AnyHttpUrl | None = None
    openrouter_app_name: str = "SEC Filings RAG Benchmark"
    openrouter_timeout_seconds: float = 60.0

    mistral_api_key: SecretStr | None = None
    mistral_ocr_model: str = "mistral-ocr-latest"
    mistral_base_url: str = "https://api.mistral.ai/v1"
    mistral_timeout_seconds: Annotated[float, Field(gt=0)] = 120.0

    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])
    frontend_dist_path: Path = Path("frontend/dist")
    local_corpus_path: Path = Path("sec_filings_pdf")

    semantic_candidates: Annotated[int, Field(gt=0, le=500)] = 50
    full_text_candidates: Annotated[int, Field(gt=0, le=500)] = 50
    fused_candidates: Annotated[int, Field(gt=0, le=100)] = 20
    evidence_top_k: Annotated[int, Field(gt=0, le=20)] = 8
    rerank_candidates: Annotated[int, Field(gt=0, le=100)] = 20
    reranker_enabled: bool = True
    agent_retry_budget: Annotated[int, Field(ge=0, le=3)] = 1

    embedding_dimension: Annotated[int, Field(gt=0)] = 1024
    chunk_target_tokens: Annotated[int, Field(gt=100)] = 1000
    chunk_max_tokens: Annotated[int, Field(gt=100)] = 1500
    chunk_overlap_tokens: Annotated[int, Field(ge=0)] = 120
    table_max_rows: Annotated[int, Field(gt=1)] = 60

    eval_timeout_seconds: Annotated[int, Field(gt=0)] = 1800
    query_trace_retention_days: Annotated[int, Field(gt=0)] = 30

    pricing_overrides_path: Path | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item) for item in value]
        return []

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("LOG_LEVEL must be a string")
        upper = value.strip().upper()
        if upper not in logging.getLevelNamesMapping():
            raise ValueError(
                f"LOG_LEVEL={value!r} is not a recognized level. "
                "Use one of: DEBUG, INFO, WARNING, ERROR, CRITICAL."
            )
        return upper

    @model_validator(mode="after")
    def validate_provider_secrets(self) -> Self:
        if self.allow_mock_providers:
            return self

        missing: list[str] = []
        if self.openrouter_api_key is None:
            missing.append("OPENROUTER_API_KEY")
        if self.mistral_api_key is None:
            missing.append("MISTRAL_API_KEY")
        for field_name, env_name in (
            ("openrouter_chat_model", "OPENROUTER_CHAT_MODEL"),
            ("openrouter_judge_model", "OPENROUTER_JUDGE_MODEL"),
            ("openrouter_embedding_model", "OPENROUTER_EMBEDDING_MODEL"),
            ("openrouter_rerank_model", "OPENROUTER_RERANK_MODEL"),
        ):
            if getattr(self, field_name) in (None, ""):
                missing.append(env_name)
        if missing:
            joined = ", ".join(missing)
            raise ValueError(
                "Missing required AI provider configuration. "
                f"Set {joined}, or use ALLOW_MOCK_PROVIDERS=true for offline smoke tests."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
