"""Throwaway: flatten an eval-run artifact into the cells needed by §7 of
docs/implementation-report.md.

Reads ``backend/artifacts/evals/<eval_run_id>.json`` and prints the §7.1
headline table, §7.2 component-ablation rows, §7.3 by-category subgroup
table, §7.4 secondary endpoints, §7.5 RAGAS, and §7.6 representative
failure candidates as already-formatted markdown rows.

Usage:
    uv run --directory backend python -m rag_benchmarking.scripts._report_metrics \\
      --artifact backend/artifacts/evals/<eval_run_id>.json \\
      [--eval-cases-yaml backend/eval_cases/sec_filings_v1.yaml]
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml


VARIANT_LABEL = {
    "full_agentic": "full_agentic",
    "full_agentic_no_hyde": "−hyde",
    "full_agentic_no_reranker": "−reranker",
    "full_agentic_no_hyde_no_reranker": "−hyde −reranker",
    "single_pass": "single_pass",
    "single_pass_semantic_only": "single_pass −fts",
    "single_pass_lexical_only": "single_pass −vector",
    "single_pass_no_reranker": "single_pass −reranker",
    "single_pass_no_decomposition": "single_pass −decomposition",
    "llm_only": "llm_only",
}

REPORT_CATEGORIES = [
    ("single_company_lookup", 35),
    ("table_lookup", 11),
    ("trend", 8),
    ("cross_company_comparison", 8),
    ("sector_synthesis", 7),
    ("multi_part", 10),
    ("latest_filing", 8),
    ("insufficient_evidence", 7),
    ("refusal", 5),
]


def _fmt(value: float | None, *, places: int = 3) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{value:.{places}f}"


def _fmt_pct(value: float | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    return f"{value * 100:.1f}%"


def _fmt_ci(low: float | None, high: float | None, *, places: int = 3) -> str:
    if low is None or high is None:
        return "—"
    return f"({low:+.{places}f}, {high:+.{places}f})"


def _fmt_delta_with_ci(diff: float | None, low: float | None, high: float | None) -> str:
    if diff is None:
        return "—"
    return f"{diff:+.3f} {_fmt_ci(low, high)}"


def _fmt_q(q: float | None) -> str:
    if q is None or (isinstance(q, float) and math.isnan(q)):
        return "—"
    if q < 0.001:
        return f"{q:.1e}"
    return f"{q:.3f}"


def _geometric_mean(values: list[float]) -> float | None:
    cleaned = [float(v) for v in values if isinstance(v, (int, float)) and v > 0 and math.isfinite(v)]
    if not cleaned:
        return None
    return math.exp(statistics.fmean(math.log(v) for v in cleaned))


def _load_artifact(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _load_case_yaml(path: Path) -> dict[str, dict[str, Any]]:
    raw = yaml.safe_load(path.read_text())
    cases = raw.get("cases") if isinstance(raw, dict) else raw
    if not isinstance(cases, list):
        return {}
    return {c.get("case_key"): c for c in cases if isinstance(c, dict) and c.get("case_key")}


def _index_pair_results(ablation: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    """(metric, treatment) -> PairResult dict.

    The artifact's pair_results all share ``baseline = full_agentic`` since the
    runner picks ``full_agentic`` as the baseline. Indexing by
    (metric, treatment) is enough.
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for pair in ablation.get("pair_results") or []:
        if not isinstance(pair, dict):
            continue
        if pair.get("subgroup"):
            continue
        out[(pair.get("metric"), pair.get("treatment"))] = pair
    return out


