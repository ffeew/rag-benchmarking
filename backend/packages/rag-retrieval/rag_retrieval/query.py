import time
from decimal import Decimal
from typing import Any

from rag_common.config import Settings, get_settings
from rag_common.db import models
from rag_common.pricing import PricingResolver, load_pricing_overrides, merge_pricing
from rag_common.schemas import (
    CitationRead,
    EvidenceRead,
    QueryRequest,
    QueryResponse,
    RetrievedChunkRef,
)
from rag_common.usage import RoleUsage, TokenUsage, total
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag_retrieval.generation import (
    citation_label,
    generate_answer,
    snippet,
)
from rag_retrieval.hybrid import RetrievedChunk, hybrid_retrieve
from rag_retrieval.planning import plan_query
from rag_retrieval.verification import verify_evidence


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
    usage_summary: dict[str, Any] | None = None,
    cost_estimate_usd: float | None = None,
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
        usage_summary=usage_summary,
        cost_estimate_usd=Decimal(str(cost_estimate_usd)) if cost_estimate_usd is not None else None,
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


def _build_pricing_resolver(settings: Settings) -> PricingResolver:
    overrides = load_pricing_overrides(settings.pricing_overrides_path)
    return PricingResolver(table=merge_pricing(overrides))


def _estimate_role_costs(role_usage: RoleUsage, pricing: PricingResolver) -> dict[str, float]:
    return {
        "planner": pricing.estimate(role_usage.planner.model, role_usage.planner, "planner"),
        "verifier": pricing.estimate(role_usage.verifier.model, role_usage.verifier, "verifier"),
        "generator": pricing.estimate(role_usage.generator.model, role_usage.generator, "generator"),
        "embedding": pricing.estimate(role_usage.embedding.model, role_usage.embedding, "embedding"),
        "rerank": pricing.estimate(role_usage.rerank.model, role_usage.rerank, "rerank"),
        "judge": pricing.estimate(role_usage.judge.model, role_usage.judge, "judge"),
    }


def _to_retrieved_ref(rank: int, item: RetrievedChunk) -> RetrievedChunkRef:
    return RetrievedChunkRef(
        chunk_id=item.chunk.id,
        document_id=item.document.id,
        ticker=item.document.ticker,
        form_type=item.document.form_type,
        page_start=item.chunk.page_start,
        page_end=item.chunk.page_end,
        rank=rank,
    )


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
    plan, planner_meta, planner_usage = plan_query(
        session,
        dataset_id=request.dataset_id,
        question=request.question,
        filters=request.filters,
        settings=resolved,
        force_heuristic=request.retrieval_mode == "single_pass",
    )
    top_k = request.top_k or resolved.evidence_top_k
    retrieval_calls: list[dict[str, Any]] = []
    retrieved: list[RetrievedChunk] = []
    full_retrieval: list[RetrievedChunk] = []
    verifier_result: dict[str, Any] = {
        "supported_chunk_ids": [],
        "missing_subclaims": [],
        "contradictions": [],
        "retry_query": None,
        "confidence": 0.0,
        "reasoning": None,
    }
    verifier_meta: dict[str, Any] = {"agent_used": False, "model": None, "error": None}
    verifier_usage = TokenUsage()
    embedding_usage_total = TokenUsage()
    rerank_usage_total = TokenUsage()

    if request.retrieval_mode != "llm_only":
        retrieved, retrieval_trace, embedding_usage, rerank_usage = hybrid_retrieve(
            session,
            dataset_id=request.dataset_id,
            question=request.question,
            filters=request.filters,
            plan=plan,
            top_k=top_k,
            settings=resolved,
        )
        full_retrieval = list(retrieved)
        embedding_usage_total = embedding_usage
        rerank_usage_total = rerank_usage
        retrieval_calls.append({"query": request.question, **retrieval_trace})
        if request.retrieval_mode == "full_agentic":
            verification, verifier_meta, first_verifier_usage = verify_evidence(
                request.question, retrieved, settings=resolved
            )
            verifier_usage = first_verifier_usage
            verifier_result = verification.as_dict()
        if (
            request.retrieval_mode == "full_agentic"
            and not verifier_result.get("supported_chunk_ids")
            and verifier_result.get("retry_query")
            and resolved.agent_retry_budget > 0
        ):
            retry_retrieved, retry_trace, retry_embedding_usage, retry_rerank_usage = hybrid_retrieve(
                session,
                dataset_id=request.dataset_id,
                question=str(verifier_result["retry_query"]),
                filters=request.filters,
                plan=plan,
                top_k=top_k,
                settings=resolved,
            )
            retrieval_calls.append({"query": verification.retry_query, "retry": True, **retry_trace})
            retrieved = retry_retrieved
            full_retrieval = list(retry_retrieved)
            from rag_common.usage import merge

            embedding_usage_total = merge(embedding_usage_total, retry_embedding_usage)
            rerank_usage_total = merge(rerank_usage_total, retry_rerank_usage)
            verification, verifier_meta, retry_verifier_usage = verify_evidence(
                request.question, retrieved, settings=resolved
            )
            verifier_usage = merge(verifier_usage, retry_verifier_usage)
            verifier_result = verification.as_dict()

    raw_supported_ids = verifier_result.get("supported_chunk_ids") or []
    supported_ids = set(raw_supported_ids if isinstance(raw_supported_ids, list) else [])
    verified_evidence = [item for item in retrieved if not supported_ids or item.chunk.id in supported_ids][:top_k]
    answer, generator_usage = generate_answer(
        question=request.question,
        evidence=verified_evidence,
        retrieval_mode=request.retrieval_mode,
        plan=plan,
        settings=resolved,
    )
    timings = {"total_seconds": round(time.perf_counter() - start, 3)}
    generator_metadata = answer.metadata or {}

    role_usage = RoleUsage(
        planner=planner_usage,
        verifier=verifier_usage,
        generator=generator_usage,
        embedding=embedding_usage_total,
        rerank=rerank_usage_total,
        judge=TokenUsage(),
    )
    pricing = _build_pricing_resolver(resolved)
    cost_breakdown = _estimate_role_costs(role_usage, pricing)
    cost_total = sum(cost_breakdown.values())
    usage_summary_dict = role_usage.model_dump()

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
        "usage_summary": usage_summary_dict,
        "cost_breakdown_usd": cost_breakdown,
        "cost_estimate_usd": cost_total,
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
        usage_summary=usage_summary_dict,
        cost_estimate_usd=cost_total,
    )
    citations = [to_citation_read(item) for item in verified_evidence]
    if request.retrieval_mode == "llm_only":
        citations = []

    full_retrieval_refs: list[RetrievedChunkRef] | None = None
    if request.include_full_retrieval:
        full_retrieval_refs = [_to_retrieved_ref(rank, item) for rank, item in enumerate(full_retrieval, start=1)]
    generator_metadata_with_plan: dict[str, Any] = {
        **(answer.metadata or {}),
        "plan": plan.as_dict(),
        "verifier_supported_chunk_ids": list(raw_supported_ids if isinstance(raw_supported_ids, list) else []),
    }

    total_usage = total(role_usage)
    return QueryResponse(
        answer=answer.answer,
        citations=citations,
        evidence=[to_evidence_read(item) for item in verified_evidence],
        trace_id=trace.id,
        confidence=answer.confidence,
        insufficiency_reason=answer.insufficiency_reason,
        usage_summary=role_usage,
        cost_estimate_usd=cost_total if not total_usage.is_empty() else None,
        generator_metadata=generator_metadata_with_plan,
        full_retrieval=full_retrieval_refs,
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
