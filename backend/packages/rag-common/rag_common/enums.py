"""Centralized ``StrEnum`` classes for the closed string-valued types used
throughout the codebase.

Every enum value is identical to the string it replaces, so wire payloads
(JSON, DB columns) are byte-equivalent and ``JobStatus.QUEUED == "queued"``
holds. Consumers may compare to either the enum member or the bare string.
"""

from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    COMPLETED_WITH_ERRORS = "completed_with_errors"


JOB_TERMINAL_STATUSES = frozenset(
    {
        JobStatus.COMPLETED,
        JobStatus.SKIPPED,
        JobStatus.CANCELLED,
        JobStatus.COMPLETED_WITH_ERRORS,
        JobStatus.FAILED,
    }
)


class IngestionRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


INGESTION_RUN_TERMINAL_STATUSES = frozenset(
    {
        IngestionRunStatus.COMPLETED,
        IngestionRunStatus.FAILED,
        IngestionRunStatus.SKIPPED,
    }
)


class JobType(StrEnum):
    INGESTION = "ingestion"
    EVALUATION = "evaluation"


class Provider(StrEnum):
    """LLM / embedding / OCR provider identifiers used in usage tracking."""

    ZAI = "zai"
    OPENROUTER = "openrouter"
    MISTRAL_OCR = "mistral-ocr"
    MOCK_ZAI = "mock-zai"
    MOCK_OPENROUTER = "mock-openrouter"


class ParserType(StrEnum):
    """PDF parser tiers in the ingestion fallback chain."""

    MISTRAL_OCR = "mistral-ocr"
    DOCLING = "docling"
    PYPDF_LOCAL = "pypdf-local"


class ChunkerType(StrEnum):
    CHONKIE = "chonkie"


class ChunkType(StrEnum):
    TABLE = "table"
    NARRATIVE = "narrative"
    MIXED = "mixed"


class RetrievalMode(StrEnum):
    FULL_AGENTIC = "full_agentic"
    SINGLE_PASS = "single_pass"  # noqa: S105 - not a password
    LLM_ONLY = "llm_only"


class QueryType(StrEnum):
    FACT_LOOKUP = "fact_lookup"
    TABLE_LOOKUP = "table_lookup"
    COMPARISON = "comparison"
    TREND = "trend"
    THEMATIC_SYNTHESIS = "thematic_synthesis"
    LATEST_FILING = "latest_filing"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class VerificationStatus(StrEnum):
    DRAFT = "draft"
    VERIFIED = "verified"
    DEPRECATED = "deprecated"


class BenchmarkProfile(StrEnum):
    SCIENTIFIC = "scientific"
    DIAGNOSTIC = "diagnostic"


class ExpectedAnswerType(StrEnum):
    NUMERIC = "numeric"
    TEXT = "text"
    MULTI_PART = "multi_part"
    INSUFFICIENT = "insufficient"
    REFUSAL = "refusal"


class PipelineRole(StrEnum):
    """Roles tracked in token-usage accounting (``rag_common.usage``)."""

    PLANNER = "planner"
    VERIFIER = "verifier"
    GENERATOR = "generator"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    JUDGE = "judge"


class RagasMetric(StrEnum):
    FAITHFULNESS = "faithfulness"
    CONTEXT_PRECISION = "context_precision"
    ANSWER_RELEVANCY = "answer_relevancy"
    CONTEXT_RECALL = "context_recall"
