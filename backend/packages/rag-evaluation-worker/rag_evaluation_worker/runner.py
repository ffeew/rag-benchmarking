from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from rag_common.config import Settings, get_settings
from rag_common.db import models
from rag_common.job_state import commit_job_progress
from rag_common.pricing import PricingResolver, load_pricing_overrides, merge_pricing
from rag_common.schemas import QueryFilters, QueryRequest
from rag_common.usage import TokenUsage
from rag_retrieval.agents import judge_available
from rag_retrieval.query import run_query
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from rag_evaluation_worker.metrics import (
    ChunkSnapshot,
    CitationSnapshot,
    ExpectedCitation,
    PlanFilters,
    RetrievedChunkRef,
    citation_coverage,
    citation_validity,
    mean_reciprocal_rank,
    metadata_filter_correctness,
    page_evidence_f1,
    recall_at_k,
)

if TYPE_CHECKING:
    from rag_common.schemas import QueryResponse
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def normalized_contains(answer: str, expected: str | None) -> float:
    if not expected:
        return 0.0
    return 1.0 if expected.lower().strip() in answer.lower() else 0.0


def citation_page_hit(response_citations: list[Any], expected_citations: list[dict[str, Any]]) -> float:
    if not expected_citations:
        return 0.0
    expected_pages = {
        (item.get("ticker"), item.get("form_type"), item.get("page_number")) for item in expected_citations
    }
    actual_pages = {(citation.ticker, citation.form_type, citation.page_number) for citation in response_citations}
    if not expected_pages:
        return 0.0
    return len(expected_pages & actual_pages) / len(expected_pages)


def _coerce_expected_citations(raw: list[dict[str, Any]]) -> list[ExpectedCitation]:
    return [
        ExpectedCitation(
            ticker=item.get("ticker"),
            form_type=item.get("form_type"),
            page_number=item.get("page_number"),
            document_id=item.get("document_id"),
            evidence_text=item.get("evidence_text"),
        )
        for item in raw
        if isinstance(item, dict)
    ]


def _coerce_retrieved(refs: list[Any] | None) -> list[RetrievedChunkRef]:
    if not refs:
        return []
    coerced: list[RetrievedChunkRef] = []
    for ref in refs:
        if isinstance(ref, RetrievedChunkRef):
            coerced.append(ref)
            continue
        data = ref.model_dump() if hasattr(ref, "model_dump") else dict(ref)
        coerced.append(RetrievedChunkRef(**data))
    return coerced


def _expected_page_set(expected: list[ExpectedCitation]) -> set[tuple[str, int]]:
    pages: set[tuple[str, int]] = set()
    for exp in expected:
        if exp.page_number is None:
            continue
        key = exp.document_id or exp.ticker
        if key is None:
            continue
        pages.add((key, exp.page_number))
    return pages


def _retrieved_page_set(retrieved: list[RetrievedChunkRef]) -> set[tuple[str, int]]:
    pages: set[tuple[str, int]] = set()
    for item in retrieved:
        for page in range(item.page_start, item.page_end + 1):
            pages.add((item.document_id, page))
            pages.add((item.ticker, page))
    return pages


def _load_chunk_snapshots(session: Session, chunk_ids: list[str]) -> dict[str, ChunkSnapshot]:
    if not chunk_ids:
        return {}
    rows = session.execute(
        select(
            models.Chunk.id,
            models.Chunk.document_id,
            models.Chunk.text,
            models.Chunk.page_start,
            models.Chunk.page_end,
        ).where(models.Chunk.id.in_(chunk_ids))
    ).all()
    return {
        row[0]: ChunkSnapshot(
            chunk_id=row[0],
            document_id=row[1],
            text=row[2],
            page_start=row[3],
            page_end=row[4],
        )
        for row in rows
    }


def _citation_snapshots_from_response(response: QueryResponse) -> list[CitationSnapshot]:
    return [
        CitationSnapshot(
            chunk_id=citation.chunk_id,
            document_id=citation.document_id,
            page_number=citation.page_number,
            evidence_text=citation.snippet,
        )
        for citation in response.citations
    ]


