"""Trigger an evaluation run from the CLI and wait for terminal status.

Usage:
    # Default 3-mode comparison (back-compat):
    uv run --directory backend python -m rag_benchmarking.scripts.run_eval \\
        --dataset <dataset_id> \\
        [--variants full_agentic,single_pass,llm_only] \\
        [--case-ids id1,id2,...] \\
        [--output table|json|markdown] \\
        [--artifact-dir artifacts/evals] \\
        [--poll-seconds 5] \\
        [--timeout-seconds 3600]

    # Component-lesion ablation matrix (9 locked configs):
    uv run --directory backend python -m rag_benchmarking.scripts.run_eval \\
        --dataset <dataset_id> --ablation-preset locked9

    # Custom matrix from a YAML/JSON variants file:
    uv run --directory backend python -m rag_benchmarking.scripts.run_eval \\
        --dataset <dataset_id> --variants-file path/to/variants.yaml

Reads ``API_BEARER_TOKEN`` and ``API_BASE_URL`` from ``backend/.env`` via
``rag_common.config.get_settings``. Writes the full aggregate metrics JSON to
``{artifact_dir}/{eval_run_id}.json`` and prints either a human table, the
JSON, or a markdown summary suitable for pasting into the implementation
report.

The companion script ``compare_ablations.py`` renders a side-by-side variant
table; ``analyze_ablation.py`` runs paired statistical analysis with FDR
correction.
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Literal, cast

import httpx
from rag_common.config import get_settings
from rag_common.enums import JOB_TERMINAL_STATUSES, BenchmarkProfile
from rag_common.eval_variants import ABLATION_PRESETS
from rag_common.schemas import RetrievalVariantSpec

logger = logging.getLogger(__name__)

OutputFormat = Literal["table", "json", "markdown"]
# Mirror the worker's canonical set so the CLI exits as soon as the run is
# durably done. The previous hand-rolled ``{"succeeded", "failed", "cancelled"}``
# silently dropped the actual terminal value (``completed`` /
# ``completed_with_errors``), so successful runs left the poller spinning.
TERMINAL_STATUSES = {status.value for status in JOB_TERMINAL_STATUSES}

# Headline metric keys produced by the evaluation runner. Order is the order we
# render in the table; missing keys are shown as "—". Keep in sync with
# ``rag_evaluation_worker.runner._summary_for_metrics``.
HEADLINE_METRICS: tuple[tuple[str, str], ...] = (
    ("case_count", "Cases"),
    ("answer_accuracy_rate", "Answer accuracy"),
    ("avg_recall_at_5", "Recall@5"),
    ("avg_recall_at_10", "Recall@10"),
    ("avg_mrr", "MRR"),
    ("avg_page_evidence_f1", "Page F1"),
    ("citation_validity_rate", "Citation validity"),
    ("citation_coverage_rate", "Citation coverage"),
    ("citation_gold_recall_rate", "Citation gold recall"),
    ("metadata_filter_correctness_rate", "Metadata filter"),
    ("insufficient_rate", "Insufficient rate"),
    ("avg_latency_ms", "Latency (ms)"),
    ("total_tokens", "Tokens"),
    ("total_cost_usd", "Cost (USD)"),
)


def _api_base_url() -> str:
    return os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")


def _auth_headers() -> dict[str, str]:
    settings = get_settings()
    token = settings.api_bearer_token.get_secret_value()
    if not token:
        raise SystemExit("API_BEARER_TOKEN is not set in backend/.env")
    return {"Authorization": f"Bearer {token}"}


def _post_evaluation(
    base_url: str,
    headers: dict[str, str],
    dataset_id: str,
    variants: list[str],
    case_ids: list[str] | None,
    variant_specs: list[RetrievalVariantSpec] | None = None,
) -> dict[str, str]:
    payload: dict[str, Any] = {
        "dataset_id": dataset_id,
        "benchmark_profile": BenchmarkProfile.SCIENTIFIC,
    }
    if variant_specs is not None:
        payload["variants"] = [spec.model_dump(mode="json") for spec in variant_specs]
    else:
        payload["system_variants"] = variants
    if case_ids:
        payload["case_ids"] = case_ids
    response = httpx.post(
        f"{base_url}/v1/evaluations",
        json=payload,
        headers=headers,
        timeout=30.0,
    )
    if response.status_code >= 400:
        raise SystemExit(f"POST /v1/evaluations failed ({response.status_code}): {response.text}")
    return cast("dict[str, str]", response.json())


def _load_variants_file(path: Path) -> list[RetrievalVariantSpec]:
    """Load a list of RetrievalVariantSpec dicts from YAML or JSON."""

    text = path.read_text(encoding="utf-8")
    if path.suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - yaml is a transitive dep
            raise SystemExit("YAML variants files require PyYAML; pass JSON instead") from exc
        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)
    if not isinstance(raw, list):
        raise SystemExit(f"{path}: expected a list of variant specs at top level")
    return [RetrievalVariantSpec.model_validate(item) for item in raw]


def _get_evaluation(base_url: str, headers: dict[str, str], eval_run_id: str) -> dict[str, Any]:
    response = httpx.get(
        f"{base_url}/v1/evaluations/{eval_run_id}",
        headers=headers,
        timeout=30.0,
    )
    if response.status_code >= 400:
        raise SystemExit(f"GET /v1/evaluations/{eval_run_id} failed ({response.status_code}): {response.text}")
    return cast("dict[str, Any]", response.json())


def _wait_for_terminal(
    base_url: str,
    headers: dict[str, str],
    eval_run_id: str,
    *,
    poll_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_status: str | None = None
    while True:
        run = _get_evaluation(base_url, headers, eval_run_id)
        status = str(run.get("status") or "")
        if status != last_status:
            logger.info("eval_status status=%s eval_run_id=%s", status, eval_run_id)
            last_status = status
        if status in TERMINAL_STATUSES:
            return run
        if time.monotonic() > deadline:
            raise SystemExit(f"Eval run {eval_run_id} did not reach terminal status within {timeout_seconds}s")
        time.sleep(poll_seconds)


def _write_artifact(run: dict[str, Any], artifact_dir: Path) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    target = artifact_dir / f"{run['id']}.json"
    target.write_text(json.dumps(run, indent=2, default=str), encoding="utf-8")
    return target


def _format_value(key: str, value: Any) -> str:
    if value is None:
        return "—"
    if key == "avg_latency_ms":
        return f"{float(value):.0f}"
    if key == "total_tokens" or key == "case_count":
        return f"{int(value):,}"
    if key == "total_cost_usd":
        return f"${float(value):.4f}"
    if isinstance(value, (int, float)):
        return f"{float(value):.3f}"
    return str(value)


def _render_markdown(run: dict[str, Any]) -> str:
    metrics = run.get("metrics") or {}
    variants = [variant for variant in metrics if isinstance(metrics[variant], dict)]
    if not variants:
        return f"_No per-variant metrics on eval run {run.get('id')}._"
    lines = [
        f"### Eval run `{run.get('id')}` ({run.get('status')})",
        "",
        "| Metric | " + " | ".join(variants) + " |",
        "| --- | " + " | ".join("---" for _ in variants) + " |",
    ]
    for key, label in HEADLINE_METRICS:
        row = [label]
        row.extend(_format_value(key, metrics[variant].get(key)) for variant in variants)
        lines.append("| " + " | ".join(row) + " |")
    grand_total_cost = metrics.get("total_cost_usd")
    if isinstance(grand_total_cost, (int, float)):
        lines.append("")
        lines.append(f"_Grand total cost: ${float(grand_total_cost):.4f}_")
    return "\n".join(lines)


def _render_table(run: dict[str, Any]) -> str:
    metrics = run.get("metrics") or {}
    variants = [variant for variant in metrics if isinstance(metrics[variant], dict)]
    if not variants:
        return f"No per-variant metrics on eval run {run.get('id')}"
    label_width = max(len(label) for _key, label in HEADLINE_METRICS)
    col_width = max(16, max((len(variant) for variant in variants), default=10))
    header = "Metric".ljust(label_width) + "  " + "  ".join(variant.rjust(col_width) for variant in variants)
    separator = "-" * len(header)
    body_rows = []
    for key, label in HEADLINE_METRICS:
        cells = [_format_value(key, metrics[variant].get(key)).rjust(col_width) for variant in variants]
        body_rows.append(label.ljust(label_width) + "  " + "  ".join(cells))
    return "\n".join([header, separator, *body_rows])


def _print_output(run: dict[str, Any], output: OutputFormat) -> None:
    if output == "json":
        print(json.dumps(run, indent=2, default=str))
        return
    if output == "markdown":
        print(_render_markdown(run))
        return
    print(_render_table(run))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trigger an evaluation run and wait for results.")
    parser.add_argument("--dataset", required=True, help="Dataset id")
    parser.add_argument(
        "--variants",
        default="full_agentic,single_pass,llm_only",
        help=(
            "Comma-separated retrieval modes (default: all three). "
            "Mutually exclusive with --ablation-preset / --variants-file."
        ),
    )
    parser.add_argument(
        "--ablation-preset",
        choices=sorted(ABLATION_PRESETS.keys()),
        default=None,
        help="Use a named ablation matrix (e.g. 'locked9' = 9 component-lesion configs).",
    )
    parser.add_argument(
        "--variants-file",
        default=None,
        type=Path,
        help="Path to a YAML or JSON file listing RetrievalVariantSpec dicts.",
    )
    parser.add_argument(
        "--case-ids",
        default=None,
        help="Comma-separated eval case ids; if omitted, all verified cases on the dataset are used",
    )
    parser.add_argument(
        "--output",
        choices=("table", "json", "markdown"),
        default="table",
        help="Render format for stdout (artifact JSON is always written)",
    )
    parser.add_argument(
        "--artifact-dir",
        default="artifacts/evals",
        type=Path,
        help="Directory to write the raw eval-run JSON (default: artifacts/evals)",
    )
    parser.add_argument("--poll-seconds", default=5.0, type=float, help="Polling interval")
    parser.add_argument("--timeout-seconds", default=3600.0, type=float, help="Hard timeout")
    parser.add_argument(
        "--existing-run-id",
        default=None,
        help="Skip creation and only poll/render this existing eval_run_id",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    base_url = _api_base_url()
    headers = _auth_headers()
    case_ids = [c.strip() for c in args.case_ids.split(",")] if args.case_ids else None

    variant_specs: list[RetrievalVariantSpec] | None = None
    if args.ablation_preset and args.variants_file:
        raise SystemExit("Pass at most one of --ablation-preset / --variants-file")
    if args.ablation_preset:
        variant_specs = list(ABLATION_PRESETS[args.ablation_preset])
        logger.info("ablation_preset=%s variants=%s", args.ablation_preset, [spec.name for spec in variant_specs])
    elif args.variants_file:
        variant_specs = _load_variants_file(args.variants_file)
        logger.info("variants_file=%s variants=%s", args.variants_file, [spec.name for spec in variant_specs])
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]

    if args.existing_run_id:
        eval_run_id = args.existing_run_id
        logger.info("eval_resume eval_run_id=%s", eval_run_id)
    else:
        created = _post_evaluation(base_url, headers, args.dataset, variants, case_ids, variant_specs)
        eval_run_id = created["eval_run_id"]
        logger.info("eval_created eval_run_id=%s job_id=%s", eval_run_id, created.get("job_id"))

    run = _wait_for_terminal(
        base_url,
        headers,
        eval_run_id,
        poll_seconds=args.poll_seconds,
        timeout_seconds=args.timeout_seconds,
    )
    artifact = _write_artifact(run, args.artifact_dir)
    logger.info("eval_artifact_written path=%s", artifact)

    _print_output(run, cast("OutputFormat", args.output))
    return 0 if run.get("status") in {"completed", "completed_with_errors"} else 1


if __name__ == "__main__":
    sys.exit(main())