def _by_category_for_variant(variant_agg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return variant_agg.get("by_category") or {}


def _per_variant_metrics(artifact: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metrics = artifact.get("metrics") or {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in metrics.items():
        if not isinstance(value, dict):
            continue
        if key in {"ablation", "judge_diagnostics", "pairing_skew", "ingestion_diagnostics"}:
            continue
        if key in VARIANT_LABEL or value.get("retrieval_mode"):
            out[key] = value
    return out


def _results_for_variant(artifact: dict[str, Any], variant: str) -> list[dict[str, Any]]:
    rows = artifact.get("results") or []
    return [r for r in rows if isinstance(r, dict) and r.get("variant_name") == variant]


def _print_section(title: str) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)


def section_7_1(artifact: dict[str, Any]) -> None:
    """§7.1 Headline: full_agentic vs llm_only."""
    _print_section("§7.1 Headline (full_agentic vs llm_only)")
    ablation = artifact.get("metrics", {}).get("ablation") or {}
    pairs = _index_pair_results(ablation)
    per_variant = _per_variant_metrics(artifact)
    fa = per_variant.get("full_agentic", {})
    lo = per_variant.get("llm_only", {})
    rows = [
        ("answer_accuracy", "answer_accuracy", "answer_accuracy_rate"),
        ("strict_recall_at_10", "strict_recall_at_10", "avg_evidence_recall_at_10"),
        ("expected_contains", "expected_contains", "expected_contains_rate"),
    ]
    print("| Endpoint | full_agentic | llm_only | Δ | One-sided p (BH-adj) | Cliff's δ |")
    print("| --- | --- | --- | --- | --- | --- |")
    for label, metric, agg_key in rows:
        pair = pairs.get((metric, "llm_only"))
        fa_mean = fa.get(agg_key)
        lo_mean = lo.get(agg_key)
        if pair is None:
            print(f"| `{label}` | {_fmt(fa_mean)} | {_fmt(lo_mean)} | — | — | — |")
            continue
        # llm_only has no retrieval — recall is n/a there.
        treat_display = "n/a (no retrieval)" if metric == "strict_recall_at_10" else _fmt(pair.get("mean_treatment"))
        base_display = _fmt(pair.get("mean_baseline"))
        # diff is treatment − baseline in the analyzer; we want baseline − treatment
        diff = pair.get("diff")
        diff_signed = -diff if diff is not None else None
        # CI also flips sign + swap; ci is on (treatment - baseline) so for baseline - treatment we get (-ci_high, -ci_low)
        ci_low = pair.get("ci_low")
        ci_high = pair.get("ci_high")
        flipped_low = -ci_high if ci_high is not None else None
        flipped_high = -ci_low if ci_low is not None else None
        # Cliff's δ on (a=baseline, b=treatment) — see paired_stats. Sign convention is treatment vs baseline.
        cliffs = pair.get("cliffs_delta")
        # For "higher is better" endpoints, "baseline > treatment" implies positive Cliff's δ flipped.
        cliffs_signed = -cliffs if cliffs is not None else None
        print(
            f"| `{label}` | {base_display} | {treat_display} | "
            f"{_fmt_delta_with_ci(diff_signed, flipped_low, flipped_high)} | "
            f"{_fmt_q(pair.get('q_value'))} | {_fmt(cliffs_signed)} |"
        )


def section_7_2(artifact: dict[str, Any]) -> None:
    """§7.2 Component ablations (baseline = full_agentic)."""
    _print_section("§7.2 Component ablations (baseline = full_agentic)")
    ablation = artifact.get("metrics", {}).get("ablation") or {}
    pairs = _index_pair_results(ablation)
    treatments = [
        "full_agentic_no_hyde",
        "full_agentic_no_reranker",
        "full_agentic_no_hyde_no_reranker",
        "single_pass",
        "single_pass_semantic_only",
        "single_pass_lexical_only",
        "single_pass_no_reranker",
        "single_pass_no_decomposition",
    ]
    print("| Knockout | Δ answer_accuracy (95% CI) | Δ strict_recall_at_10 (95% CI) | Δ expected_contains (95% CI) | BH-adj q (answer_accuracy) |")
    print("| --- | --- | --- | --- | --- |")
    for treatment in treatments:
        label = VARIANT_LABEL.get(treatment, treatment)
        row = [f"| `{label}`"]
        q_to_show = None
        for metric in ("answer_accuracy", "strict_recall_at_10", "expected_contains"):
            pair = pairs.get((metric, treatment))
            if pair is None:
                row.append(" — ")
                continue
            diff = pair.get("diff")
            diff_signed = -diff if diff is not None else None
            ci_low = pair.get("ci_low")
            ci_high = pair.get("ci_high")
            flipped_low = -ci_high if ci_high is not None else None
            flipped_high = -ci_low if ci_low is not None else None
            row.append(f" {_fmt_delta_with_ci(diff_signed, flipped_low, flipped_high)} ")
            if metric == "answer_accuracy":
                q_to_show = pair.get("q_value")
        row.append(f" {_fmt_q(q_to_show)} ")
        print("|".join(row) + "|")


def section_7_3(artifact: dict[str, Any]) -> None:
    """§7.3 By category (subgroup table)."""
    _print_section("§7.3 By category subgroup")
    per_variant = _per_variant_metrics(artifact)
    fa_by_cat = _by_category_for_variant(per_variant.get("full_agentic", {}))
    lo_by_cat = _by_category_for_variant(per_variant.get("llm_only", {}))
    print("| Category | N | answer_accuracy (full_agentic) | answer_accuracy (llm_only) | Δ |")
    print("| --- | --- | --- | --- | --- |")
    for cat, expected_n in REPORT_CATEGORIES:
        fa_cell = fa_by_cat.get(cat, {})
        lo_cell = lo_by_cat.get(cat, {})
        fa_acc = fa_cell.get("answer_accuracy_rate")
        lo_acc = lo_cell.get("answer_accuracy_rate")
        # case_count comes from the aggregator and may differ from the report's
        # historical N if some cases are inelig­ible. Show actual.
        n_actual = fa_cell.get("case_count") or expected_n
        diff = (fa_acc - lo_acc) if (fa_acc is not None and lo_acc is not None) else None
        print(f"| `{cat}` | {n_actual} | {_fmt(fa_acc)} | {_fmt(lo_acc)} | {('—' if diff is None else f'{diff:+.3f}')} |")


def section_7_4(artifact: dict[str, Any]) -> None:
    """§7.4 Secondary endpoints (uncorrected)."""
    _print_section("§7.4 Secondary endpoints (uncorrected)")
    per_variant = _per_variant_metrics(artifact)
    fa = per_variant.get("full_agentic", {})
    sp = per_variant.get("single_pass", {})

    # Geometric means for latency_ms and cost_usd come from per-case rows.
    fa_rows = _results_for_variant(artifact, "full_agentic")
    sp_rows = _results_for_variant(artifact, "single_pass")
    fa_lat_g = _geometric_mean([r.get("latency_ms") for r in fa_rows if isinstance(r.get("latency_ms"), (int, float))])
    sp_lat_g = _geometric_mean([r.get("latency_ms") for r in sp_rows if isinstance(r.get("latency_ms"), (int, float))])

    def _row_cost(rows: list[dict[str, Any]]) -> list[float]:
        out: list[float] = []
        for r in rows:
            cost = r.get("cost_estimate")
            if isinstance(cost, dict):
                total = sum(float(v) for v in cost.values() if isinstance(v, (int, float)))
                if total > 0:
                    out.append(total)
        return out

    fa_cost_g = _geometric_mean(_row_cost(fa_rows))
    sp_cost_g = _geometric_mean(_row_cost(sp_rows))

    rows: list[tuple[str, str, float | None, float | None, str]] = [
        ("mrr", "avg_mrr", fa.get("avg_mrr"), sp.get("avg_mrr"), "higher better"),
        ("page_evidence_f1", "avg_page_evidence_f1", fa.get("avg_page_evidence_f1"), sp.get("avg_page_evidence_f1"), "higher better"),
        ("citation_validity", "citation_validity_rate", fa.get("citation_validity_rate"), sp.get("citation_validity_rate"), "higher better"),
        ("citation_coverage", "citation_coverage_rate", fa.get("citation_coverage_rate"), sp.get("citation_coverage_rate"), "higher better"),
        ("metadata_filter_correctness", "metadata_filter_correctness_rate", fa.get("metadata_filter_correctness_rate"), sp.get("metadata_filter_correctness_rate"), "higher better"),
        ("latency_ms (geometric mean)", "", fa_lat_g, sp_lat_g, "lower better"),
        ("cost_usd (geometric mean per case)", "", fa_cost_g, sp_cost_g, "lower better"),
    ]
    print("| Endpoint | full_agentic | single_pass | Direction |")
    print("| --- | --- | --- | --- |")
    for label, _key, fa_v, sp_v, direction in rows:
        if "latency" in label:
            fa_d = f"{fa_v:.0f} ms" if isinstance(fa_v, (int, float)) else "—"
            sp_d = f"{sp_v:.0f} ms" if isinstance(sp_v, (int, float)) else "—"
        elif "cost" in label:
            fa_d = f"${fa_v:.4f}" if isinstance(fa_v, (int, float)) else "—"
            sp_d = f"${sp_v:.4f}" if isinstance(sp_v, (int, float)) else "—"
        else:
            fa_d = _fmt(fa_v)
            sp_d = _fmt(sp_v)
        print(f"| `{label}` | {fa_d} | {sp_d} | {direction} |")


def section_7_5(artifact: dict[str, Any]) -> None:
    """§7.5 Informational RAGAS judge."""
    _print_section("§7.5 Informational (RAGAS judge)")
    per_variant = _per_variant_metrics(artifact)
    fa = per_variant.get("full_agentic", {})
    judge = fa.get("judge_diagnostics") or {}
    ragas = judge.get("ragas") if isinstance(judge, dict) else None
    print("| Endpoint | full_agentic | Notes |")
    print("| --- | --- | --- |")
    if not ragas:
        for ep in ("faithfulness", "answer_relevancy", "context_precision", "context_recall"):
            print(f"| `{ep}` | not run | RAGAS judge disabled or absent |")
        return
    for ep, note in (
        ("faithfulness", "informational; LLM judge"),
        ("answer_relevancy", "informational"),
        ("context_precision", "informational"),
        ("context_recall", "informational"),
    ):
        print(f"| `{ep}` | {_fmt(ragas.get(ep))} | {note} |")


def section_7_6(artifact: dict[str, Any], cases: dict[str, dict[str, Any]]) -> None:
    """§7.6 representative failure modes — pick up to 9 (one per category)."""
    _print_section("§7.6 Representative failure candidates (full_agentic answer_accuracy < 0.5)")
    fa_rows = _results_for_variant(artifact, "full_agentic")
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in fa_rows:
        m = row.get("metrics") or {}
        eligible = m.get("answer_gold_eligible")
        if eligible is False:
            # for refusal / insufficient cases, "passed" is the right signal
            passed = m.get("passed")
            if passed is False:
                by_cat[m.get("category") or "uncategorized"].append(row)
            continue
        acc = m.get("answer_accuracy")
        if isinstance(acc, (int, float)) and acc < 0.5:
            by_cat[m.get("category") or "uncategorized"].append(row)
    print(f"Total failures: {sum(len(v) for v in by_cat.values())}")
    # Pick worst (lowest accuracy) per category, prioritising rubric-heavy categories first
    category_priority = [c for c, _ in REPORT_CATEGORIES]
    picked: list[dict[str, Any]] = []
    seen_cases: set[str] = set()
    for cat in category_priority:
        rows = by_cat.get(cat) or []
        if not rows:
            continue
        rows = sorted(rows, key=lambda r: ((r.get("metrics") or {}).get("answer_accuracy") or 1.0))
        for r in rows:
            cid = (r.get("metrics") or {}).get("case_key") or r.get("eval_case_id")
            if cid in seen_cases:
                continue
            picked.append(r)
            seen_cases.add(cid)
            break
    # If we have fewer than 9, pad with worst remaining failures
    pool = sorted(
        (r for rows in by_cat.values() for r in rows),
        key=lambda r: ((r.get("metrics") or {}).get("answer_accuracy") or 1.0),
    )
    for r in pool:
        cid = (r.get("metrics") or {}).get("case_key") or r.get("eval_case_id")
        if cid in seen_cases:
            continue
        picked.append(r)
        seen_cases.add(cid)
        if len(picked) >= 9:
            break
    for row in picked[:9]:
        m = row.get("metrics") or {}
        case_key = m.get("case_key") or row.get("eval_case_id")
        category = m.get("category")
        case_def = cases.get(case_key, {})
        question = case_def.get("question") or "(question missing)"
        expected = case_def.get("expected_answer") or case_def.get("expected_answer_spec") or "(no gold)"
        answer = row.get("answer") or "(no answer)"
        answer_trimmed = (answer[:240] + "…") if isinstance(answer, str) and len(answer) > 240 else answer
        err = row.get("error")
        acc = m.get("answer_accuracy")
        ev = m.get("evidence_recall_at_10")
        print("---")
        print(f"case_key: {case_key}")
        print(f"category: {category}")
        print(f"answer_accuracy: {acc}, evidence_recall_at_10: {ev}, error: {err}")
        print(f"Q: {question}")
        print(f"Expected: {expected}")
        print(f"System: {answer_trimmed}")


def section_overview(artifact: dict[str, Any]) -> None:
    _print_section("Overview")
    metrics = artifact.get("metrics") or {}
    print(f"eval_run_id: {artifact.get('id')}")
    print(f"dataset_id : {artifact.get('dataset_id')}")
    print(f"status     : {artifact.get('status')}")
    print(f"variants   : {metrics.get('variants_used')}")
    print(f"results    : {len(artifact.get('results') or [])}")
    print(f"errors     : {metrics.get('errors') or '(none)'}")
    print(f"pass_rate  : {metrics.get('pass_rate')} ({metrics.get('pass_count')}/{metrics.get('pass_eligible_count')})")
    print(f"total_cost_usd: {metrics.get('total_cost_usd')}")
    print(f"avg_latency_ms (run-wide): {metrics.get('avg_latency_ms')}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument(
        "--eval-cases-yaml",
        type=Path,
        default=Path("backend/eval_cases/sec_filings_v1.yaml"),
    )
    args = parser.parse_args()
    artifact = _load_artifact(args.artifact)
    cases = _load_case_yaml(args.eval_cases_yaml) if args.eval_cases_yaml.exists() else {}
    section_overview(artifact)
    section_7_1(artifact)
    section_7_2(artifact)
    section_7_3(artifact)
    section_7_4(artifact)
    section_7_5(artifact)
    section_7_6(artifact, cases)


if __name__ == "__main__":
    main()