def _ensure_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _compute_case_metrics(
    *,
    session: Session,
    response: QueryResponse,
    case: models.EvalCase,
    latency_ms: int,
) -> dict[str, Any]:
    expected = _coerce_expected_citations(case.expected_citations or [])
    retrieved = _coerce_retrieved(response.full_retrieval)
    generator_metadata = _ensure_dict(response.generator_metadata)
    plan_dict = _ensure_dict(generator_metadata.get("plan"))
    plan_filters = PlanFilters.from_plan_dict(plan_dict)

    citation_snapshots = _citation_snapshots_from_response(response)
    chunk_ids = [citation.chunk_id for citation in citation_snapshots]
    chunks_by_id = _load_chunk_snapshots(session, chunk_ids)

    citations_used_raw = generator_metadata.get("citations_used")
    citations_used = [str(item) for item in citations_used_raw] if isinstance(citations_used_raw, list) else []

    metrics: dict[str, Any] = {
        "answer_present": 1.0 if response.answer.strip() else 0.0,
        "expected_contains": normalized_contains(response.answer, case.expected_answer),
        "citation_page_hit": citation_page_hit(response.citations, case.expected_citations or []),
        "citation_count": len(response.citations),
        "confidence": response.confidence,
        "insufficient": 1.0 if response.insufficiency_reason else 0.0,
        "latency_ms": latency_ms,
        "recall_at_5": recall_at_k(expected, retrieved, k=5),
        "recall_at_10": recall_at_k(expected, retrieved, k=10),
        "mrr": mean_reciprocal_rank(expected, retrieved),
        "page_evidence_f1": page_evidence_f1(_expected_page_set(expected), _retrieved_page_set(retrieved)),
        "metadata_filter_correctness": metadata_filter_correctness(plan_filters, expected),
        "citation_validity": citation_validity(citation_snapshots, chunks_by_id),
        "citation_coverage": citation_coverage(response.answer, citations_used),
    }
    return metrics


def _empty_role_usage_dict() -> dict[str, dict[str, Any]]:
    return {
        "planner": TokenUsage().model_dump(),
        "verifier": TokenUsage().model_dump(),
        "generator": TokenUsage().model_dump(),
        "embedding": TokenUsage().model_dump(),
        "rerank": TokenUsage().model_dump(),
        "judge": TokenUsage().model_dump(),
    }


def _build_pricing(settings: Settings) -> PricingResolver:
    overrides = load_pricing_overrides(settings.pricing_overrides_path)
    return PricingResolver(table=merge_pricing(overrides))


def aggregate_metrics(results: list[models.EvalResult]) -> dict[str, Any]:
    by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_mode_results: dict[str, list[models.EvalResult]] = defaultdict(list)
    for result in results:
        by_mode[result.retrieval_mode].append(result.metrics or {})
        by_mode_results[result.retrieval_mode].append(result)
    aggregate: dict[str, Any] = {}
    grand_total_cost = 0.0
    for mode, metrics in by_mode.items():
        if not metrics:
            continue
        per_mode: dict[str, Any] = {
            "case_count": len(metrics),
            "answer_present_rate": _mean(metric.get("answer_present", 0.0) for metric in metrics),
            "expected_contains_rate": _mean(metric.get("expected_contains", 0.0) for metric in metrics),
            "citation_page_hit_rate": _mean(metric.get("citation_page_hit", 0.0) for metric in metrics),
            "insufficient_rate": _mean(metric.get("insufficient", 0.0) for metric in metrics),
            "avg_recall_at_5": _mean(metric.get("recall_at_5", 0.0) for metric in metrics),
            "avg_recall_at_10": _mean(metric.get("recall_at_10", 0.0) for metric in metrics),
            "avg_mrr": _mean(metric.get("mrr", 0.0) for metric in metrics),
            "avg_page_evidence_f1": _mean(metric.get("page_evidence_f1", 0.0) for metric in metrics),
            "metadata_filter_correctness_rate": _mean(
                metric.get("metadata_filter_correctness", 0.0) for metric in metrics
            ),
            "citation_validity_rate": _mean(metric.get("citation_validity", 0.0) for metric in metrics),
            "citation_coverage_rate": _mean(metric.get("citation_coverage", 0.0) for metric in metrics),
        }
        latency_values = [metric["latency_ms"] for metric in metrics if isinstance(metric.get("latency_ms"), (int, float))]
        if latency_values:
            per_mode["avg_latency_ms"] = sum(latency_values) / len(latency_values)
        cost_values = [
            float(sum(result.cost_estimate.values()))
            for result in by_mode_results[mode]
            if isinstance(result.cost_estimate, dict)
        ]
        if cost_values:
            per_mode["total_cost_usd"] = sum(cost_values)
            per_mode["cost_per_case_usd"] = sum(cost_values) / max(len(cost_values), 1)
            grand_total_cost += sum(cost_values)
        token_values = [
            int(_extract_total_tokens(result.usage))
            for result in by_mode_results[mode]
            if isinstance(result.usage, dict)
        ]
        if token_values:
            per_mode["total_tokens"] = sum(token_values)
        ragas_scores: dict[str, list[float]] = defaultdict(list)
        for metric in metrics:
            ragas = metric.get("ragas")
            if not isinstance(ragas, dict):
                continue
            for key, value in ragas.items():
                if isinstance(value, (int, float)) and not math.isnan(float(value)):
                    ragas_scores[key].append(float(value))
        if ragas_scores:
            per_mode["ragas"] = {key: sum(values) / len(values) for key, values in ragas_scores.items()}
        aggregate[mode] = per_mode
    if grand_total_cost > 0.0:
        aggregate["total_cost_usd"] = grand_total_cost
    return aggregate


