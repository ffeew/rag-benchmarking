"""Paired ablation analysis: build per-case matrices, run tests, render reports.

Consumes an eval-run artifact (the JSON written by ``run_eval.py``) or any dict
matching the same shape, produces an :class:`AblationReport` with paired effect
sizes, paired bootstrap CIs of mean differences, Wilcoxon / McNemar tests, and
Benjamini-Hochberg FDR-adjusted q-values across the primary endpoint family.

Pre-registration lives at ``docs/eval/ablation_v1_plan.md``.
"""

import csv
import io
import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from rag_evaluation.paired_stats import (
    benjamini_hochberg,
    cliffs_delta,
    mcnemar_midp,
    paired_bootstrap_diff_ci,
    paired_cohens_d,
    wilcoxon_signed_rank,
)

# --- Endpoint catalogue ----------------------------------------------------

PRIMARY_ENDPOINTS_DEFAULT: tuple[str, ...] = (
    "answer_accuracy",
    "strict_recall_at_10",
)

# Mapping from "logical" endpoint name -> per-case metric key. Some endpoints
# are computed against multiple stored keys (older artifacts may use the
# unstrict ``evidence_recall_at_10`` field); the analyzer prefers the strict
# one first and falls back to the legacy key when only it is present.
ENDPOINT_KEYS: dict[str, tuple[str, ...]] = {
    "answer_accuracy": ("answer_accuracy",),
    "strict_recall_at_10": ("strict_recall_at_10", "evidence_recall_at_10"),
    "expected_contains": ("expected_contains",),
    "mrr": ("mrr",),
    "strict_mrr": ("strict_mrr", "evidence_mrr"),
    "page_evidence_f1": ("page_evidence_f1",),
    "chunk_evidence_f1": ("chunk_evidence_f1",),
    "strict_chunk_f1": ("strict_chunk_f1", "evidence_chunk_f1"),
    "citation_validity": ("citation_validity",),
    "citation_coverage": ("citation_coverage",),
    "citation_gold_recall": ("citation_gold_recall",),
    "citation_gold_precision": ("citation_gold_precision",),
    "metadata_filter_correctness": ("metadata_filter_correctness",),
    "latency_ms": ("latency_ms",),
}

SECONDARY_ENDPOINTS_DEFAULT: tuple[str, ...] = (
    "expected_contains",
    "mrr",
    "strict_mrr",
    "page_evidence_f1",
    "chunk_evidence_f1",
    "citation_validity",
    "citation_coverage",
    "citation_gold_recall",
    "citation_gold_precision",
    "metadata_filter_correctness",
)

LOG_ENDPOINTS: frozenset[str] = frozenset({"latency_ms", "cost_usd"})
BINARY_ENDPOINTS: frozenset[str] = frozenset({"expected_contains"})

TestKind = Literal["wilcoxon", "wilcoxon_log", "mcnemar_midp"]


# --- Data types ------------------------------------------------------------


@dataclass(frozen=True)
class PairResult:
    """One paired contrast (baseline vs treatment) on one metric."""

    metric: str
    baseline: str
    treatment: str
    n_paired: int
    mean_baseline: float
    mean_treatment: float
    diff: float
    ci_low: float
    ci_high: float
    wilcoxon_stat: float | None
    p_value: float | None
    q_value: float | None
    cliffs_delta: float | None
    cohens_d: float | None
    test: TestKind
    alternative: Literal["two-sided", "greater", "less"]
    primary: bool
    subgroup: str | None = None
    geometric_mean_ratio: float | None = None


@dataclass(frozen=True)
class AblationReport:
    run_id: str | None
    baseline: str
    variants: list[str]
    primary_endpoints: list[str]
    secondary_endpoints: list[str]
    pair_results: list[PairResult]
    subgroup_results: dict[str, list[PairResult]] = field(default_factory=dict)
    case_count: int = 0
    excluded_cases: dict[str, int] = field(default_factory=dict)
    methodology_notes: str = ""
    pairing_skew: dict[str, Any] = field(default_factory=dict)


# --- Helpers ----------------------------------------------------------------


