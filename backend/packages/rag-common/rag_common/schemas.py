from datetime import date, datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rag_common.usage import RoleUsage


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    default_query_settings: dict[str, Any] = Field(default_factory=dict)
    domain_label: str | None = Field(default=None, max_length=512)
    entity_label: str | None = Field(default=None, max_length=64)
    valid_forms: list[str] | None = None
    metric_terms: list[str] | None = None
    hyde_style_hint: str | None = None
    citation_label_template: str | None = Field(default=None, max_length=256)


class DatasetRead(BaseModel):
    id: str
    name: str
    description: str | None
    default_query_settings: dict[str, Any]
    domain_label: str | None = None
    entity_label: str | None = None
    valid_forms: list[str] | None = None
    metric_terms: list[str] | None = None
    hyde_style_hint: str | None = None
    citation_label_template: str | None = None
    created_at: datetime
    document_count: int = 0
    active_chunk_count: int = 0
    completed_ingestion_count: int = 0


class DatasetUpdate(BaseModel):
    """Partial update for an existing dataset.

    All fields are optional; only those supplied by the caller are written. ``None`` is
    a valid value (e.g. ``hyde_style_hint=None`` clears the override and re-enables the
    SEC default at resolution time). To distinguish "unset" from "null", we use
    ``model_dump(exclude_unset=True)`` in the route.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    default_query_settings: dict[str, Any] | None = None
    domain_label: str | None = Field(default=None, max_length=512)
    entity_label: str | None = Field(default=None, max_length=64)
    valid_forms: list[str] | None = None
    metric_terms: list[str] | None = None
    hyde_style_hint: str | None = None
    citation_label_template: str | None = Field(default=None, max_length=256)


class DocumentRead(BaseModel):
    id: str
    dataset_id: str
    ticker: str
    company_name: str | None
    form_type: str
    filing_date: date | None
    report_period: date | None
    fiscal_year: int | None
    fiscal_quarter: int | None
    checksum: str
    minio_bucket: str
    minio_key: str
    minio_version_id: str | None
    byte_size: int
    active_ingestion_run_id: str | None
    ingestion_status: str | None = None
    created_at: datetime


class DocumentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str | None = None
    company_name: str | None = None
    form_type: str | None = None
    filing_date: date | None = None
    report_period: date | None = None
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None


class ParsedPageRead(BaseModel):
    page_number: int
    text: str
    text_char_count: int
    table_count: int


class DocumentExtracted(BaseModel):
    document_id: str
    ingestion_run_id: str
    pages: list[ParsedPageRead]


class RegisterLocalCorpusRequest(BaseModel):
    dataset_name: str = "sec-filings"
    description: str | None = "SEC filing PDFs registered from the local corpus."
    path: str | None = None
    domain_label: str | None = None
    entity_label: str | None = None
    valid_forms: list[str] | None = None
    metric_terms: list[str] | None = None
    hyde_style_hint: str | None = None
    citation_label_template: str | None = None


class RegisterDocumentsResponse(BaseModel):
    dataset: DatasetRead
    documents: list[DocumentRead]
    created_count: int
    reused_count: int
    job_ids: list[str] = Field(default_factory=list)
    queued_document_ids: list[str] = Field(default_factory=list)
    skipped_document_ids: list[str] = Field(default_factory=list)


class DocumentUploadResponse(BaseModel):
    documents: list[DocumentRead]
    job_ids: list[str] = Field(default_factory=list)
    queued_document_ids: list[str] = Field(default_factory=list)
    skipped_document_ids: list[str] = Field(default_factory=list)


class IngestionCreate(BaseModel):
    document_ids: list[str] | None = None
    minio_prefix: str | None = None
    force: bool = False


class IngestionCreateResponse(BaseModel):
    job_ids: list[str]
    queued_document_ids: list[str]
    skipped_document_ids: list[str]


class JobRead(BaseModel):
    id: str
    job_type: str
    status: str
    progress: int
    current_step: str | None
    dataset_id: str | None
    document_id: str | None
    eval_run_id: str | None
    error: str | None
    metadata: dict[str, Any]
    started_at: datetime | None
    completed_at: datetime | None
    last_heartbeat_at: datetime | None
    retry_count: int
    created_at: datetime


class JobSweepResponse(BaseModel):
    redispatched: int
    exhausted: int
    reaped: int


class QueryFilters(BaseModel):
    ticker: list[str] | None = None
    form_type: list[str] | None = None
    filing_date_start: date | None = None
    filing_date_end: date | None = None
    report_period_start: date | None = None
    report_period_end: date | None = None
    document_ids: list[str] | None = None


RetrievalMode = Literal["full_agentic", "single_pass", "llm_only"]
BenchmarkProfile = Literal["scientific", "diagnostic"]
VerificationStatus = Literal["draft", "verified", "deprecated"]
ExpectedAnswerType = Literal["numeric", "text", "multi_part", "insufficient", "refusal"]


def default_eval_variants() -> list[RetrievalMode]:
    return ["full_agentic", "single_pass", "llm_only"]


class RetrievalOverrides(BaseModel):
    """Per-variant retrieval-config overrides applied as a Settings.model_copy(update=...).

    Each field is optional; ``None`` means "inherit from the resolved Settings".
    Zero-valued candidate counts intentionally allowed: ``semantic_candidates=0``
    disables the vector channel (lexical-only), ``full_text_candidates=0``
    disables the FTS channel (semantic-only).
    """

    model_config = ConfigDict(extra="forbid")

    hyde_enabled: bool | None = None
    reranker_enabled: bool | None = None
    semantic_candidates: int | None = Field(default=None, ge=0, le=500)
    full_text_candidates: int | None = Field(default=None, ge=0, le=500)
    fused_candidates: int | None = Field(default=None, gt=0, le=100)
    rerank_candidates: int | None = Field(default=None, gt=0, le=100)
    evidence_top_k: int | None = Field(default=None, gt=0, le=20)
    retrieval_agent_tool_call_budget: int | None = Field(default=None, ge=1, le=8)


class RetrievalVariantSpec(BaseModel):
    """A named retrieval configuration used by an eval run.

    The ``name`` is the join key for paired statistical analysis and persists on
    ``EvalResult.variant_name``. The ``retrieval_mode`` picks the underlying
    pipeline branch; ``overrides`` knock individual components on/off.
    """

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    retrieval_mode: RetrievalMode
    overrides: RetrievalOverrides = Field(default_factory=RetrievalOverrides)


class QueryRequest(BaseModel):
    dataset_id: str
    question: str = Field(min_length=1)
    filters: QueryFilters = Field(default_factory=QueryFilters)
    top_k: int | None = Field(default=None, ge=1, le=20)
    include_trace: bool = True
    retrieval_mode: RetrievalMode = "full_agentic"
    include_full_retrieval: bool = False


class CitationRead(BaseModel):
    document_id: str
    ticker: str
    form_type: str
    filing_date: date | None
    report_period: date | None
    page_number: int
    chunk_id: str
    minio_bucket: str
    minio_key: str
    minio_version_id: str | None
    snippet: str
    label: str


class EvidenceRead(BaseModel):
    chunk_id: str
    document_id: str
    ticker: str
    form_type: str
    filing_date: date | None
    page_start: int
    page_end: int
    contains_table: bool
    score: float
    snippet: str


class RetrievedChunkRef(BaseModel):
    """Lightweight reference to a retrieved chunk, used for retriever metrics."""

    chunk_id: str
    document_id: str
    ticker: str
    form_type: str
    page_start: int
    page_end: int
    rank: int


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationRead]
    evidence: list[EvidenceRead]
    trace_id: str
    confidence: float
    insufficiency_reason: str | None = None
    usage_summary: RoleUsage | None = None
    cost_estimate_usd: float | None = None
    generator_metadata: dict[str, Any] | None = None
    full_retrieval: list[RetrievedChunkRef] | None = None


class TraceRead(BaseModel):
    id: str
    dataset_id: str
    user_question: str
    retrieval_mode: str
    plan: dict[str, Any]
    retrieval_calls: list[dict[str, Any]]
    verifier_result: dict[str, Any]
    model_metadata: dict[str, Any]
    final_answer_metadata: dict[str, Any]
    timings: dict[str, Any]
    citations: list[CitationRead]
    created_at: datetime


class ExpectedCitation(BaseModel):
    """Expected-citation hint used in eval cases for retriever/citation scoring."""

    ticker: str | None = None
    form_type: str | None = None
    page_number: int | None = None
    document_id: str | None = None
    evidence_text: str | None = None


class ExpectedValue(BaseModel):
    """Structured gold value for deterministic answer scoring."""

    label: str
    value_numeric: float | None = None
    value_text: str | None = None
    unit: str | None = None
    tolerance_abs: float | None = Field(default=None, ge=0)
    tolerance_pct: float | None = Field(default=None, ge=0)


class ExpectedAnswerSpec(BaseModel):
    """Structured answer gold data. Draft cases may leave every field empty."""

    answer_type: ExpectedAnswerType | None = None
    expected_values: list[ExpectedValue] = Field(default_factory=list)
    required_claims: list[str] = Field(default_factory=list)
    required_reason_keywords: list[str] = Field(default_factory=list)


class ExpectedEvidenceSpec(BaseModel):
    """Verified source evidence used for retrieval, citation, parser, and table scoring."""

    ticker: str | None = None
    form_type: str | None = None
    document_id: str | None = None
    filing_date: date | None = None
    report_period: date | None = None
    page_number: int | None = None
    evidence_text: str | None = None
    evidence_hash: str | None = None
    table_key: str | None = None


class EvalCaseCreate(BaseModel):
    question: str = Field(min_length=1)
    expected_answer: str | None = None
    expected_citations: list[dict[str, Any]] = Field(default_factory=list)
    expected_answer_spec: ExpectedAnswerSpec = Field(default_factory=ExpectedAnswerSpec)
    expected_evidence: list[ExpectedEvidenceSpec] = Field(default_factory=list)
    verification_status: VerificationStatus = "draft"
    verified_by: str | None = Field(default=None, max_length=128)
    verified_at: datetime | None = None
    gold_version: str = Field(default="v1", max_length=32)
    tags: list[str] = Field(default_factory=list)


class EvalCaseCreateRequest(BaseModel):
    dataset_id: str
    case_key: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=64)
    difficulty: str | None = Field(default=None, max_length=16)
    question: str = Field(min_length=1)
    expected_answer: str | None = None
    expected_citations: list[dict[str, Any]] = Field(default_factory=list)
    expected_answer_spec: ExpectedAnswerSpec = Field(default_factory=ExpectedAnswerSpec)
    expected_evidence: list[ExpectedEvidenceSpec] = Field(default_factory=list)
    verification_status: VerificationStatus = "draft"
    verified_by: str | None = Field(default=None, max_length=128)
    verified_at: datetime | None = None
    gold_version: str = Field(default="v1", max_length=32)
    tags: list[str] = Field(default_factory=list)


class EvalCaseUpdate(BaseModel):
    case_key: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=64)
    difficulty: str | None = Field(default=None, max_length=16)
    question: str | None = Field(default=None, min_length=1)
    expected_answer: str | None = None
    expected_citations: list[dict[str, Any]] | None = None
    expected_answer_spec: ExpectedAnswerSpec | None = None
    expected_evidence: list[ExpectedEvidenceSpec] | None = None
    verification_status: VerificationStatus | None = None
    verified_by: str | None = Field(default=None, max_length=128)
    verified_at: datetime | None = None
    gold_version: str | None = Field(default=None, max_length=32)
    tags: list[str] | None = None


class EvalCaseRead(BaseModel):
    id: str
    dataset_id: str
    case_key: str | None
    category: str | None
    difficulty: str | None
    question: str
    expected_answer: str | None
    expected_citations: list[dict[str, Any]]
    expected_answer_spec: ExpectedAnswerSpec
    expected_evidence: list[ExpectedEvidenceSpec]
    verification_status: str
    verified_by: str | None
    verified_at: datetime | None
    gold_version: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime


class EvaluationCreate(BaseModel):
    dataset_id: str
    cases: list[EvalCaseCreate] | None = None
    case_ids: list[str] | None = None
    system_variants: list[RetrievalMode] = Field(default_factory=default_eval_variants)
    variants: list[RetrievalVariantSpec] | None = None
    benchmark_profile: BenchmarkProfile = "scientific"

    @model_validator(mode="after")
    def coerce_variants(self) -> Self:
        explicit = self.variants is not None
        defaults_used = self.system_variants == default_eval_variants()
        if explicit and not defaults_used:
            raise ValueError(
                "Specify either `system_variants` or `variants`, not both. "
                "`variants` supersedes `system_variants` when set; pass only one."
            )
        if not explicit:
            self.variants = [
                RetrievalVariantSpec(name=mode, retrieval_mode=mode) for mode in self.system_variants
            ]
        names = [v.name for v in self.variants or []]
        if len(set(names)) != len(names):
            raise ValueError(f"variant names must be unique; got {names}")
        return self


class EvaluationCreateResponse(BaseModel):
    eval_run_id: str
    job_id: str


class EvalResultRead(BaseModel):
    id: str
    eval_case_id: str | None
    retrieval_mode: str
    variant_name: str | None = None
    answer: str | None
    trace_id: str | None
    metrics: dict[str, Any]
    error: str | None
    usage: dict[str, Any] | None = None
    cost_estimate: dict[str, Any] | None = None
    latency_ms: int | None = None


class EvalRunRead(BaseModel):
    id: str
    dataset_id: str
    job_id: str | None
    status: str
    run_config: dict[str, Any]
    system_variant: str
    model_metadata: dict[str, Any]
    metrics: dict[str, Any]
    errors: list[dict[str, Any]]
    results: list[EvalResultRead]
    created_at: datetime


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    database: bool
    minio: bool
    redis: bool
    providers: dict[str, Any]