def _mean(values: Any) -> float:
    collected = [float(value) for value in values]
    if not collected:
        return 0.0
    return sum(collected) / len(collected)


def _extract_total_tokens(usage: dict[str, Any] | None) -> int:
    if not isinstance(usage, dict):
        return 0
    total = 0
    for role_data in usage.values():
        if isinstance(role_data, dict):
            total += int(role_data.get("total_tokens", 0) or 0)
    return total


def _ragas_sample(case: models.EvalCase, response_answer: str, contexts: list[str]) -> dict[str, Any]:
    return {
        "user_input": case.question,
        "response": response_answer,
        "retrieved_contexts": contexts or [""],
        "reference": case.expected_answer or "",
    }


def _attach_ragas_scores(
    pending: list[tuple[models.EvalResult, dict[str, Any]]],
    settings: Settings,
) -> dict[str, Any]:
    """Compute RAGAS faithfulness/answer_relevancy/context_* and attach to each result."""
    if not pending:
        return {}
    if not judge_available(settings):
        for entry, _ in pending:
            merged = dict(entry.metrics or {})
            merged["ragas_skipped"] = "judge_unavailable"
            entry.metrics = merged
        return {"skipped": "judge_unavailable"}

    try:
        from openai import OpenAI
        from ragas.embeddings import OpenAIEmbeddings as RagasOpenAIEmbeddings
        from ragas.llms import llm_factory
        from ragas.metrics.collections import (
            AnswerRelevancy,
            ContextPrecision,
            ContextRecall,
            Faithfulness,
        )
    except ImportError as exc:
        logger.warning("ragas_import_failed", extra={"error": str(exc)})
        return {"error": f"ragas import failed: {exc}"}

    if settings.openrouter_api_key is None:
        return {"skipped": "no_api_key"}
    api_key = settings.openrouter_api_key.get_secret_value()

    client = OpenAI(base_url=settings.openrouter_base_url, api_key=api_key)
    llm = llm_factory(model=settings.openrouter_judge_model or "", client=client)
    embeddings = None
    if settings.openrouter_embedding_model:
        embeddings = RagasOpenAIEmbeddings(client=client, model=settings.openrouter_embedding_model)

    has_reference = any(sample["reference"] for _, sample in pending)
    metrics_config: list[tuple[str, Any]] = [
        ("faithfulness", Faithfulness(llm=llm)),
        ("context_precision", ContextPrecision(llm=llm)),
    ]
    if embeddings is not None:
        metrics_config.append(("answer_relevancy", AnswerRelevancy(llm=llm, embeddings=embeddings)))
    if has_reference:
        metrics_config.append(("context_recall", ContextRecall(llm=llm)))

    for entry, sample in pending:
        scores: dict[str, float] = {}
        for key, metric in metrics_config:
            try:
                if key == "faithfulness":
                    result = metric.score(
                        user_input=sample["user_input"],
                        response=sample["response"],
                        retrieved_contexts=sample["retrieved_contexts"],
                    )
                elif key == "answer_relevancy":
                    result = metric.score(
                        user_input=sample["user_input"],
                        response=sample["response"],
                    )
                elif key == "context_precision":
                    result = metric.score(
                        user_input=sample["user_input"],
                        reference=sample["reference"] or sample["response"],
                        retrieved_contexts=sample["retrieved_contexts"],
                    )
                elif key == "context_recall":
                    result = metric.score(
                        user_input=sample["user_input"],
                        response=sample["response"],
                        reference=sample["reference"],
                        retrieved_contexts=sample["retrieved_contexts"],
                    )
                else:
                    continue
                value = float(result.value) if result.value is not None else float("nan")
            except (RuntimeError, ValueError, KeyError, OSError) as exc:
                logger.warning("ragas_metric_failed", extra={"metric": key, "error": str(exc)})
                continue
            if not math.isnan(value):
                scores[key] = value
        merged = dict(entry.metrics or {})
        if scores:
            merged["ragas"] = scores
        else:
            merged["ragas_error"] = "no metric scored"
        entry.metrics = merged

    return {"case_count": len(pending), "metrics": [key for key, _ in metrics_config]}


