import dataclasses
import time
from decimal import Decimal
from typing import Any

from rag_common.config import Settings, get_settings
from rag_common.db import models
from rag_common.enums import ChunkerType, PipelineRole, RetrievalMode
from rag_common.pricing import PricingResolver, load_pricing_overrides, merge_pricing
from rag_common.schemas import (
    CitationRead,
    EvidenceRead,
    QueryRequest,
    QueryResponse,
    RetrievedChunkRef,
)
from rag_common.usage import RoleUsage, TokenUsage, merge, total
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag_retrieval.dataset_config import DatasetConfig, load_dataset_config
from rag_retrieval.decomposition import decompose_query
from rag_retrieval.generation import (
    citation_label,
    generate_answer,
    snippet,
)
from rag_retrieval.hybrid import RetrievedChunk, hybrid_retrieve, rrf_fuse_ranked_lists
from rag_retrieval.planning import RetrievalPlan, plan_query
from rag_retrieval.retrieval_tool import run_retrieval_agent


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


def to_citation_read(item: RetrievedChunk, template: str | None = None) -> CitationRead:
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
        label=citation_label(item, template),
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
    answer: str | None = None,
    usage_summary: dict[str, Any] | None = None,
    cost_estimate_usd: float | None = None,
    citation_template: str | None = None,
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
        answer=answer,
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
                citation_label=citation_label(item, citation_template),
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
        role.value: pricing.estimate(getattr(role_usage, role.value).model, getattr(role_usage, role.value), role)
        for role in PipelineRole
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


def _empty_verifier_result() -> dict[str, Any]:
    # confidence is None (not 0.0) so the UI can distinguish "verifier didn't run"
    # from "verifier ran and was unconfident". Single-pass and llm_only never
    # overwrite this dict, so 0.0 would read as a low-confidence verdict.
    return {
        "supported_chunk_ids": [],
        "missing_subclaims": [],
        "contradictions": [],
        "retry_query": None,
        "confidence": None,
        "reasoning": None,
    }


def _empty_meta(resolved: Settings) -> dict[str, Any]:
    return {"agent_used": False, "model": resolved.zai_chat_model, "error": None}


def _heuristic_plan(
    session: Session,
    *,
    request: QueryRequest,
    resolved: Settings,
    dataset_config: DatasetConfig,
) -> tuple[RetrievalPlan, dict[str, Any], TokenUsage]:
    return plan_query(
        session,
        dataset_id=request.dataset_id,
        question=request.question,
        filters=request.filters,
        settings=resolved,
        force_heuristic=True,
        dataset_config=dataset_config,
    )


