"""Paired ablation analysis CLI.

Consumes an eval-run artifact written by ``run_eval.py``, builds paired
matrices across the named variants, runs Wilcoxon / McNemar tests with FDR
correction, and writes a Markdown report + long-form CSV.

Usage:
    uv run --directory backend python -m rag_benchmarking.scripts.analyze_ablation \
        --artifact artifacts/evals/<eval_run_id>.json \
        [--baseline full_agentic] \
        [--out docs/eval/ablation_v1_results.md] \
        [--csv docs/eval/ablation_v1_results.csv] \
        [--fdr-q 0.05] \
        [--bootstrap-samples 5000] \
        [--seed 1729]

Pre-registration: ``docs/eval/ablation_v1_plan.md``.
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, cast

from rag_evaluation_worker.ablation_analysis import (
    PRIMARY_ENDPOINTS_DEFAULT,
    SECONDARY_ENDPOINTS_DEFAULT,
    render_csv,
    render_markdown,
    run_ablation_analysis,
)

logger = logging.getLogger(__name__)


def _load_artifact(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    return cast("dict[str, Any]", json.loads(text))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paired ablation analysis (Wilcoxon/McNemar + BH FDR + effect sizes).")
    parser.add_argument("--artifact", required=True, type=Path, help="Eval-run JSON artifact")
    parser.add_argument(
        "--baseline",
        default="full_agentic",
        help="Variant name to compare every other variant against",
    )
    parser.add_argument(
        "--primary-endpoints",
        default=",".join(PRIMARY_ENDPOINTS_DEFAULT),
        help="Comma-separated list of primary endpoints (FDR-controlled)",
    )
    parser.add_argument(
        "--secondary-endpoints",
        default=",".join(SECONDARY_ENDPOINTS_DEFAULT),
        help="Comma-separated list of secondary endpoints (uncorrected)",
    )
    parser.add_argument("--out", type=Path, default=None, help="Markdown output path")
    parser.add_argument("--csv", type=Path, default=None, help="CSV output path (long-form per-pair)")
    parser.add_argument("--fdr-q", type=float, default=0.05, help="Benjamini-Hochberg q threshold")
    parser.add_argument("--bootstrap-samples", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument(
        "--two-sided",
        action="store_true",
        help="Use two-sided alternatives for primary endpoints (default: one-sided greater)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    artifact = _load_artifact(args.artifact)
    report = run_ablation_analysis(
        artifact,
        baseline=args.baseline,
        primary_endpoints=tuple(e.strip() for e in args.primary_endpoints.split(",") if e.strip()),
        secondary_endpoints=tuple(e.strip() for e in args.secondary_endpoints.split(",") if e.strip()),
        seed=args.seed,
        bootstrap_samples=args.bootstrap_samples,
        fdr_q=args.fdr_q,
        one_sided=not args.two_sided,
    )

    markdown = render_markdown(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(markdown, encoding="utf-8")
        logger.info("ablation_markdown_written path=%s", args.out)
    else:
        print(markdown)

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        args.csv.write_text(render_csv(report), encoding="utf-8")
        logger.info("ablation_csv_written path=%s", args.csv)

    return 0


if __name__ == "__main__":
    sys.exit(main())
