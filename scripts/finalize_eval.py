"""Finalise a partially-completed eval_run without re-running anything.

Use case: the eval daemon thread was killed mid-RAGAS (Z.AI 429s or container
restart). The 990 per-case `eval_results` rows are persisted; the run row is
stuck at status=running with `_partial: True`. This script pulls the run via
the API, recomputes the per-variant aggregate + ablation report locally
(reusing the same code path the in-process runner would have), and writes the
artifact JSON to disk so the report-population step can proceed.

It does NOT touch the database. The zombie row stays at status=running; a
maintenance sweep can clear it later. The on-disk artifact is enough for
`compare_ablations` and `_report_metrics`.

Run via:
    uv run --directory backend python /home/daniel/rag-benchmarking/scripts/finalize_eval.py \
        --eval-run-id bd31b96d-6201-464c-8b66-28d40f81692a \
        --artifact-dir backend/artifacts/evals
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import httpx

logger = logging.getLogger("finalize_eval")


def _api_base_url() -> str:
    return os.environ.get("API_BASE_URL", "http://localhost:8000")


def _bearer_token() -> str:
    token = os.environ.get("API_BEARER_TOKEN")
    if token:
        return token
    env_path = Path("/home/daniel/rag-benchmarking/backend/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("API_BEARER_TOKEN"):
                value = line.split("=", 1)[1].strip().strip("'\"")
                if value:
                    return value
    raise SystemExit("API_BEARER_TOKEN not set (env or backend/.env)")


def _fetch_run(eval_run_id: str) -> dict:
    base = _api_base_url()
    headers = {"Authorization": f"Bearer {_bearer_token()}"}
    with httpx.Client(timeout=120.0) as client:
        response = client.get(f"{base}/v1/evaluations/{eval_run_id}", headers=headers)
        response.raise_for_status()
        return response.json()


def _attach_ablation(artifact: dict) -> None:
    """Run paired ablation analysis on the artifact's per-case rows.

    Mirrors what `rag_evaluation.runner._attach_ablation_report` does after the
    per-case loop completes, but operating on the artifact dict shape returned
    by `/v1/evaluations/<id>` rather than ORM objects.
    """

    from rag_evaluation.ablation_analysis import run_ablation_analysis

    # Build a synthetic "run_id" and pick the baseline from the variants
    # actually present in the rows. The full locked preset always has
    # `full_agentic`; if for some reason it's missing, fall back to the first
    # variant alphabetically.
    rows = artifact.get("results") or []
    variants_present = sorted(
        {(r.get("variant_name") or r.get("retrieval_mode")) for r in rows if isinstance(r, dict)}
    )
    variants_present = [v for v in variants_present if v]
    baseline = "full_agentic" if "full_agentic" in variants_present else variants_present[0]
    logger.info("ablation_baseline=%s variants=%s", baseline, variants_present)
    try:
        report = run_ablation_analysis(artifact, baseline=baseline)
    except Exception as exc:  # noqa: BLE001 — surface every failure path
        logger.exception("ablation_analysis_failed")
        artifact.setdefault("metrics", {})["ablation"] = {
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            "baseline": baseline,
            "variants": variants_present,
        }
        return

    # Serialise the dataclass-graph the same way runner._sanitise_for_jsonb does
    # (the runner uses dataclasses.asdict + a NaN-stripper). Here NaN can come
    # from p_values that are exactly 0/1 under Wilcoxon ties; json.dumps with
    # allow_nan=False would crash, so we coerce to None.
    import dataclasses
    import math

    def _sanitise(obj):
        if isinstance(obj, float):
            return None if (math.isnan(obj) or math.isinf(obj)) else obj
        if isinstance(obj, dict):
            return {k: _sanitise(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_sanitise(v) for v in obj]
        return obj

    artifact.setdefault("metrics", {})["ablation"] = _sanitise(dataclasses.asdict(report))


def _drop_partial_flag(artifact: dict) -> None:
    """Strip the `_partial` marker so consumers treat the artifact as final."""

    metrics = artifact.get("metrics") or {}
    metrics.pop("_partial", None)


def _write_artifact(artifact: dict, eval_run_id: str, artifact_dir: Path) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    out = artifact_dir / f"{eval_run_id}.json"
    out.write_text(json.dumps(artifact, indent=2, sort_keys=True))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-run-id", required=True)
    parser.add_argument("--artifact-dir", type=Path, default=Path("backend/artifacts/evals"))
    parser.add_argument("--mark-status", choices=("none", "completed", "completed_with_errors"), default="none")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("fetch_run eval_run_id=%s", args.eval_run_id)
    artifact = _fetch_run(args.eval_run_id)
    logger.info("fetched: results=%d metrics_keys=%s", len(artifact.get("results") or []),
                list((artifact.get("metrics") or {}).keys())[:10])
    if args.mark_status != "none":
        artifact["status"] = args.mark_status
    _attach_ablation(artifact)
    _drop_partial_flag(artifact)
    out = _write_artifact(artifact, args.eval_run_id, args.artifact_dir)
    logger.info("artifact_written path=%s", out)
    ablation = (artifact.get("metrics") or {}).get("ablation") or {}
    if "error" in ablation:
        logger.warning("ablation_skipped error=%s", ablation["error"])
    else:
        pairs = len(ablation.get("pair_results") or [])
        logger.info("ablation_attached pair_results=%d baseline=%s",
                    pairs, ablation.get("baseline"))


if __name__ == "__main__":
    sys.exit(main() or 0)
