"""Per-variant and run-wide aggregation over eval-result rows.

Hosted in ``rag_common`` so the API image (which deliberately excludes
``rag_evaluation_worker`` to stay lean — see ``backend/Dockerfile``) can
recompute aggregates on the read path without pulling in the worker's
heavy deps (ragas, openai, docling). The eval worker, the
``backfill_eval_metrics`` script, and the API serializer all import from
here.

Pure data-shaping logic: takes ``EvalResult`` rows (or their ``metrics``
dicts) and returns aggregate dicts. No I/O, no LLM calls. Anything that
needs scoring/judging is upstream of this module — by the time
``aggregate_metrics`` runs, every per-case metric is already a plain
``dict`` on the row.
"""

import math
import random
from collections import defaultdict
from typing import Any

from rag_common.db import models
from rag_common.enums import VerificationStatus


def bootstrap_mean_ci(values: list[float], *, seed: int, samples: int = 500) -> list[float] | None:
    """Two-sided 95% bootstrap CI of the mean.

    Returns ``None`` for an empty input and a degenerate ``[v, v]`` interval
    for a single observation. Seeded for reproducibility — the same input +
    seed always yields the same interval so the diff against a prior run is
    deterministic.
    """
    if not values:
        return None
    if len(values) == 1:
        return [values[0], values[0]]
    rng = random.Random(seed)  # noqa: S311 - deterministic bootstrap sampling, not security-sensitive.
    means: list[float] = []
    for _ in range(samples):
        draw = [values[rng.randrange(len(values))] for _ in values]
        means.append(sum(draw) / len(draw))
    means.sort()
    lower = means[int(0.025 * (len(means) - 1))]
    upper = means[int(0.975 * (len(means) - 1))]
    return [lower, upper]


def aggregate_metrics(results: list[models.EvalResult], *, seed: int = 1729) -> dict[str, Any]:
    """Roll per-result rows into per-variant + run-wide aggregates.

    Buckets on ``variant_name`` when present, falling back to
    ``retrieval_mode`` so legacy rows (pre-variants) still aggregate. Each
    bucket gets a full ``_summary_for_metrics`` block plus latency, cost,
    token, judge-diagnostic, and category/difficulty/tag breakdowns.
    """
    by_mode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_mode_results: dict[str, list[models.EvalResult]] = defaultdict(list)
    for result in results:
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
    # Top-level pass/latency rollups for the UI's run-wide KPI tiles. These
    # weight every eligible case equally regardless of variant, which is the
    # right denominator for "did this run pass overall".
    all_metrics: list[dict[str, Any]] = []
    for bucket in by_mode.values():
        all_metrics.extend(bucket)
    all_pass_values = [
        1.0 if metric.get("passed") is True else 0.0
        for metric in all_metrics
        if metric.get("answer_gold_eligible") is True and isinstance(metric.get("passed"), bool)
    ]
    if all_pass_values:
        aggregate["pass_rate"] = sum(all_pass_values) / len(all_pass_values)
        aggregate["pass_count"] = int(sum(all_pass_values))
        aggregate["pass_eligible_count"] = len(all_pass_values)
    all_latencies = [
        metric["latency_ms"] for metric in all_metrics if isinstance(metric.get("latency_ms"), (int, float))
    ]
    if all_latencies:
        aggregate["avg_latency_ms"] = sum(all_latencies) / len(all_latencies)
    return aggregate


def _summary_for_metrics(metrics: list[dict[str, Any]], *, seed: int) -> dict[str, Any]:
    answer_values = _eligible_values(metrics, key="answer_accuracy", eligible_key="answer_gold_eligible")
    evidence_recall_values = _eligible_values(
        metrics, key="evidence_recall_at_10", eligible_key="evidence_gold_eligible"
    )
    citation_gold_recall_values = _eligible_values(
        metrics, key="citation_gold_recall", eligible_key="evidence_gold_eligible"
    )
    # ``passed`` is a tri-valued field (True/False/None for non-eligible); we
    # convert eligible bools to floats so the existing CI/mean helpers work.
    pass_values = [
        1.0 if metric.get("passed") is True else 0.0
        for metric in metrics
        if metric.get("answer_gold_eligible") is True and isinstance(metric.get("passed"), bool)
    ]
    pass_count = sum(1 for v in pass_values if v == 1.0)
    summary: dict[str, Any] = {
        "case_count": len(metrics),
        "diagnostic_case_count": len(metrics),
        "scientific_case_count": sum(1 for metric in metrics if metric.get("gold_eligible") is True),
        "answer_scientific_case_count": len(answer_values),
        "evidence_scientific_case_count": len(evidence_recall_values),
        "draft_case_count": sum(
            1 for metric in metrics if metric.get("verification_status") != VerificationStatus.VERIFIED
        ),
        "answer_accuracy_rate": _mean_list(answer_values),
        "answer_accuracy_ci_95": bootstrap_mean_ci(answer_values, seed=seed),
        "pass_rate": _mean_list(pass_values),
        "pass_count": pass_count,
        "pass_eligible_count": len(pass_values),
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
        "avg_chunk_evidence_f1": _mean_metric(metrics, "chunk_evidence_f1"),
        "avg_evidence_recall_at_5": _mean_metric(metrics, "evidence_recall_at_5"),
        "avg_evidence_mrr": _mean_metric(metrics, "evidence_mrr"),
        "avg_evidence_page_f1": _mean_metric(metrics, "evidence_page_f1"),
        "avg_evidence_chunk_f1": _mean_metric(metrics, "evidence_chunk_f1"),
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
