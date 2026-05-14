import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from rag_benchmarking.api.schemas import (
    CitationRead,
    EvidenceRead,
    QueryRequest,
    QueryResponse,
)
from rag_benchmarking.core.config import Settings, get_settings
from rag_benchmarking.db import models
from rag_benchmarking.retrieval.generation import (
    citation_label,
    generate_answer,
    snippet,
)
from rag_benchmarking.retrieval.hybrid import RetrievedChunk, hybrid_retrieve
from rag_benchmarking.retrieval.planning import plan_query
from rag_benchmarking.retrieval.verification import verify_evidence


def to_evidence_read(item: RetrievedChunk) -> EvidenceRead:
    return EvidenceRead(
        chunk_id=item.chunk.id,
        document_id=item.document.id,
        ticker=item.document.ticker,
        form_type=item.document.form_type,
        filing_date=item.document.filing_date,
        page_start=item.chunk.page_start,
        page_end=item.chunk.page_end,
        contains_table=item.chunk.contains_table,
        score=item.rerank_score if item.rerank_score is not None else item.score,
        snippet=snippet(item.chunk.text),
    )


def to_citation_read(item: RetrievedChunk) -> CitationRead:
    return CitationRead(
        document_id=item.document.id,
        ticker=item.document.ticker,
        form_type=item.document.form_type,
        filing_date=item.document.filing_date,
        report_period=item.document.report_period,
        page_number=item.chunk.page_start,
        chunk_id=item.chunk.id,
        minio_bucket=item.document.minio_bucket,
        minio_key=item.document.minio_key,
        minio_version_id=item.document.minio_version_id,
        snippet=snippet(item.chunk.text),
        label=citation_label(item),
    )


def persist_trace(
    session: Session,
    *,
    request: QueryRequest,
    plan: dict[str, Any],
    retrieval_calls: list[dict[str, Any]],
    verifier_result: dict[str, Any],
    model_metadata: dict[str, Any],
    final_answer_metadata: dict[str, Any],
    timings: dict[str, Any],
    citations: list[RetrievedChunk],
) -> models.QueryTrace:
    trace = models.QueryTrace(
        dataset_id=request.dataset_id,
        user_question=request.question,
        retrieval_mode=request.retrieval_mode,
        plan=plan,
        retrieval_calls=retrieval_calls,
        verifier_result=verifier_result,
        model_metadata=model_metadata,
        final_answer_metadata=final_answer_metadata,
        timings=timings,
    )
    session.add(trace)
    session.flush()
    for item in citations:
        session.add(
            models.Citation(
                trace_id=trace.id,
                chunk_id=item.chunk.id,
                document_id=item.document.id,
                page_number=item.chunk.page_start,
                evidence_text=snippet(item.chunk.text),
                citation_label=citation_label(item),
                minio_bucket=item.document.minio_bucket,
                minio_key=item.document.minio_key,
                minio_version_id=item.document.minio_version_id,
            )
        )
    session.flush()
    return trace


