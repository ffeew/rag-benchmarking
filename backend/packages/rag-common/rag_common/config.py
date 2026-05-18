import logging
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from rag_common.constants import EMBEDDING_VECTOR_DIMENSION


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    api_bearer_token: SecretStr
    allow_mock_providers: bool = False

    log_level: str = "INFO"
    log_format: Literal["auto", "json", "console"] = "auto"

    database_url: str = "postgresql+psycopg://rag:rag@localhost:5432/rag"
    redis_url: str = "redis://localhost:6379/0"

    minio_endpoint: str = "localhost:9000"
    # Host used when minting presigned URLs handed to browsers. The default
    # minio_endpoint above is a docker-internal hostname inside compose, which
    # the browser can't resolve; set this to the host-reachable address.
    minio_public_endpoint: str | None = None
    minio_access_key: str = "minioadmin"
    minio_secret_key: SecretStr = SecretStr("minioadmin")
    minio_secure: bool = False
    raw_document_bucket: str = "sec-filings"
    artifact_bucket: str = "sec-filings"

    openrouter_api_key: SecretStr | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_embedding_model: str | None = None
    openrouter_rerank_model: str | None = None
    # Generator fallback model used when the primary Z.AI generator refuses a
    # prompt with the PRC content-policy classifier (HTTP 400, code 1301).
    # Optional: leave unset to keep the legacy extractive fallback only. When
    # set (e.g. ``anthropic/claude-sonnet-4-6``), refused prompts are retried
    # against OpenRouter so the eval still gets a real answer for content
    # Z.AI declines to generate against.
    openrouter_chat_model: str | None = None
    openrouter_site_url: AnyHttpUrl | None = None
    openrouter_app_name: str = "RAG Benchmark"
    openrouter_timeout_seconds: float = 60.0

    zai_api_key: SecretStr | None = None
    zai_base_url: str = "https://api.z.ai/api/paas/v4"
    zai_chat_model: str | None = None
    zai_judge_model: str | None = None
    zai_timeout_seconds: Annotated[float, Field(gt=0)] = 60.0

    mistral_api_key: SecretStr | None = None
    mistral_ocr_model: str = "mistral-ocr-latest"
    mistral_base_url: str = "https://api.mistral.ai/v1"
    mistral_timeout_seconds: Annotated[float, Field(gt=0)] = 120.0

    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])
    frontend_dist_path: Path = Path("frontend/dist")
    local_corpus_path: Path = Path("sec_filings_pdf")

    # ge=0 (not gt=0) so ablations can set a channel to zero to disable it:
    # semantic_candidates=0 -> lexical-only; full_text_candidates=0 -> semantic-only.
    semantic_candidates: Annotated[int, Field(ge=0, le=500)] = 50
    full_text_candidates: Annotated[int, Field(ge=0, le=500)] = 50
    fused_candidates: Annotated[int, Field(gt=0, le=100)] = 20
    evidence_top_k: Annotated[int, Field(gt=0, le=20)] = 8
    rerank_candidates: Annotated[int, Field(gt=0, le=100)] = 20
    reranker_enabled: bool = True
    hyde_enabled: bool = True
    retrieval_agent_tool_call_budget: Annotated[int, Field(ge=1, le=8)] = 4
    # Query decomposition for single_pass: when on, an LLM call breaks multi-part
    # questions into subquestions and single_pass fans out one hybrid_retrieve per
    # subquestion (RRF-fused). Questions the LLM judges atomic return an empty list
    # and fall through to the existing single hybrid_retrieve, so the LLM cost is
    # paid but the retrieval cost stays flat for simple fact lookups.
    query_decomposition_enabled: bool = True
    decomposition_max_subquestions: Annotated[int, Field(ge=1, le=6)] = 4
    # When true, OpenRouter chat + pydantic-ai agent + RAGAS judge calls are pinned to
    # temperature=0 for evaluation determinism. Set to false only for debug runs that
    # intentionally re-enable sampling.
    eval_temperature_zero: bool = True
    # Explicit upper bound on completion tokens for every chat call (HyDE,
    # planner, retrieval agent, verifier, generator, RAGAS judge, llm_only
    # ablation). Set explicitly because some providers reject preflight when
    # ``len(prompt) + provider_default_max_tokens > context_window`` — the
    # symptom is a ``Model token limit (provider default) exceeded before any
    # response was generated`` error on long-context cases.
    generation_max_tokens: Annotated[int, Field(ge=512, le=32768)] = 8192

    embedding_dimension: Annotated[int, Field(gt=0)] = 1024
    chunk_target_tokens: Annotated[int, Field(gt=100)] = 1000
    chunk_max_tokens: Annotated[int, Field(gt=100)] = 1500
    chunk_overlap_tokens: Annotated[int, Field(ge=0)] = 120
    table_max_rows: Annotated[int, Field(gt=1)] = 60

    # Multi-criteria pass thresholds for the per-case ``passed`` flag and the
    # variant-level ``pass_rate`` aggregate. A case is considered passed when
    # both gates are met:
    #   answer_accuracy >= eval_pass_answer_accuracy_threshold
    #   citation_validity >= eval_pass_citation_validity_threshold
    # Recall@5 is reported as a per-variant diagnostic but is intentionally
    # not part of the gate: a correctly-answered case with chunk-grounded
    # citations should pass even when the retriever surfaced different valid
    # pages than the annotator picked.
    eval_pass_answer_accuracy_threshold: Annotated[float, Field(ge=0.0, le=1.0)] = 1.0
    eval_pass_citation_validity_threshold: Annotated[float, Field(ge=0.0, le=1.0)] = 0.5
    # Persist a partial run-level aggregate every N completed cases so a
    # worker reap doesn't drop all metrics on the floor. Aggregation is cheap
    # relative to a single eval case, so a low N is fine.
    eval_partial_aggregate_every: Annotated[int, Field(gt=0)] = 5
    # Whether to run the RAGAS judge phase after per-case scoring. RAGAS is
    # informational-only (faithfulness / answer-relevancy / context-* metrics
    # not under FDR control) and adds substantial latency — one LLM call per
    # metric per case, sequential, on the slow judge model. Set to false for
    # iteration / smoke tests to skip the trailing 4+ minute RAGAS phase.
    eval_run_ragas: bool = True
    # Maximum number of evaluations that may run simultaneously inside one API
    # process. The launcher gates thread creation with a semaphore sized from
    # this value. The default of 1 matches the previous Celery worker's
    # ``worker_prefetch_multiplier=1``; bump it to allow concurrent evals if
    # the host has the CPU + provider quota headroom.
    eval_max_inflight: Annotated[int, Field(ge=1, le=8)] = 1

    # Sweeper thresholds. ``POST /v1/jobs/sweep`` marks a RUNNING job failed
    # when no heartbeat has landed for ``running_heartbeat_seconds``. The
    # default is generous so a legitimately slow eval case — e.g. one stalled
    # on provider rate-limit retries — cannot be reaped mid-flight.
    running_heartbeat_seconds: Annotated[int, Field(gt=0)] = 2700
    queued_grace_seconds: Annotated[int, Field(gt=0)] = 600

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
                f"LOG_LEVEL={value!r} is not a recognized level. Use one of: DEBUG, INFO, WARNING, ERROR, CRITICAL."
            )
        return upper

    @model_validator(mode="after")
    def validate_provider_secrets(self) -> Self:
        if self.allow_mock_providers:
            return self

        missing: list[str] = []
        if self.openrouter_api_key is None:
            missing.append("OPENROUTER_API_KEY")
        if self.zai_api_key is None:
            missing.append("ZAI_API_KEY")
        if self.mistral_api_key is None:
            missing.append("MISTRAL_API_KEY")
        for field_name, env_name in (
            ("zai_chat_model", "ZAI_CHAT_MODEL"),
            ("zai_judge_model", "ZAI_JUDGE_MODEL"),
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

    @model_validator(mode="after")
    def validate_embedding_dimension_matches_schema(self) -> Self:
        # The pgvector ``chunks.embedding_vector`` column is declared ``vector(N)``
        # with N == EMBEDDING_VECTOR_DIMENSION, and the HNSW cosine index
        # ``ix_chunks_embedding_vector_hnsw`` is built on that same N. A mismatch
        # wouldn't be caught until the per-batch UPDATE in the embedding stage of
        # an ingestion run, by which point parsing, chunking, and (partial)
        # embedding work has already been done and rolled back. Reject it at
        # Settings load so the failure mode is "service refuses to start" instead
        # of "every ingestion silently rolls back".
        if self.embedding_dimension != EMBEDDING_VECTOR_DIMENSION:
            raise ValueError(
                f"EMBEDDING_DIMENSION={self.embedding_dimension} does not match the "
                f"pgvector schema (EMBEDDING_VECTOR_DIMENSION={EMBEDDING_VECTOR_DIMENSION}). "
                "Changing the embedding dimension requires a new migration that alters "
                "chunks.embedding_vector and rebuilds ix_chunks_embedding_vector_hnsw."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