def _per_case_rows(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the flat list of per-case result dicts from an artifact."""

    results = artifact.get("results") or []
    if not isinstance(results, list):
        return []
    return [row for row in results if isinstance(row, dict)]


def _per_case_cost(row: dict[str, Any]) -> float | None:
    cost = row.get("cost_estimate")
    if isinstance(cost, dict):
        total = 0.0
        any_value = False
        for value in cost.values():
            if isinstance(value, (int, float)):
                total += float(value)
                any_value = True
        return total if any_value else None
    if isinstance(cost, (int, float)):
        return float(cost)
    return None


def _resolve_endpoint_value(row: dict[str, Any], endpoint: str) -> float | None:
    """Pull the per-case metric for an endpoint, with key fallbacks."""

    if endpoint == "cost_usd":
        return _per_case_cost(row)
    if endpoint == "latency_ms":
        latency = row.get("latency_ms")
        return float(latency) if isinstance(latency, (int, float)) else None
    keys = ENDPOINT_KEYS.get(endpoint, (endpoint,))
    metrics = row.get("metrics") or {}
    if not isinstance(metrics, dict):
        return None
    for key in keys:
        if key in metrics and isinstance(metrics[key], (int, float)):
            return float(metrics[key])
    return None


def _variant_of(row: dict[str, Any]) -> str | None:
    """variant_name takes precedence; fall back to retrieval_mode for legacy rows."""

    return row.get("variant_name") or row.get("retrieval_mode")


def build_paired_matrix(
    rows: Sequence[dict[str, Any]],
    *,
    endpoint: str,
    variants: Sequence[str],
) -> tuple[list[str], dict[str, list[float]]]:
    """Build a paired matrix keyed by variant.

    Returns ``(case_ids, matrix)`` where ``matrix[variant][i]`` is the metric
    for ``case_ids[i]`` and that variant. Cases for which any requested variant
    is missing or non-finite are dropped (paired same-N).
    """

    per_variant: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rows:
        variant = _variant_of(row)
        case_id = row.get("eval_case_id")
        if variant is None or not isinstance(case_id, str):
            continue
        if variant not in variants:
            continue
        value = _resolve_endpoint_value(row, endpoint)
        if value is None or not math.isfinite(value):
            continue
        per_variant[variant][case_id] = value
    case_sets = [set(per_variant.get(variant, {}).keys()) for variant in variants]
    if not case_sets:
        return [], {variant: [] for variant in variants}
    shared = set.intersection(*case_sets) if all(case_sets) else set()
    ordered_cases = sorted(shared)
    matrix = {variant: [per_variant[variant][case_id] for case_id in ordered_cases] for variant in variants}
    return ordered_cases, matrix


def _safe_log(value: float, *, eps: float = 1e-9) -> float:
    return math.log(max(value, eps))


def _run_pair(
    baseline_values: list[float],
    treatment_values: list[float],
    *,
    metric: str,
    baseline: str,
    treatment: str,
    primary: bool,
    alternative: Literal["two-sided", "greater", "less"] = "two-sided",
    seed: int = 1729,
    bootstrap_samples: int = 5000,
    subgroup: str | None = None,
) -> PairResult:
    """Compute the test + effect sizes appropriate to the metric type."""

    n_paired = len(baseline_values)
    if metric in BINARY_ENDPOINTS:
        a_bin = [1 if v >= 0.5 else 0 for v in baseline_values]
        b_bin = [1 if v >= 0.5 else 0 for v in treatment_values]
        b_count, c_count, p_two = mcnemar_midp(a_bin, b_bin)
        diff = (sum(b_bin) - sum(a_bin)) / max(n_paired, 1)
        _, ci_lo, ci_hi = paired_bootstrap_diff_ci(
            [float(v) for v in a_bin], [float(v) for v in b_bin], seed=seed, samples=bootstrap_samples
        )
        return PairResult(
            metric=metric,
            baseline=baseline,
            treatment=treatment,
            n_paired=n_paired,
            mean_baseline=sum(a_bin) / max(n_paired, 1),
            mean_treatment=sum(b_bin) / max(n_paired, 1),
            diff=diff,
            ci_low=ci_lo,
            ci_high=ci_hi,
            wilcoxon_stat=float(b_count - c_count),
            p_value=p_two,
            q_value=None,
            cliffs_delta=cliffs_delta(baseline_values, treatment_values),
            cohens_d=paired_cohens_d(baseline_values, treatment_values),
            test="mcnemar_midp",
            alternative=alternative,
            primary=primary,
            subgroup=subgroup,
        )

    if metric in LOG_ENDPOINTS:
        a_log = [_safe_log(v) for v in baseline_values]
        b_log = [_safe_log(v) for v in treatment_values]
        diff_log, ci_lo_log, ci_hi_log = paired_bootstrap_diff_ci(a_log, b_log, seed=seed, samples=bootstrap_samples)
        w, p = wilcoxon_signed_rank(a_log, b_log, alternative=alternative)
        return PairResult(
            metric=metric,
            baseline=baseline,
            treatment=treatment,
            n_paired=n_paired,
            mean_baseline=sum(baseline_values) / max(n_paired, 1),
            mean_treatment=sum(treatment_values) / max(n_paired, 1),
            diff=diff_log,
            ci_low=ci_lo_log,
            ci_high=ci_hi_log,
            wilcoxon_stat=w,
            p_value=p,
            q_value=None,
            cliffs_delta=cliffs_delta(a_log, b_log),
            cohens_d=paired_cohens_d(a_log, b_log),
            test="wilcoxon_log",
            alternative=alternative,
            primary=primary,
            subgroup=subgroup,
            geometric_mean_ratio=math.exp(diff_log),
        )

    diff, ci_lo, ci_hi = paired_bootstrap_diff_ci(
        baseline_values, treatment_values, seed=seed, samples=bootstrap_samples
    )
    w, p = wilcoxon_signed_rank(baseline_values, treatment_values, alternative=alternative)
    return PairResult(
        metric=metric,
        baseline=baseline,
        treatment=treatment,
        n_paired=n_paired,
        mean_baseline=sum(baseline_values) / max(n_paired, 1),
        mean_treatment=sum(treatment_values) / max(n_paired, 1),
        diff=diff,
        ci_low=ci_lo,
        ci_high=ci_hi,
        wilcoxon_stat=w,
        p_value=p,
        q_value=None,
        cliffs_delta=cliffs_delta(baseline_values, treatment_values),
        cohens_d=paired_cohens_d(baseline_values, treatment_values),
        test="wilcoxon",
        alternative=alternative,
        primary=primary,
        subgroup=subgroup,
    )


def _apply_fdr(results: list[PairResult], *, q: float = 0.05) -> list[PairResult]:
    """Apply Benjamini-Hochberg across the *primary* family only."""

    indices = [i for i, r in enumerate(results) if r.primary and r.subgroup is None and r.p_value is not None]
    raw_p = [results[i].p_value or 1.0 for i in indices]
    _rejected, adjusted = benjamini_hochberg(raw_p, q=q)
    updated = list(results)
    for index, q_value in zip(indices, adjusted, strict=True):
        old = updated[index]
        updated[index] = PairResult(**{**old.__dict__, "q_value": q_value})
    return updated


def _subgroup_keys(rows: Iterable[dict[str, Any]], *, dimension: str) -> dict[str, set[str]]:
    """Map subgroup value -> set of case_ids belonging to it."""

    grouped: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        case_id = row.get("eval_case_id")
        metrics = row.get("metrics") or {}
        if not isinstance(case_id, str) or not isinstance(metrics, dict):
            continue
        value = metrics.get(dimension)
        if isinstance(value, str) and value:
            grouped[value].add(case_id)
    return grouped


# --- Public entry point ----------------------------------------------------


def run_ablation_analysis(
    artifact: dict[str, Any],
    *,
    baseline: str = "full_agentic",
    primary_endpoints: Sequence[str] = PRIMARY_ENDPOINTS_DEFAULT,
    secondary_endpoints: Sequence[str] = SECONDARY_ENDPOINTS_DEFAULT,
    cost_latency_endpoints: Sequence[str] = ("latency_ms", "cost_usd"),
    seed: int = 1729,
    bootstrap_samples: int = 5000,
    fdr_q: float = 0.05,
    one_sided: bool = True,
) -> AblationReport:
    """Run the full paired analysis on an eval-run artifact and return the report."""

    rows = _per_case_rows(artifact)
    metrics_aggregate = artifact.get("metrics") or {}
    variants = sorted({_variant_of(row) or "" for row in rows if _variant_of(row) is not None} - {""})
    if baseline not in variants:
        raise ValueError(f"baseline {baseline!r} not in artifact variants {variants!r}")
    treatments = [v for v in variants if v != baseline]

    all_pairs: list[PairResult] = []
    excluded: dict[str, int] = {}

    def _do_endpoint(endpoint: str, *, primary: bool) -> None:
        case_ids, matrix = build_paired_matrix(rows, endpoint=endpoint, variants=variants)
        for treatment in treatments:
            baseline_values = matrix.get(baseline, [])
            treatment_values = matrix.get(treatment, [])
            key = f"{endpoint}:{baseline}->{treatment}"
            excluded[key] = len([row for row in rows if _variant_of(row) in {baseline, treatment}]) // 2 - len(case_ids)
            if not baseline_values:
                continue
            # Pre-registered hypothesis is `baseline > treatment`. In the
            # ``(a=baseline, b=treatment)`` framing this means testing whether
            # ``(b - a) < 0``, i.e. ``alternative="less"`` for primaries.
            alternative: Literal["two-sided", "greater", "less"] = "less" if (primary and one_sided) else "two-sided"
            all_pairs.append(
                _run_pair(
                    baseline_values,
                    treatment_values,
                    metric=endpoint,
                    baseline=baseline,
                    treatment=treatment,
                    primary=primary,
                    alternative=alternative,
                    seed=seed,
                    bootstrap_samples=bootstrap_samples,
                )
            )

    for endpoint in primary_endpoints:
        _do_endpoint(endpoint, primary=True)
    for endpoint in secondary_endpoints:
        _do_endpoint(endpoint, primary=False)
    for endpoint in cost_latency_endpoints:
        _do_endpoint(endpoint, primary=False)

    pairs_with_q = _apply_fdr(all_pairs, q=fdr_q)

    subgroup_results: dict[str, list[PairResult]] = {}
    for dimension in ("category", "difficulty"):
        subgroup_results.update(
            _subgroup_pairs(
                rows,
                dimension=dimension,
                baseline=baseline,
                treatments=treatments,
                primary_endpoints=primary_endpoints,
                seed=seed,
                bootstrap_samples=bootstrap_samples,
            )
        )

    notes = _methodology_notes(
        case_count=len({row.get("eval_case_id") for row in rows if row.get("eval_case_id")}),
        bootstrap_samples=bootstrap_samples,
        fdr_q=fdr_q,
        seed=seed,
        primary_endpoints=list(primary_endpoints),
        secondary_endpoints=list(secondary_endpoints),
        cost_latency_endpoints=list(cost_latency_endpoints),
    )

    return AblationReport(
        run_id=artifact.get("id"),
        baseline=baseline,
        variants=variants,
        primary_endpoints=list(primary_endpoints),
        secondary_endpoints=list(secondary_endpoints) + list(cost_latency_endpoints),
        pair_results=pairs_with_q,
        subgroup_results=subgroup_results,
        case_count=len({row.get("eval_case_id") for row in rows if row.get("eval_case_id")}),
        excluded_cases=excluded,
        methodology_notes=notes,
        pairing_skew=(
            metrics_aggregate.get("pairing_skew", {})
            if isinstance(metrics_aggregate, dict) and isinstance(metrics_aggregate.get("pairing_skew"), dict)
            else {}
        ),
    )


def _subgroup_pairs(
    rows: list[dict[str, Any]],
    *,
    dimension: str,
    baseline: str,
    treatments: list[str],
    primary_endpoints: Sequence[str],
    seed: int,
    bootstrap_samples: int,
) -> dict[str, list[PairResult]]:
    """Build paired contrasts restricted to each subgroup. Exploratory only.

    The analyzer flags these in the report header as not FDR-corrected.
    """

    keys = _subgroup_keys(rows, dimension=dimension)
    out: dict[str, list[PairResult]] = {}
    for value, case_ids in keys.items():
        if not case_ids:
            continue
        scoped = [row for row in rows if row.get("eval_case_id") in case_ids]
        bucket: list[PairResult] = []
        for endpoint in primary_endpoints:
            _, matrix = build_paired_matrix(scoped, endpoint=endpoint, variants=[baseline, *treatments])
            for treatment in treatments:
                baseline_values = matrix.get(baseline, [])
                treatment_values = matrix.get(treatment, [])
                if len(baseline_values) < 2:
                    continue
                bucket.append(
                    _run_pair(
                        baseline_values,
                        treatment_values,
                        metric=endpoint,
                        baseline=baseline,
                        treatment=treatment,
                        primary=False,
                        alternative="two-sided",
                        seed=seed,
                        bootstrap_samples=bootstrap_samples,
                        subgroup=f"{dimension}={value}",
                    )
                )
        if bucket:
            out[f"{dimension}={value}"] = bucket
    return out


def _methodology_notes(
    *,
    case_count: int,
    bootstrap_samples: int,
    fdr_q: float,
    seed: int,
    primary_endpoints: list[str],
    secondary_endpoints: list[str],
    cost_latency_endpoints: list[str],
) -> str:
    return (
        f"N paired cases: {case_count}. Bootstrap seed: {seed}, samples: {bootstrap_samples:,}. "
        f"FDR family: {len(primary_endpoints)} primary endpoints × (variants-1) treatments, "
        f"Benjamini-Hochberg q={fdr_q}. Continuous primaries: paired Wilcoxon signed-rank "
        "(continuity-corrected normal approx; exact for n≤25 when no ties), 95% paired "
        "bootstrap CI of the mean difference. Binary primaries: McNemar mid-P + paired "
        "bootstrap on the 0/1 vectors. Latency/cost: log-transform then Wilcoxon; "
        "geometric-mean ratio reported. Effect sizes: paired Cliff's δ (Romano: 0.11/0.28/0.43) "
        "and paired Cohen's d (0.2/0.5/0.8). Subgroup contrasts are exploratory and NOT "
        "FDR-corrected. RAGAS judge metrics (informational) are not part of this report."
    )


# --- Renderers --------------------------------------------------------------


def _fmt_metric(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    return f"{value:+.3f}"


def _fmt_q(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    if value < 0.001:
        return "<0.001"
    return f"{value:.3f}"


def _cliffs_tier(delta: float | None) -> str:
    if delta is None:
        return "—"
    magnitude = abs(delta)
    if magnitude < 0.11:
        return "negligible"
    if magnitude < 0.28:
        return "small"
    if magnitude < 0.43:
        return "medium"
    return "large"


def render_markdown(report: AblationReport) -> str:
    """Render the Markdown ablation report (sections 1-9 of the plan)."""

    lines: list[str] = []
    lines.append("# Ablation v1 — full_agentic component knockouts")
    lines.append("")
    lines.append(f"**Run ID**: `{report.run_id}`   **Cases**: {report.case_count}   **Baseline**: `{report.baseline}`")
    lines.append(
        f"**Pre-registration**: docs/eval/ablation_v1_plan.md   **Seed**: 1729   **Variants**: {len(report.variants)}"
    )
    if report.pairing_skew and not report.pairing_skew.get("balanced", True):
        lines.append("")
        lines.append(
            f"> Pairing skew detected: missing cases per variant = "
            f"`{report.pairing_skew.get('missing')}`. Pairs are still same-N within each "
            "metric (cases missing for either arm are dropped from the contrast)."
        )
    lines.append("")

    lines.append("## 1. Headline (primary endpoints, FDR-controlled)")
    lines.append("")
    primary_pairs = [pr for pr in report.pair_results if pr.primary and pr.subgroup is None]
    treatments = sorted({pr.treatment for pr in primary_pairs})
    if primary_pairs:
        header_cells = ["Contrast"] + [f"{ep} Δ [CI] (q)" for ep in report.primary_endpoints]
        lines.append("| " + " | ".join(header_cells) + " |")
        lines.append("| " + " | ".join("---" for _ in header_cells) + " |")
        for treatment in treatments:
            row = [f"`{report.baseline}` vs `{treatment}`"]
            for endpoint in report.primary_endpoints:
                hit = next(
                    (pr for pr in primary_pairs if pr.treatment == treatment and pr.metric == endpoint),
                    None,
                )
                if hit is None:
                    row.append("—")
                    continue
                cell = (
                    f"{_fmt_metric(hit.diff)} [{_fmt_metric(hit.ci_low)}, {_fmt_metric(hit.ci_high)}] "
                    f"(q={_fmt_q(hit.q_value)})"
                )
                row.append(cell)
            lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    lines.append("## 2. Forest plots (primary endpoints)")
    for endpoint in report.primary_endpoints:
        rows_for_endpoint = sorted(
            (pr for pr in primary_pairs if pr.metric == endpoint),
            key=lambda pr: pr.diff,
        )
        if not rows_for_endpoint:
            continue
        lines.append("")
        lines.append(f"### {endpoint} (baseline = `{report.baseline}`)")
        lines.append("")
        lines.append("```")
        lines.extend(_forest_plot(rows_for_endpoint))
        lines.append("```")
    lines.append("")

    lines.append("## 3. Secondary endpoints (uncorrected)")
    lines.append("")
    secondary_pairs = [pr for pr in report.pair_results if not pr.primary and pr.subgroup is None]
    if secondary_pairs:
        lines.append("| Metric | Contrast | Δ | 95% CI | p (raw) | Cliff's δ |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for pr in sorted(secondary_pairs, key=lambda x: (x.metric, x.treatment)):
            row = [
                pr.metric,
                f"`{pr.baseline}` vs `{pr.treatment}`",
                _fmt_metric(pr.diff),
                f"[{_fmt_metric(pr.ci_low)}, {_fmt_metric(pr.ci_high)}]",
                _fmt_q(pr.p_value),
                f"{_fmt_metric(pr.cliffs_delta)} ({_cliffs_tier(pr.cliffs_delta)})",
            ]
            lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    lines.append("## 4. Latency / cost (geometric-mean ratio)")
    lines.append("")
    log_pairs = [pr for pr in report.pair_results if pr.test == "wilcoxon_log"]
    if log_pairs:
        lines.append("| Metric | Contrast | GM ratio | 95% CI of logΔ | p (raw) |")
        lines.append("| --- | --- | --- | --- | --- |")
        for pr in sorted(log_pairs, key=lambda x: (x.metric, x.treatment)):
            ratio = pr.geometric_mean_ratio or 0.0
            row = [
                pr.metric,
                f"`{pr.baseline}` vs `{pr.treatment}`",
                f"{ratio:.3f}×",
                f"[{_fmt_metric(pr.ci_low)}, {_fmt_metric(pr.ci_high)}]",
                _fmt_q(pr.p_value),
            ]
            lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    lines.append("## 5. Subgroup analysis (exploratory, no FDR)")
    lines.append("")
    if report.subgroup_results:
        for subgroup_key in sorted(report.subgroup_results.keys()):
            entries = report.subgroup_results[subgroup_key]
            if not entries:
                continue
            lines.append(
                f"### {subgroup_key} (n_paired ∈ [{min(e.n_paired for e in entries)}, "
                f"{max(e.n_paired for e in entries)}])"
            )
            lines.append("")
            lines.append("| Metric | Contrast | Δ | 95% CI | Cliff's δ |")
            lines.append("| --- | --- | --- | --- | --- |")
            for pr in sorted(entries, key=lambda x: (x.metric, x.treatment)):
                row = [
                    pr.metric,
                    f"`{pr.baseline}` vs `{pr.treatment}`",
                    _fmt_metric(pr.diff),
                    f"[{_fmt_metric(pr.ci_low)}, {_fmt_metric(pr.ci_high)}]",
                    f"{_fmt_metric(pr.cliffs_delta)} ({_cliffs_tier(pr.cliffs_delta)})",
                ]
                lines.append("| " + " | ".join(row) + " |")
            lines.append("")
    else:
        lines.append("_No subgroup contrasts were produced (no category/difficulty signal)._")
        lines.append("")

    lines.append("## 6. Methodology footer")
    lines.append("")
    lines.append(report.methodology_notes)
    lines.append("")

    return "\n".join(lines)


def _forest_plot(pairs: list[PairResult], *, width: int = 50) -> list[str]:
    """ASCII forest plot. Asterisk = point estimate, brackets = 95% CI."""

    if not pairs:
        return []
    lo = min(pr.ci_low for pr in pairs)
    hi = max(pr.ci_high for pr in pairs)
    span = max(hi - lo, 1e-9)

    def col(value: float) -> int:
        return max(0, min(width - 1, int(round((value - lo) / span * (width - 1)))))

    rows: list[str] = []
    label_w = max(len(pr.treatment) for pr in pairs) + 2
    for pr in pairs:
        bar = [" "] * width
        ci_lo_col = col(pr.ci_low)
        ci_hi_col = col(pr.ci_high)
        center = col(pr.diff)
        for i in range(ci_lo_col, ci_hi_col + 1):
            bar[i] = "-"
        bar[ci_lo_col] = "["
        bar[ci_hi_col] = "]"
        bar[center] = "*"
        zero_col = col(0.0) if lo <= 0 <= hi else None
        if zero_col is not None and bar[zero_col] == " ":
            bar[zero_col] = "|"
        annotation = f" Δ={_fmt_metric(pr.diff)}  q={_fmt_q(pr.q_value)}"
        rows.append(f"{pr.treatment.ljust(label_w)}{''.join(bar)}{annotation}")
    axis_lo = f"{lo:+.2f}"
    axis_hi = f"{hi:+.2f}"
    axis = axis_lo + " " * max(1, width - len(axis_lo) - len(axis_hi)) + axis_hi
    rows.append(" " * label_w + axis)
    return rows


def render_csv(report: AblationReport) -> str:
    """Render the long-form per-pair CSV (one row per metric × contrast × subgroup)."""

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "metric",
            "baseline",
            "treatment",
            "subgroup",
            "n_paired",
            "mean_baseline",
            "mean_treatment",
            "diff",
            "ci_low",
            "ci_high",
            "test",
            "wilcoxon_stat",
            "p_value",
            "q_value",
            "cliffs_delta",
            "cohens_d",
            "primary",
            "geometric_mean_ratio",
        ]
    )
    all_results = list(report.pair_results) + [pr for entries in report.subgroup_results.values() for pr in entries]
    for pr in all_results:
        writer.writerow(
            [
                pr.metric,
                pr.baseline,
                pr.treatment,
                pr.subgroup or "",
                pr.n_paired,
                f"{pr.mean_baseline:.6f}",
                f"{pr.mean_treatment:.6f}",
                f"{pr.diff:.6f}",
                f"{pr.ci_low:.6f}",
                f"{pr.ci_high:.6f}",
                pr.test,
                "" if pr.wilcoxon_stat is None else f"{pr.wilcoxon_stat:.4f}",
                "" if pr.p_value is None else f"{pr.p_value:.6f}",
                "" if pr.q_value is None else f"{pr.q_value:.6f}",
                "" if pr.cliffs_delta is None else f"{pr.cliffs_delta:.4f}",
                "" if pr.cohens_d is None else f"{pr.cohens_d:.4f}",
                "1" if pr.primary else "0",
                "" if pr.geometric_mean_ratio is None else f"{pr.geometric_mean_ratio:.6f}",
            ]
        )
    return buf.getvalue()


__all__ = [
    "AblationReport",
    "PairResult",
    "build_paired_matrix",
    "render_csv",
    "render_markdown",
    "run_ablation_analysis",
]
