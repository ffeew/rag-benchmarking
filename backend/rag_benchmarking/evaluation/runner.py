from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from rag_benchmarking.api.schemas import QueryFilters, QueryRequest
from rag_benchmarking.core.config import Settings, get_settings
from rag_benchmarking.db import models
from rag_benchmarking.retrieval.agents import judge_available
from rag_benchmarking.retrieval.query import run_query
from rag_benchmarking.workers.job_state import commit_job_progress

if TYPE_CHECKING:
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


def aggregate_metrics(results: list[models.EvalResult]) -> dict[str, Any]:
    by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        by_mode[result.retrieval_mode].append(result.metrics or {})
    aggregate: dict[str, Any] = {}
    for mode, metrics in by_mode.items():
        if not metrics:
            continue
        per_mode: dict[str, Any] = {
            "case_count": len(metrics),
            "answer_present_rate": sum(metric.get("answer_present", 0.0) for metric in metrics) / len(metrics),
            "expected_contains_rate": sum(metric.get("expected_contains", 0.0) for metric in metrics) / len(metrics),
            "citation_page_hit_rate": sum(metric.get("citation_page_hit", 0.0) for metric in metrics) / len(metrics),
            "insufficient_rate": sum(metric.get("insufficient", 0.0) for metric in metrics) / len(metrics),
        }
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
    return aggregate


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
                response = run_query(
                    session,
                    request=QueryRequest(
                        dataset_id=eval_run.dataset_id,
                        question=case.question,
                        filters=QueryFilters(),
                        include_trace=True,
                        retrieval_mode=variant,
                    ),
                    settings=resolved,
                )
                metrics = {
                    "answer_present": 1.0 if response.answer.strip() else 0.0,
                    "expected_contains": normalized_contains(response.answer, case.expected_answer),
                    "citation_page_hit": citation_page_hit(response.citations, case.expected_citations),
                    "citation_count": len(response.citations),
                    "confidence": response.confidence,
                    "insufficient": 1.0 if response.insufficiency_reason else 0.0,
                }
                result_row = models.EvalResult(
                    eval_run_id=eval_run.id,
                    eval_case_id=case.id,
                    retrieval_mode=variant,
                    answer=response.answer,
                    trace_id=response.trace_id,
                    metrics=metrics,
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