def run_query(
    session: Session,
    *,
    request: QueryRequest,
    settings: Settings | None = None,
) -> QueryResponse:
    resolved = settings or get_settings()
    start = time.perf_counter()
    dataset = session.get(models.Dataset, request.dataset_id)
    if dataset is None:
        raise ValueError(f"Dataset {request.dataset_id} was not found")
    plan, planner_meta = plan_query(
        session,
        dataset_id=request.dataset_id,
        question=request.question,
        filters=request.filters,
        settings=resolved,
    )
    top_k = request.top_k or resolved.evidence_top_k
    retrieval_calls: list[dict[str, Any]] = []
    retrieved: list[RetrievedChunk] = []
    verifier_result: dict[str, Any] = {
        "supported_chunk_ids": [],
        "missing_subclaims": [],
        "contradictions": [],
        "retry_query": None,
        "confidence": 0.0,
        "reasoning": None,
    }
    verifier_meta: dict[str, Any] = {"agent_used": False, "model": None, "error": None}

    if request.retrieval_mode != "llm_only":
        retrieved, retrieval_trace = hybrid_retrieve(
            session,
            dataset_id=request.dataset_id,
            question=request.question,
            filters=request.filters,
            plan=plan,
            top_k=top_k,
            settings=resolved,
        )
        retrieval_calls.append({"query": request.question, **retrieval_trace})
        verification, verifier_meta = verify_evidence(request.question, retrieved, settings=resolved)
        verifier_result = verification.as_dict()
        if (
            request.retrieval_mode == "full_agentic"
            and not verification.supported_chunk_ids
            and verification.retry_query
            and resolved.agent_retry_budget > 0
        ):
            retry_retrieved, retry_trace = hybrid_retrieve(
                session,
                dataset_id=request.dataset_id,
                question=verification.retry_query,
                filters=request.filters,
                plan=plan,
                top_k=top_k,
                settings=resolved,
            )
            retrieval_calls.append({"query": verification.retry_query, "retry": True, **retry_trace})
            retrieved = retry_retrieved
            verification, verifier_meta = verify_evidence(request.question, retrieved, settings=resolved)
            verifier_result = verification.as_dict()

    raw_supported_ids = verifier_result.get("supported_chunk_ids") or []
    supported_ids = set(raw_supported_ids if isinstance(raw_supported_ids, list) else [])
    verified_evidence = [item for item in retrieved if not supported_ids or item.chunk.id in supported_ids][:top_k]
    answer = generate_answer(
        question=request.question,
        evidence=verified_evidence,
        retrieval_mode=request.retrieval_mode,
        plan=plan,
        settings=resolved,
    )
    timings = {"total_seconds": round(time.perf_counter() - start, 3)}
    generator_metadata = answer.metadata or {}
    model_metadata = {
        "chat_model": resolved.openrouter_chat_model,
        "embedding_model": resolved.openrouter_embedding_model,
        "rerank_model": resolved.openrouter_rerank_model,
        "allow_mock_providers": resolved.allow_mock_providers,
        "agent_planner_used": bool(planner_meta.get("agent_used")),
        "agent_verifier_used": bool(verifier_meta.get("agent_used")),
        "agent_generator_used": generator_metadata.get("generator") == "pydantic-ai-agent",
        "citation_validation": generator_metadata.get("citation_validation"),
        "citation_repair_used": generator_metadata.get("repair_used", False),
        "chunker": "chonkie",
        "planner_error": planner_meta.get("error"),
        "verifier_error": verifier_meta.get("error"),
    }
    trace = persist_trace(
        session,
        request=request,
        plan=plan.as_dict(),
        retrieval_calls=retrieval_calls,
        verifier_result=verifier_result,
        model_metadata=model_metadata,
        final_answer_metadata=answer.metadata,
        timings=timings,
        citations=verified_evidence,
    )
    citations = [to_citation_read(item) for item in verified_evidence]
    if request.retrieval_mode == "llm_only":
        citations = []
    return QueryResponse(
        answer=answer.answer,
        citations=citations,
        evidence=[to_evidence_read(item) for item in verified_evidence],
        trace_id=trace.id,
        confidence=answer.confidence,
        insufficiency_reason=answer.insufficiency_reason,
    )


def read_trace(
    session: Session,
    trace_id: str,
) -> tuple[models.QueryTrace, list[tuple[models.Citation, models.Document]]]:
    trace = session.get(models.QueryTrace, trace_id)
    if trace is None:
        raise ValueError(f"Trace {trace_id} was not found")
    rows = session.execute(
        select(models.Citation, models.Document)
        .join(models.Document, models.Document.id == models.Citation.document_id)
        .where(models.Citation.trace_id == trace_id)
        .order_by(models.Citation.created_at)
    ).all()
    return trace, [(row[0], row[1]) for row in rows]