def run_query(
    session: Session,
    *,
    request: QueryRequest,
    settings: Settings | None = None,
) -> QueryResponse:
    resolved = settings or get_settings()
    start = time.perf_counter()
    dataset_config = load_dataset_config(session, request.dataset_id)
    top_k = request.top_k or resolved.evidence_top_k

    plan: RetrievalPlan
    planner_meta: dict[str, Any]
    planner_usage: TokenUsage
    retrieval_calls: list[dict[str, Any]] = []
    retrieved: list[RetrievedChunk] = []
    full_retrieval: list[RetrievedChunk] = []
    verifier_result: dict[str, Any] = _empty_verifier_result()
    verifier_meta: dict[str, Any] = _empty_meta(resolved)
    verifier_usage = TokenUsage()
    embedding_usage_total = TokenUsage()
    rerank_usage_total = TokenUsage()
    missing_subclaims: list[str] = []
    contradictions: list[str] = []
    # Decomposition only fires for single_pass; full_agentic does its own multi-query
    # via the retrieval agent's tool calls, and llm_only doesn't retrieve at all. Seed
    # with the "not applicable" defaults so the trace surface is uniform across modes.
    decomposition_meta: dict[str, Any] = {"agent_used": False, "fallback_reason": "not_applicable"}
    decomposition_subquestions: list[str] = []

    if request.retrieval_mode == RetrievalMode.FULL_AGENTIC:
        known_tickers = set(dataset_config.known_tickers)
        agent_result, retrieval_agent_meta, agent_chat_usage = run_retrieval_agent(
            session,
            dataset_id=request.dataset_id,
            question=request.question,
            filters=request.filters,
            known_tickers=known_tickers,
            settings=resolved,
            dataset_config=dataset_config,
        )
        retrieved = list(agent_result.chunks)
        full_retrieval = list(agent_result.chunks)
        retrieval_calls = list(agent_result.tool_calls)
        embedding_usage_total = agent_result.embedding_usage
        rerank_usage_total = agent_result.rerank_usage
        # The retrieval agent absorbed both planning and verification, so its chat tokens
        # roll into RoleUsage.planner. HyDE chat tokens also fold in there because HyDE
        # is part of the agent's planning work for each tool call.
        planner_usage = merge(agent_chat_usage, agent_result.hyde_usage)
        planner_meta = {
            "agent_used": bool(retrieval_agent_meta.get("agent_used")),
            "model": retrieval_agent_meta.get("model"),
            "error": retrieval_agent_meta.get("error"),
            "fallback_reason": retrieval_agent_meta.get("fallback_reason"),
            "source": "retrieval_agent",
            "tool_call_count": retrieval_agent_meta.get("tool_call_count"),
            "tool_retry_count": retrieval_agent_meta.get("tool_retry_count"),
            "tool_call_budget": retrieval_agent_meta.get("tool_call_budget"),
        }
        plan = RetrievalPlan(
            target_tickers=list(agent_result.output.target_tickers),
            forms=list(agent_result.output.forms),
            filing_date_start=request.filters.filing_date_start,
            filing_date_end=request.filters.filing_date_end,
            metrics=list(agent_result.output.metrics),
            subquestions=list(agent_result.output.subquestions),
            query_type=agent_result.output.query_type,
            latest=agent_result.output.latest,
            ambiguity=None,
            reasoning=agent_result.output.reasoning or None,
        )
        verifier_result = {
            "supported_chunk_ids": list(agent_result.output.selected_chunk_ids),
            "missing_subclaims": list(agent_result.output.missing_subclaims),
            "contradictions": list(agent_result.output.contradictions),
            "retry_query": None,
            "confidence": agent_result.output.confidence,
            "reasoning": agent_result.output.reasoning or None,
        }
        verifier_meta = {
            "agent_used": bool(retrieval_agent_meta.get("agent_used")),
            "model": retrieval_agent_meta.get("model"),
            "error": retrieval_agent_meta.get("error"),
            "source": "retrieval_agent",
        }
        verifier_usage = TokenUsage()  # subsumed into planner_usage above
        missing_subclaims = list(agent_result.output.missing_subclaims)
        contradictions = list(agent_result.output.contradictions)
    elif request.retrieval_mode == RetrievalMode.SINGLE_PASS:
        plan, planner_meta, planner_usage = _heuristic_plan(
            session, request=request, resolved=resolved, dataset_config=dataset_config
        )
        subquestions, decomposition_meta, decomposition_usage = decompose_query(
            request.question,
            resolved,
            dataset_config=dataset_config,
        )
        decomposition_subquestions = list(subquestions)
        # Decomposition is a planning-phase LLM call; roll its usage into planner_usage
        # the same way HyDE rolls into planner_usage inside full_agentic (query.py:216).
        planner_usage = merge(planner_usage, decomposition_usage)
        if subquestions:
            # Record what we decomposed into so the persisted plan reflects the actual
            # multi-query strategy used. RetrievalPlan is a frozen dataclass — replace
            # is the standard mutate-by-copy.
            plan = dataclasses.replace(plan, subquestions=subquestions)
        queries: list[tuple[int | None, str]] = (
            [(i, subq) for i, subq in enumerate(subquestions)] if subquestions else [(None, request.question)]
        )
        ranked_lists: list[list[RetrievedChunk]] = []
        for subquestion_index, query_text in queries:
            sub_retrieved, retrieval_trace, embedding_usage, rerank_usage = hybrid_retrieve(
                session,
                dataset_id=request.dataset_id,
                question=query_text,
                filters=request.filters,
                plan=plan,
                top_k=top_k,
                settings=resolved,
            )
            embedding_usage_total = merge(embedding_usage_total, embedding_usage)
            rerank_usage_total = merge(rerank_usage_total, rerank_usage)
            ranked_lists.append(sub_retrieved)
            call_entry: dict[str, Any] = {
                "query": query_text,
                **retrieval_trace,
                "candidates": [
                    {
                        "rank": rank,
                        "chunk_id": item.chunk.id,
                        "ticker": item.document.ticker,
                        "form_type": item.document.form_type,
                        "filing_date": item.document.filing_date.isoformat() if item.document.filing_date else None,
                        "page_start": item.chunk.page_start,
                        "score": float(item.score),
                        "rerank_score": float(item.rerank_score) if item.rerank_score is not None else None,
                        "snippet": snippet(item.chunk.text, limit=400),
                    }
                    for rank, item in enumerate(sub_retrieved, start=1)
                ],
            }
            if subquestion_index is not None:
                call_entry["subquestion_index"] = subquestion_index
            retrieval_calls.append(call_entry)
        # Single-query path keeps the raw ranked list verbatim; multi-query path fuses
        # the per-subquestion lists via RRF so the downstream verifier/generator sees a
        # single coherent evidence ordering rather than a concatenation.
        retrieved = ranked_lists[0] if len(ranked_lists) == 1 else rrf_fuse_ranked_lists(ranked_lists, top_k)
        full_retrieval = list(retrieved)
    else:  # llm_only
        plan, planner_meta, planner_usage = _heuristic_plan(
            session, request=request, resolved=resolved, dataset_config=dataset_config
        )

    verified_evidence = retrieved[:top_k]
    answer, generator_usage = generate_answer(
        question=request.question,
        evidence=verified_evidence,
        retrieval_mode=request.retrieval_mode,
        plan=plan,
        settings=resolved,
        missing_subclaims=missing_subclaims,
        contradictions=contradictions,
        dataset_config=dataset_config,
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
        "chat_model": resolved.zai_chat_model,
        "embedding_model": resolved.openrouter_embedding_model,
        "rerank_model": resolved.openrouter_rerank_model,
        "allow_mock_providers": resolved.allow_mock_providers,
        "agent_planner_used": bool(planner_meta.get("agent_used")),
        "agent_verifier_used": bool(verifier_meta.get("agent_used")),
        "agent_generator_used": generator_metadata.get("generator") == "pydantic-ai-agent",
        "citation_validation": generator_metadata.get("citation_validation"),
        "citation_repair_used": generator_metadata.get("repair_used", False),
        "citation_label_template": dataset_config.citation_label_template,
        "dataset_domain_label": dataset_config.domain_label,
        "chunker": ChunkerType.CHONKIE,
        "planner_error": planner_meta.get("error"),
        "verifier_error": verifier_meta.get("error"),
        "planner_source": planner_meta.get("source"),
        "tool_call_count": planner_meta.get("tool_call_count"),
        "tool_retry_count": planner_meta.get("tool_retry_count"),
        "tool_call_budget": planner_meta.get("tool_call_budget"),
        "decomposition_enabled": resolved.query_decomposition_enabled,
        "decomposition_used": bool(decomposition_meta.get("agent_used")),
        "decomposition_count": len(decomposition_subquestions),
        "decomposition_fallback_reason": decomposition_meta.get("fallback_reason"),
        "decomposition_error": decomposition_meta.get("error"),
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
        answer=answer.answer,
        timings=timings,
        citations=verified_evidence,
        usage_summary=usage_summary_dict,
        cost_estimate_usd=cost_total,
        citation_template=dataset_config.citation_label_template,
    )
    raw_supported_ids = verifier_result.get("supported_chunk_ids") or []
    citations = [to_citation_read(item, dataset_config.citation_label_template) for item in verified_evidence]
    if request.retrieval_mode == RetrievalMode.LLM_ONLY:
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
    degraded_reasons: list[str] = []
    if planner_meta.get("error"):
        degraded_reasons.append(f"planner_fallback: {planner_meta['error']}")
    if verifier_meta.get("error"):
        degraded_reasons.append(f"verifier_fallback: {verifier_meta['error']}")
    if generator_metadata.get("generator") and generator_metadata.get("generator") != "pydantic-ai-agent":
        degraded_reasons.append(f"generator_fallback: {generator_metadata['generator']}")
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
        degraded=bool(degraded_reasons),
        degraded_reasons=degraded_reasons,
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


def list_traces(
    session: Session,
    *,
    dataset_id: str | None = None,
    question_contains: str | None = None,
    limit: int = 50,
) -> list[models.QueryTrace]:
    stmt = select(models.QueryTrace).order_by(models.QueryTrace.created_at.desc()).limit(limit)
    if dataset_id:
        stmt = stmt.where(models.QueryTrace.dataset_id == dataset_id)
    if question_contains:
        stmt = stmt.where(models.QueryTrace.user_question.ilike(f"%{question_contains}%"))
    return list(session.execute(stmt).scalars())
