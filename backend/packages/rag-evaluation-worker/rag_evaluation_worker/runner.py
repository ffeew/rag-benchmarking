from __future__ import annotations

import logging
import math
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from rag_common.config import Settings, get_settings
from rag_common.db import models
from rag_common.eval_variants import apply_overrides
from rag_common.job_state import commit_job_progress
from rag_common.pricing import PricingResolver, load_pricing_overrides, merge_pricing
from rag_common.schemas import QueryFilters, QueryRequest, RetrievalOverrides, RetrievalVariantSpec
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
    strict_mean_reciprocal_rank,
    strict_recall_at_k,
)
from rag_evaluation_worker.scoring import (
    bootstrap_mean_ci,
    coerce_expected_evidence,
    score_answer,
    strict_evidence_eligible,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

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


def _strict_expected_page_set(expected: Sequence[object]) -> set[tuple[str, int]]:
    pages: set[tuple[str, int]] = set()
    for exp in expected:
        page_number = getattr(exp, "page_number", None)
        if page_number is None:
            continue
        document_id = getattr(exp, "document_id", None)
        ticker = getattr(exp, "ticker", None)
        form_type = getattr(exp, "form_type", None)
        if document_id:
            pages.add((str(document_id), int(page_number)))
        if ticker and form_type:
            pages.add((f"{str(ticker).upper()}:{str(form_type).upper()}", int(page_number)))
    return pages


def _strict_retrieved_page_set(retrieved: list[RetrievedChunkRef]) -> set[tuple[str, int]]:
    pages: set[tuple[str, int]] = set()
    for item in retrieved:
        for page in range(item.page_start, item.page_end + 1):
            pages.add((item.document_id, page))
            pages.add((f"{item.ticker.upper()}:{item.form_type.upper()}", page))
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


def _citation_matches_expected(citation: Any, expected: object) -> bool:
    page_number = getattr(expected, "page_number", None)
    if page_number is None or citation.page_number != page_number:
        return False
    document_id = getattr(expected, "document_id", None)
    if document_id:
        return bool(citation.document_id == document_id)
    ticker = getattr(expected, "ticker", None)
    form_type = getattr(expected, "form_type", None)
    if not ticker or not form_type:
        return False
    return bool(citation.ticker.upper() == ticker.upper() and citation.form_type.upper() == form_type.upper())


def _citation_gold_scores(response: QueryResponse, expected: Sequence[object]) -> dict[str, Any]:
    if not expected:
        return {
            "citation_gold_precision": None,
            "citation_gold_recall": None,
        }
    matched_citations = sum(
        1 for citation in response.citations if any(_citation_matches_expected(citation, exp) for exp in expected)
    )
    matched_expected = sum(
        1 for exp in expected if any(_citation_matches_expected(citation, exp) for citation in response.citations)
    )
    precision = matched_citations / len(response.citations) if response.citations else 0.0
    recall = matched_expected / len(expected)
    return {
        "citation_gold_precision": precision,
        "citation_gold_recall": recall,
    }


def _parser_table_diagnostics(session: Session, expected: Sequence[object]) -> dict[str, Any]:
    eligible = [item for item in expected if getattr(item, "document_id", None) and getattr(item, "page_number", None)]
    if not eligible:
        return {}

    page_hits = 0
    chunk_hits = 0
    table_required = 0
    table_preserved = 0
    for item in eligible:
        document_id = str(getattr(item, "document_id"))
        page_number = int(getattr(item, "page_number"))
        evidence_text = getattr(item, "evidence_text", None)
        table_key = getattr(item, "table_key", None)
        parsed_page = session.scalar(
            select(models.ParsedPage).where(
                models.ParsedPage.document_id == document_id,
                models.ParsedPage.page_number == page_number,
            )
        )
        page_text = parsed_page.text if parsed_page is not None else ""
        if _evidence_text_hit(evidence_text, page_text) or (parsed_page is not None and not evidence_text):
            page_hits += 1

        chunks = list(
            session.scalars(
                select(models.Chunk).where(
                    models.Chunk.document_id == document_id,
                    models.Chunk.page_start <= page_number,
                    models.Chunk.page_end >= page_number,
                    models.Chunk.is_active.is_(True),
                )
            )
        )
        if any(_evidence_text_hit(evidence_text, chunk.text) or not evidence_text for chunk in chunks):
            chunk_hits += 1
        if table_key:
            table_required += 1
            if any(
                chunk.contains_table and _evidence_text_hit(evidence_text or table_key, chunk.text) for chunk in chunks
            ):
                table_preserved += 1

    diagnostics: dict[str, Any] = {
        "parser_expected_evidence_count": len(eligible),
        "parser_page_text_hit_rate": page_hits / len(eligible),
        "chunk_evidence_hit_rate": chunk_hits / len(eligible),
    }
    if table_required:
        diagnostics["table_chunk_preservation_rate"] = table_preserved / table_required
    return diagnostics


def _evidence_text_hit(needle: str | None, haystack: str) -> bool:
    if not needle:
        return False
    return _normalize_whitespace(needle) in _normalize_whitespace(haystack)


def _normalize_whitespace(text: str) -> str:
    return " ".join(text.lower().split())


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
    expected_evidence = coerce_expected_evidence(case.expected_evidence or [])
    strict_expected = strict_evidence_eligible(expected_evidence)
    retrieved = _coerce_retrieved(response.full_retrieval)
    generator_metadata = _ensure_dict(response.generator_metadata)
    plan_dict = _ensure_dict(generator_metadata.get("plan"))
    plan_filters = PlanFilters.from_plan_dict(plan_dict)

    citation_snapshots = _citation_snapshots_from_response(response)
    chunk_ids = [citation.chunk_id for citation in citation_snapshots]
    chunks_by_id = _load_chunk_snapshots(session, chunk_ids)

    citations_used_raw = generator_metadata.get("citations_used")
    citations_used = [str(item) for item in citations_used_raw] if isinstance(citations_used_raw, list) else []
    answer_metrics = score_answer(
        answer=response.answer,
        insufficiency_reason=response.insufficiency_reason,
        raw_spec=case.expected_answer_spec,
    )
    verified = case.verification_status == "verified"
    answer_gold_eligible = verified and bool(answer_metrics.get("answer_scoreable"))
    evidence_gold_eligible = verified and bool(strict_expected)

    metrics: dict[str, Any] = {
        "eval_case_id": case.id,
        "case_key": case.case_key,
        "category": case.category or "uncategorized",
        "difficulty": case.difficulty or "uncategorized",
        "tags": case.tags or [],
        "verification_status": case.verification_status,
        "gold_version": case.gold_version,
        "gold_eligible": answer_gold_eligible or evidence_gold_eligible,
        "answer_gold_eligible": answer_gold_eligible,
        "evidence_gold_eligible": evidence_gold_eligible,
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
        "evidence_recall_at_5": strict_recall_at_k(strict_expected, retrieved, k=5) if evidence_gold_eligible else None,
        "evidence_recall_at_10": (
            strict_recall_at_k(strict_expected, retrieved, k=10) if evidence_gold_eligible else None
        ),
        "evidence_mrr": strict_mean_reciprocal_rank(strict_expected, retrieved) if evidence_gold_eligible else None,
        "evidence_page_f1": (
            page_evidence_f1(_strict_expected_page_set(strict_expected), _strict_retrieved_page_set(retrieved))
            if evidence_gold_eligible
            else None
        ),
        "metadata_filter_correctness": metadata_filter_correctness(plan_filters, expected),
        "citation_validity": citation_validity(citation_snapshots, chunks_by_id),
        "citation_reference_validity": citation_validity(citation_snapshots, chunks_by_id),
        "claim_citation_coverage": citation_coverage(response.answer, citations_used),
        "citation_coverage": citation_coverage(response.answer, citations_used),
    }
    metrics.update(answer_metrics)
    if evidence_gold_eligible:
        metrics.update(_citation_gold_scores(response, strict_expected))
        metrics.update(_parser_table_diagnostics(session, strict_expected))
    else:
        metrics.update({"citation_gold_precision": None, "citation_gold_recall": None})
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


_LEGACY_VARIANTS: list[str] = ["full_agentic", "single_pass", "llm_only"]


def _resolve_variants(run_config: dict[str, Any]) -> list[RetrievalVariantSpec]:
    """Materialize the variant specs for this eval run.

    Reads ``run_config['variants']`` (new shape, list of dicts) and falls back
    to ``run_config['system_variants']`` (legacy, list of RetrievalMode literals)
    so older eval runs continue to aggregate. Never raises on legacy rows; only
    raises if the new ``variants`` payload is malformed.
    """

    raw = run_config.get("variants")
    if raw:
        if not isinstance(raw, list):
            raise ValueError("run_config['variants'] must be a list of variant specs")
        return [RetrievalVariantSpec.model_validate(item) for item in raw]
    legacy = run_config.get("system_variants") or _LEGACY_VARIANTS
    return [
        RetrievalVariantSpec(name=mode, retrieval_mode=mode, overrides=RetrievalOverrides()) for mode in legacy
    ]


def _detect_pairing_skew(
    case_ids_per_variant: dict[str, set[str]], *, expected_cases: set[str]
) -> dict[str, Any]:
    """Detect cases that succeeded for some variants but not others.

    Returns a structured summary used by the analyzer to either drop affected
    case×pair contrasts (preferred) or surface the skew in the report. An empty
    ``missing`` block means every variant covered the exact same case set.
    """

    missing: dict[str, list[str]] = {}
    for variant, ids in case_ids_per_variant.items():
        diff = sorted(expected_cases - ids)
        if diff:
            missing[variant] = diff
    return {
        "expected_case_count": len(expected_cases),
        "variant_case_counts": {variant: len(ids) for variant, ids in case_ids_per_variant.items()},
        "missing": missing,
        "balanced": not missing,
    }


def aggregate_metrics(results: list[models.EvalResult], *, seed: int = 1729) -> dict[str, Any]:
    by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_mode_results: dict[str, list[models.EvalResult]] = defaultdict(list)
    for result in results:
        # Bucket on variant_name when present (post-0005), fall back to retrieval_mode
        # for legacy rows so historical eval runs still aggregate.
        bucket = result.variant_name or result.retrieval_mode
        by_mode[bucket].append(result.metrics or {})
        by_mode_results[bucket].append(result)
    aggregate: dict[str, Any] = {}
    grand_total_cost = 0.0
    for mode, metrics in by_mode.items():
        if not metrics:
            continue
        per_mode = _summary_for_metrics(metrics, seed=seed)
        latency_values = [
            metric["latency_ms"] for metric in metrics if isinstance(metric.get("latency_ms"), (int, float))
        ]
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
        judge_scores = _judge_score_summary(metrics)
        if judge_scores:
            per_mode["judge_diagnostics"] = judge_scores
        per_mode["by_category"] = _grouped_summaries(metrics, key="category", seed=seed)
        per_mode["by_difficulty"] = _grouped_summaries(metrics, key="difficulty", seed=seed)
        per_mode["by_tag"] = _tagged_summaries(metrics, seed=seed)
        per_mode["representative_failures"] = _representative_failures(metrics)
        # Surface the underlying pipeline literal and the overrides that produced
        # this bucket so downstream tooling (analyze_ablation, dashboards) can
        # group named variants by their lineage.
        sample_row = by_mode_results[mode][0]
        per_mode["retrieval_mode"] = sample_row.retrieval_mode
        sample_metric = metrics[0] if metrics else {}
        overrides_applied = sample_metric.get("overrides_applied")
        if isinstance(overrides_applied, dict):
            per_mode["overrides_applied"] = overrides_applied
        aggregate[mode] = per_mode
    if grand_total_cost > 0.0:
        aggregate["total_cost_usd"] = grand_total_cost
    return aggregate


def _summary_for_metrics(metrics: list[dict[str, Any]], *, seed: int) -> dict[str, Any]:
    answer_values = _eligible_values(metrics, key="answer_accuracy", eligible_key="answer_gold_eligible")
    evidence_recall_values = _eligible_values(
        metrics, key="evidence_recall_at_10", eligible_key="evidence_gold_eligible"
    )
    citation_gold_recall_values = _eligible_values(
        metrics, key="citation_gold_recall", eligible_key="evidence_gold_eligible"
    )
    summary: dict[str, Any] = {
        "case_count": len(metrics),
        "diagnostic_case_count": len(metrics),
        "scientific_case_count": sum(1 for metric in metrics if metric.get("gold_eligible") is True),
        "answer_scientific_case_count": len(answer_values),
        "evidence_scientific_case_count": len(evidence_recall_values),
        "draft_case_count": sum(1 for metric in metrics if metric.get("verification_status") != "verified"),
        "answer_accuracy_rate": _mean_list(answer_values),
        "answer_accuracy_ci_95": bootstrap_mean_ci(answer_values, seed=seed),
        "avg_evidence_recall_at_10": _mean_list(evidence_recall_values),
        "evidence_recall_at_10_ci_95": bootstrap_mean_ci(evidence_recall_values, seed=seed + 1),
        "citation_gold_recall_rate": _mean_list(citation_gold_recall_values),
        "answer_present_rate": _mean_metric(metrics, "answer_present"),
        "expected_contains_rate": _mean_metric(metrics, "expected_contains"),
        "citation_page_hit_rate": _mean_metric(metrics, "citation_page_hit"),
        "insufficient_rate": _mean_metric(metrics, "insufficient"),
        "avg_recall_at_5": _mean_metric(metrics, "recall_at_5"),
        "avg_recall_at_10": _mean_metric(metrics, "recall_at_10"),
        "avg_mrr": _mean_metric(metrics, "mrr"),
        "avg_page_evidence_f1": _mean_metric(metrics, "page_evidence_f1"),
        "avg_evidence_recall_at_5": _mean_metric(metrics, "evidence_recall_at_5"),
        "avg_evidence_mrr": _mean_metric(metrics, "evidence_mrr"),
        "avg_evidence_page_f1": _mean_metric(metrics, "evidence_page_f1"),
        "metadata_filter_correctness_rate": _mean_metric(metrics, "metadata_filter_correctness"),
        "citation_reference_validity_rate": _mean_metric(metrics, "citation_reference_validity"),
        "citation_validity_rate": _mean_metric(metrics, "citation_validity"),
        "claim_citation_coverage_rate": _mean_metric(metrics, "claim_citation_coverage"),
        "citation_coverage_rate": _mean_metric(metrics, "citation_coverage"),
        "citation_gold_precision_rate": _mean_metric(metrics, "citation_gold_precision"),
    }
    parser_page_values = _numeric_values(metrics, "parser_page_text_hit_rate")
    chunk_values = _numeric_values(metrics, "chunk_evidence_hit_rate")
    table_values = _numeric_values(metrics, "table_chunk_preservation_rate")
    if parser_page_values:
        summary["parser_page_text_hit_rate"] = _mean(parser_page_values)
    if chunk_values:
        summary["chunk_evidence_hit_rate"] = _mean(chunk_values)
    if table_values:
        summary["table_chunk_preservation_rate"] = _mean(table_values)
    return summary


def _eligible_values(metrics: list[dict[str, Any]], *, key: str, eligible_key: str) -> list[float]:
    return [
        float(metric[key])
        for metric in metrics
        if metric.get(eligible_key) is True and isinstance(metric.get(key), (int, float))
    ]


def _numeric_values(metrics: list[dict[str, Any]], key: str) -> list[float]:
    return [float(metric[key]) for metric in metrics if isinstance(metric.get(key), (int, float))]


def _mean_metric(metrics: list[dict[str, Any]], key: str) -> float:
    return _mean(_numeric_values(metrics, key))


def _mean_list(values: list[float]) -> float | None:
    if not values:
        return None
    return _mean(values)


def _grouped_summaries(metrics: list[dict[str, Any]], *, key: str, seed: int) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for metric in metrics:
        value = metric.get(key)
        grouped[str(value or "uncategorized")].append(metric)
    return {group: _summary_for_metrics(items, seed=seed) for group, items in grouped.items()}


def _tagged_summaries(metrics: list[dict[str, Any]], *, seed: int) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for metric in metrics:
        tags = metric.get("tags")
        if not isinstance(tags, list) or not tags:
            grouped["untagged"].append(metric)
            continue
        for tag in tags:
            grouped[str(tag)].append(metric)
    return {tag: _summary_for_metrics(items, seed=seed) for tag, items in grouped.items()}


def _judge_score_summary(metrics: list[dict[str, Any]]) -> dict[str, Any]:
    scores: dict[str, list[float]] = defaultdict(list)
    for metric in metrics:
        diagnostics = metric.get("judge_diagnostics")
        ragas = diagnostics.get("ragas") if isinstance(diagnostics, dict) else metric.get("ragas")
        if not isinstance(ragas, dict):
            continue
        for key, value in ragas.items():
            if isinstance(value, (int, float)) and not math.isnan(float(value)):
                scores[key].append(float(value))
    return {"ragas": {key: _mean(values) for key, values in scores.items()}} if scores else {}


def _representative_failures(metrics: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for metric in metrics:
        answer_failed = (
            metric.get("answer_gold_eligible") is True and _numeric_or_one(metric.get("answer_accuracy")) < 1.0
        )
        evidence_failed = (
            metric.get("evidence_gold_eligible") is True and _numeric_or_one(metric.get("evidence_recall_at_10")) < 1.0
        )
        if not answer_failed and not evidence_failed:
            continue
        failures.append(
            {
                "eval_case_id": metric.get("eval_case_id"),
                "case_key": metric.get("case_key"),
                "category": metric.get("category"),
                "answer_accuracy": metric.get("answer_accuracy"),
                "evidence_recall_at_10": metric.get("evidence_recall_at_10"),
            }
        )
        if len(failures) >= limit:
            break
    return failures


def _numeric_or_one(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 1.0


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


def _case_has_scientific_gold(case: models.EvalCase) -> bool:
    if case.verification_status != "verified":
        return False
    answer_metrics = score_answer(answer="", insufficiency_reason=None, raw_spec=case.expected_answer_spec)
    expected_evidence = strict_evidence_eligible(coerce_expected_evidence(case.expected_evidence or []))
    return bool(answer_metrics.get("answer_scoreable")) or bool(expected_evidence)


def _ingestion_diagnostics(session: Session, dataset_id: str) -> dict[str, Any]:
    runs = list(session.scalars(select(models.IngestionRun).where(models.IngestionRun.dataset_id == dataset_id)))
    pages = list(
        session.scalars(
            select(models.ParsedPage)
            .join(models.Document, models.Document.id == models.ParsedPage.document_id)
            .where(models.Document.dataset_id == dataset_id)
        )
    )
    diagnostics: dict[str, Any] = {
        "ingestion_run_count": len(runs),
        "completed_ingestion_run_count": sum(1 for run in runs if run.status == "completed"),
        "parsed_page_count": len(pages),
    }
    total_seconds = [
        float(run.timings["total_seconds"])
        for run in runs
        if isinstance(run.timings, dict) and isinstance(run.timings.get("total_seconds"), (int, float))
    ]
    if total_seconds:
        diagnostics["avg_ingestion_time_seconds"] = _mean(total_seconds)
    if pages:
        fallback_pages = [page for page in pages if page.parser != "mistral-ocr"]
        flagged_pages = [
            page for page in pages if isinstance(page.quality_flags, dict) and any(page.quality_flags.values())
        ]
        diagnostics["ocr_fallback_page_rate"] = len(fallback_pages) / len(pages)
        diagnostics["parser_quality_flag_rate"] = len(flagged_pages) / len(pages)
        diagnostics["table_page_rate"] = sum(1 for page in pages if page.table_count > 0) / len(pages)
    return diagnostics


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
            merged["judge_diagnostics"] = {"ragas_skipped": "judge_unavailable"}
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

    if settings.zai_api_key is None:
        return {"skipped": "no_api_key"}
    zai_api_key = settings.zai_api_key.get_secret_value()

    llm_client = OpenAI(base_url=settings.zai_base_url, api_key=zai_api_key)
    llm = llm_factory(model=settings.zai_judge_model or "", client=llm_client)
    # Best-effort temperature=0 on the RAGAS judge. The wrapper's attribute path
    # varies by RAGAS version, so we try the common ones and fall through silently.
    # Residual judge stochasticity is acknowledged in docs/eval/ablation_v1_plan.md;
    # RAGAS scores are reported as informational-only, not under FDR control.
    if settings.eval_temperature_zero:
        import contextlib

        for attr in ("langchain_llm", "llm"):
            underlying = getattr(llm, attr, None)
            if underlying is not None and hasattr(underlying, "temperature"):
                with contextlib.suppress(AttributeError, ValueError, TypeError):
                    underlying.temperature = 0
                break
    embeddings = None
    if settings.openrouter_embedding_model and settings.openrouter_api_key is not None:
        embedding_client = OpenAI(
            base_url=settings.openrouter_base_url,
            api_key=settings.openrouter_api_key.get_secret_value(),
        )
        embeddings = RagasOpenAIEmbeddings(client=embedding_client, model=settings.openrouter_embedding_model)

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
            diagnostics = _ensure_dict(merged.get("judge_diagnostics"))
            diagnostics["ragas"] = scores
            merged["judge_diagnostics"] = diagnostics
        else:
            merged["judge_diagnostics"] = {"ragas_error": "no metric scored"}
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
    benchmark_profile = str(eval_run.run_config.get("benchmark_profile") or "scientific")
    if benchmark_profile == "scientific":
        invalid_cases = [case.case_key or case.id for case in cases if not _case_has_scientific_gold(case)]
        if invalid_cases:
            raise ValueError(
                "Scientific evaluation requires verified cases with structured gold fields. "
                f"Invalid cases: {', '.join(invalid_cases[:10])}"
            )
    specs = _resolve_variants(eval_run.run_config)
    bootstrap_seed = int(eval_run.run_config.get("bootstrap_seed") or 1729)
    total = max(1, len(cases) * len(specs))
    completed = 0
    errors: list[dict[str, Any]] = []
    pending_ragas: list[tuple[models.EvalResult, dict[str, Any]]] = []
    case_ids_per_variant: dict[str, set[str]] = defaultdict(set)
    for case in cases:
        for spec in specs:
            overrides_dump = spec.overrides.model_dump(exclude_none=True)
            effective = apply_overrides(resolved, spec.overrides)
            try:
                start = time.perf_counter()
                response = run_query(
                    session,
                    request=QueryRequest(
                        dataset_id=eval_run.dataset_id,
                        question=case.question,
                        filters=QueryFilters(),
                        top_k=max(effective.evidence_top_k, 10),
                        include_trace=True,
                        retrieval_mode=spec.retrieval_mode,
                        include_full_retrieval=True,
                    ),
                    settings=effective,
                )
                latency_ms = int((time.perf_counter() - start) * 1000)
                metrics = _compute_case_metrics(
                    session=session,
                    response=response,
                    case=case,
                    latency_ms=latency_ms,
                )
                metrics["variant_name"] = spec.name
                metrics["retrieval_mode"] = spec.retrieval_mode
                metrics["overrides_applied"] = overrides_dump
                usage_dump = (
                    response.usage_summary.model_dump()
                    if response.usage_summary is not None
                    else (_empty_role_usage_dict())
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
                    retrieval_mode=spec.retrieval_mode,
                    variant_name=spec.name,
                    answer=response.answer,
                    trace_id=response.trace_id,
                    metrics=metrics,
                    usage=usage_dump,
                    cost_estimate=cost_breakdown or None,
                    latency_ms=latency_ms,
                )
                session.add(result_row)
                session.flush()
                case_ids_per_variant[spec.name].add(case.id)
                contexts = [evidence.snippet for evidence in response.evidence if evidence.snippet]
                pending_ragas.append((result_row, _ragas_sample(case, response.answer, contexts)))
            except (OSError, RuntimeError, SQLAlchemyError, ValueError) as exc:
                errors.append({"case_id": case.id, "variant": spec.name, "error": str(exc)})
                session.add(
                    models.EvalResult(
                        eval_run_id=eval_run.id,
                        eval_case_id=case.id,
                        retrieval_mode=spec.retrieval_mode,
                        variant_name=spec.name,
                        error=str(exc),
                        metrics={
                            "variant_name": spec.name,
                            "retrieval_mode": spec.retrieval_mode,
                            "overrides_applied": overrides_dump,
                        },
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

    pairing_skew = _detect_pairing_skew(case_ids_per_variant, expected_cases={case.id for case in cases})

    commit_job_progress(job_id, status="running", progress=92, current_step="computing ragas metrics")
    ragas_summary = _attach_ragas_scores(pending_ragas, resolved)
    session.flush()

    results = list(session.scalars(select(models.EvalResult).where(models.EvalResult.eval_run_id == eval_run.id)))
    eval_run.errors = errors
    eval_run.metrics = aggregate_metrics(results, seed=bootstrap_seed)
    eval_run.metrics["benchmark_profile"] = benchmark_profile
    eval_run.metrics["ingestion_diagnostics"] = _ingestion_diagnostics(session, eval_run.dataset_id)
    eval_run.metrics["pairing_skew"] = pairing_skew
    eval_run.metrics["variants_used"] = [
        {
            "name": spec.name,
            "retrieval_mode": spec.retrieval_mode,
            "overrides": spec.overrides.model_dump(exclude_none=True),
        }
        for spec in specs
    ]
    if not pairing_skew["balanced"]:
        logger.warning(
            "ablation_pairing_skew",
            extra={
                "eval_run_id": eval_run.id,
                "missing": pairing_skew["missing"],
                "expected_case_count": pairing_skew["expected_case_count"],
            },
        )
    if ragas_summary:
        eval_run.metrics["ragas_run"] = ragas_summary
    eval_run.status = "completed" if not errors else "completed_with_errors"
    commit_job_progress(job_id, status=eval_run.status, progress=100, current_step="completed")
    session.flush()
    return eval_run
