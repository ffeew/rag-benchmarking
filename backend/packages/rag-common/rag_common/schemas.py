from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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


class DatasetRead(BaseModel):
    id: str
    name: str
    description: str | None
    default_query_settings: dict[str, Any]
    created_at: datetime
    document_count: int = 0
    active_chunk_count: int = 0
    completed_ingestion_count: int = 0


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


def default_eval_variants() -> list[RetrievalMode]:
    return ["full_agentic", "single_pass", "llm_only"]


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


class EvalCaseCreate(BaseModel):
    question: str = Field(min_length=1)
    expected_answer: str | None = None
    expected_citations: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class EvalCaseCreateRequest(BaseModel):
    dataset_id: str
    case_key: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=64)
    difficulty: str | None = Field(default=None, max_length=16)
    question: str = Field(min_length=1)
    expected_answer: str | None = None
    expected_citations: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class EvalCaseUpdate(BaseModel):
    case_key: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=64)
    difficulty: str | None = Field(default=None, max_length=16)
    question: str | None = Field(default=None, min_length=1)
    expected_answer: str | None = None
    expected_citations: list[dict[str, Any]] | None = None
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
    tags: list[str]
    created_at: datetime
    updated_at: datetime


class EvaluationCreate(BaseModel):
    dataset_id: str
    cases: list[EvalCaseCreate] | None = None
    case_ids: list[str] | None = None
    system_variants: list[RetrievalMode] = Field(default_factory=default_eval_variants)


class EvaluationCreateResponse(BaseModel):
    eval_run_id: str
    job_id: str


class EvalResultRead(BaseModel):
    id: str
    eval_case_id: str | None
    retrieval_mode: str
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
