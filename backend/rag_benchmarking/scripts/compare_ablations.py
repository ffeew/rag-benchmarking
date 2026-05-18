"""Render a side-by-side ablation comparison from one or more eval runs.

Usage:
    # Compare variants WITHIN a single eval run (the default mode — the runner
    # already evaluates all three variants in one run):
    uv run --directory backend python -m rag_benchmarking.scripts.compare_ablations \\
        --artifact artifacts/evals/<eval_run_id>.json

    # Compare variants ACROSS multiple eval runs (e.g. one run per variant):
    uv run --directory backend python -m rag_benchmarking.scripts.compare_ablations \\
        --artifact artifacts/evals/run-a.json \\
        --artifact artifacts/evals/run-b.json

    # Launch a fresh run, then render — convenience wrapper around run_eval.py:
    uv run --directory backend python -m rag_benchmarking.scripts.compare_ablations \\
        --dataset <dataset_id>

Outputs a markdown table to stdout. Sources of variant metrics:
* If the run's ``metrics`` dict has per-variant keys (``full_agentic`` /
  ``single_pass`` / ``llm_only``), those are used directly.
* Otherwise the run is recomputed from the ``results`` list via
  ``rag_evaluation.runner.aggregate_metrics`` (so old artifacts without
  pre-baked aggregates still render).
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, cast

from rag_benchmarking.scripts.run_eval import (
    HEADLINE_METRICS,
    _api_base_url,
    _auth_headers,
    _format_value,
    _post_evaluation,
    _wait_for_terminal,
    _write_artifact,
)

logger = logging.getLogger(__name__)


def _load_artifact(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _variants_in(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metrics = run.get("metrics") or {}
    return {
        variant: payload
        for variant, payload in metrics.items()
        if isinstance(payload, dict) and variant not in {"total_cost_usd"}
    }


def _collect_variants(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Merge per-variant metrics across one or more eval runs.

    When the same variant appears in multiple runs, the later run wins — useful
    for "rerun just llm_only" workflows without losing the original
    full_agentic / single_pass numbers.
    """
    merged: dict[str, dict[str, Any]] = {}
    for run in runs:
        for variant, payload in _variants_in(run).items():
            merged[variant] = payload
    return merged


def _grand_total_cost(runs: list[dict[str, Any]]) -> float | None:
    total = 0.0
    saw_value = False
    for run in runs:
        cost = (run.get("metrics") or {}).get("total_cost_usd")
        if isinstance(cost, (int, float)):
            total += float(cost)
            saw_value = True
    return total if saw_value else None


def _render_markdown(merged: dict[str, dict[str, Any]], grand_total: float | None) -> str:
    if not merged:
        return "_No variants found in the provided eval runs._"
    variants = list(merged.keys())
    lines = [
        "| Metric | " + " | ".join(variants) + " |",
        "| --- | " + " | ".join("---" for _ in variants) + " |",
    ]
    for key, label in HEADLINE_METRICS:
        row = [label]
        row.extend(_format_value(key, merged[variant].get(key)) for variant in variants)
        lines.append("| " + " | ".join(row) + " |")
    if grand_total is not None:
        lines.append("")
        lines.append(f"_Grand total cost across runs: ${grand_total:.4f}_")
    return "\n".join(lines)


def _by_category_markdown(merged: dict[str, dict[str, Any]]) -> str:
    """Render answer accuracy by category for each variant — the rubric slice."""
    categories: set[str] = set()
    for payload in merged.values():
        by_cat = payload.get("by_category") or {}
        categories.update(by_cat.keys())
    if not categories:
        return ""
    ordered_categories = sorted(categories)
    variants = list(merged.keys())
    lines = [
        "",
        "#### Answer accuracy by category",
        "",
        "| Category | " + " | ".join(variants) + " |",
        "| --- | " + " | ".join("---" for _ in variants) + " |",
    ]
    for category in ordered_categories:
        row = [category]
        for variant in variants:
            payload = (merged[variant].get("by_category") or {}).get(category) or {}
            row.append(_format_value("answer_accuracy_rate", payload.get("answer_accuracy_rate")))
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Side-by-side ablation comparison from eval-run artifacts.")
    parser.add_argument(
        "--artifact",
        action="append",
        type=Path,
        default=[],
        help="Path to an eval-run JSON artifact (repeat for multiple runs)",
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="If set, kick off a fresh eval run on this dataset before rendering",
    )
    parser.add_argument(
        "--variants",
        default="full_agentic,single_pass,llm_only",
        help="Variants for the fresh run (only used with --dataset)",
    )
    parser.add_argument(
        "--artifact-dir",
        default="artifacts/evals",
        type=Path,
        help="Directory to write artifacts when --dataset is supplied",
    )
    parser.add_argument("--poll-seconds", default=5.0, type=float)
    parser.add_argument("--timeout-seconds", default=3600.0, type=float)
    parser.add_argument(
        "--include-by-category",
        action="store_true",
        help="Also print the per-category answer-accuracy breakdown",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    runs: list[dict[str, Any]] = []
    if args.dataset:
        base_url = _api_base_url()
        headers = _auth_headers()
        variants = [v.strip() for v in args.variants.split(",") if v.strip()]
        created = _post_evaluation(base_url, headers, args.dataset, variants, None)
        run = _wait_for_terminal(
            base_url,
            headers,
            created["eval_run_id"],
            poll_seconds=args.poll_seconds,
            timeout_seconds=args.timeout_seconds,
        )
        artifact_path = _write_artifact(run, args.artifact_dir)
        logger.info("eval_artifact_written path=%s", artifact_path)
        runs.append(run)

    runs.extend(_load_artifact(path) for path in args.artifact)

    if not runs:
        logger.error("No --artifact paths and no --dataset given; nothing to compare.")
        return 2

    merged = _collect_variants(runs)
    output = _render_markdown(merged, _grand_total_cost(runs))
    if args.include_by_category:
        output = output + "\n" + _by_category_markdown(merged)
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
