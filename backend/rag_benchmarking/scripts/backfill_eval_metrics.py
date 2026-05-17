"""Recompute and persist run-level aggregates for EvalRun rows that never
reached the runner's final ``aggregate_metrics`` write.

The typical victim is a row that was reaped mid-loop: per-case ``EvalResult``
rows are intact (the runner commits each one progressively), but
``EvalRun.metrics`` is still ``{}``. The API serializer recomputes on the read
path so the UI shows correct numbers either way, but persisting the aggregate
back to the DB lets list-page filters and downstream analyzers see them too.

Usage:
    uv run --directory backend python -m rag_benchmarking.scripts.backfill_eval_metrics
    uv run --directory backend python -m rag_benchmarking.scripts.backfill_eval_metrics --eval-run-id <id>
    uv run --directory backend python -m rag_benchmarking.scripts.backfill_eval_metrics --dry-run

Idempotent: re-running on a row whose ``metrics`` already has ``variants_used``
is a no-op unless ``--force`` is set.
"""

import argparse
import logging
import sys
from typing import Iterable

from rag_common.db import models
from rag_common.db.session import get_sessionmaker
from rag_common.eval_aggregation import aggregate_metrics
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

logger = logging.getLogger(__name__)


def _needs_backfill(eval_run: models.EvalRun, *, force: bool) -> bool:
    if force:
        return bool(eval_run.results)
    metrics = eval_run.metrics or {}
    if "variants_used" in metrics:
        return False
    return bool(eval_run.results)


def _candidate_runs(session: Session, eval_run_id: str | None) -> Iterable[models.EvalRun]:
    stmt = select(models.EvalRun).options(selectinload(models.EvalRun.results))
    if eval_run_id:
        stmt = stmt.where(models.EvalRun.id == eval_run_id)
    return session.scalars(stmt)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval-run-id", help="Only process this single eval run id")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing")
    parser.add_argument("--force", action="store_true", help="Recompute even when metrics already finalised")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    maker = get_sessionmaker()
    updated = 0
    skipped = 0
    with maker() as session:
        for eval_run in _candidate_runs(session, args.eval_run_id):
            if not _needs_backfill(eval_run, force=args.force):
                skipped += 1
                continue
            seed = int((eval_run.run_config or {}).get("bootstrap_seed") or 1729)
            new_metrics = aggregate_metrics(list(eval_run.results), seed=seed)
            if not new_metrics:
                skipped += 1
                logger.info("eval_run_no_aggregable_results id=%s", eval_run.id)
                continue
            new_metrics["_recomputed"] = True
            logger.info(
                "eval_run_backfilled id=%s pass_rate=%s avg_latency_ms=%s",
                eval_run.id,
                new_metrics.get("pass_rate"),
                new_metrics.get("avg_latency_ms"),
            )
            if not args.dry_run:
                eval_run.metrics = new_metrics
            updated += 1
        if not args.dry_run:
            session.commit()
    logger.info("backfill_done updated=%d skipped=%d dry_run=%s", updated, skipped, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