def run_evaluation(
    session: Session,
    *,
    eval_run_id: str,
    job_id: str | None,
    settings: Settings | None = None,
) -> models.EvalRun:
    resolved = settings or get_settings()
    pricing = _build_pricing(resolved)
    eval_run = session.get(models.EvalRun, eval_run_id)
    if eval_run is None:
        raise ValueError(f"Evaluation run {eval_run_id} was not found")
    commit_job_progress(job_id, status="running", progress=5, current_step="loading eval cases")
    eval_run.status = "running"
    session.flush()

    case_ids = eval_run.run_config.get("case_ids") or []
    if case_ids:
        cases = list(session.scalars(select(models.EvalCase).where(models.EvalCase.id.in_(case_ids))))
    else:
        cases = list(
            session.scalars(
                select(models.EvalCase)
                .where(models.EvalCase.dataset_id == eval_run.dataset_id)
                .order_by(models.EvalCase.created_at)
                .limit(80)
            )
        )
    variants = eval_run.run_config.get("system_variants") or ["full_agentic", "single_pass", "llm_only"]
    total = max(1, len(cases) * len(variants))
    completed = 0
    errors: list[dict[str, Any]] = []
    pending_ragas: list[tuple[models.EvalResult, dict[str, Any]]] = []
    for case in cases:
        for variant in variants:
            try:
                start = time.perf_counter()
                response = run_query(
                    session,
                    request=QueryRequest(
                        dataset_id=eval_run.dataset_id,
                        question=case.question,
                        filters=QueryFilters(),
                        include_trace=True,
                        retrieval_mode=variant,
                        include_full_retrieval=True,
                    ),
                    settings=resolved,
                )
                latency_ms = int((time.perf_counter() - start) * 1000)
                metrics = _compute_case_metrics(
                    session=session,
                    response=response,
                    case=case,
                    latency_ms=latency_ms,
                )
                usage_dump = (
                    response.usage_summary.model_dump() if response.usage_summary is not None else _empty_role_usage_dict()
                )
                cost_breakdown: dict[str, float] = {}
                if response.usage_summary is not None:
                    role_usage = response.usage_summary
                    cost_breakdown = {
                        "planner": pricing.estimate(role_usage.planner.model, role_usage.planner, "planner"),
                        "verifier": pricing.estimate(role_usage.verifier.model, role_usage.verifier, "verifier"),
                        "generator": pricing.estimate(role_usage.generator.model, role_usage.generator, "generator"),
                        "embedding": pricing.estimate(role_usage.embedding.model, role_usage.embedding, "embedding"),
                        "rerank": pricing.estimate(role_usage.rerank.model, role_usage.rerank, "rerank"),
                        "judge": pricing.estimate(role_usage.judge.model, role_usage.judge, "judge"),
                    }
                result_row = models.EvalResult(
                    eval_run_id=eval_run.id,
                    eval_case_id=case.id,
                    retrieval_mode=variant,
                    answer=response.answer,
                    trace_id=response.trace_id,
                    metrics=metrics,
                    usage=usage_dump,
                    cost_estimate=cost_breakdown or None,
                    latency_ms=latency_ms,
                )
                session.add(result_row)
                session.flush()
                contexts = [evidence.snippet for evidence in response.evidence if evidence.snippet]
                pending_ragas.append((result_row, _ragas_sample(case, response.answer, contexts)))
            except (OSError, RuntimeError, SQLAlchemyError, ValueError) as exc:
                errors.append({"case_id": case.id, "variant": variant, "error": str(exc)})
                session.add(
                    models.EvalResult(
                        eval_run_id=eval_run.id,
                        eval_case_id=case.id,
                        retrieval_mode=variant,
                        error=str(exc),
                        metrics={},
                    )
                )
            completed += 1
            commit_job_progress(
                job_id,
                status="running",
                progress=int((completed / total) * 90),
                current_step=f"evaluated {completed}/{total}",
            )
            session.flush()

    commit_job_progress(job_id, status="running", progress=92, current_step="computing ragas metrics")
    ragas_summary = _attach_ragas_scores(pending_ragas, resolved)
    session.flush()

    results = list(session.scalars(select(models.EvalResult).where(models.EvalResult.eval_run_id == eval_run.id)))
    eval_run.errors = errors
    eval_run.metrics = aggregate_metrics(results)
    if ragas_summary:
        eval_run.metrics["ragas_run"] = ragas_summary
    eval_run.status = "completed" if not errors else "completed_with_errors"
    commit_job_progress(job_id, status=eval_run.status, progress=100, current_step="completed")
    session.flush()
    return eval_run
