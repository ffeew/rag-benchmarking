"""Seed curated eval cases into a dataset.

Usage:
    python -m rag_benchmarking.scripts.seed_eval_cases \\
        --dataset <dataset_id> \\
        --file backend/eval_cases/sec_filings_v1.yaml \\
        [--dry-run]

Cases are upserted by (dataset_id, case_key). Re-running is idempotent: existing rows
with the same case_key are updated in place; rows without a case_key are left alone.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError
from rag_common.config import get_settings
from rag_common.db import models
from rag_common.db.session import get_sessionmaker
from sqlalchemy import select

logger = logging.getLogger(__name__)


class SeedExpectedCitation(BaseModel):
    ticker: str | None = None
    form_type: str | None = None
    page_number: int | None = None
    document_id: str | None = None
    evidence_text: str | None = None


class SeedEvalCase(BaseModel):
    case_key: str = Field(min_length=1, max_length=64)
    category: str | None = Field(default=None, max_length=64)
    difficulty: str | None = Field(default=None, max_length=16)
    question: str = Field(min_length=1)
    expected_answer: str | None = None
    expected_citations: list[SeedExpectedCitation] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


def load_cases(path: Path) -> list[SeedEvalCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    if not isinstance(raw, list):
        raise ValueError(f"Expected a top-level list of cases in {path}, got {type(raw).__name__}")
    cases: list[SeedEvalCase] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"Case at index {index} is not a mapping")
        try:
            cases.append(SeedEvalCase(**entry))
        except ValidationError as exc:
            raise ValueError(f"Case {entry.get('case_key', index)} failed validation: {exc}") from exc
    return cases


def seed_cases(
    dataset_id: str,
    cases: list[SeedEvalCase],
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """Upsert cases into the eval_cases table. Returns counts."""
    settings = get_settings()
    sessionmaker = get_sessionmaker(settings.database_url)
    counts = {"created": 0, "updated": 0, "skipped": 0}
    with sessionmaker() as session:
        dataset = session.get(models.Dataset, dataset_id)
        if dataset is None:
            raise ValueError(f"Dataset {dataset_id} was not found")
        for case in cases:
            existing = session.scalar(
                select(models.EvalCase).where(
                    models.EvalCase.dataset_id == dataset_id,
                    models.EvalCase.case_key == case.case_key,
                )
            )
            if existing is None:
                if dry_run:
                    counts["skipped"] += 1
                    continue
                session.add(_to_orm(dataset_id, case))
                counts["created"] += 1
            else:
                if dry_run:
                    counts["skipped"] += 1
                    continue
                _apply_update(existing, case)
                counts["updated"] += 1
        if dry_run:
            session.rollback()
        else:
            session.commit()
    return counts


def _to_orm(dataset_id: str, case: SeedEvalCase) -> models.EvalCase:
    return models.EvalCase(
        dataset_id=dataset_id,
        case_key=case.case_key,
        category=case.category,
        difficulty=case.difficulty,
        question=case.question,
        expected_answer=case.expected_answer,
        expected_citations=[citation.model_dump() for citation in case.expected_citations],
        tags=list(case.tags),
    )


def _apply_update(existing: models.EvalCase, case: SeedEvalCase) -> None:
    existing.category = case.category
    existing.difficulty = case.difficulty
    existing.question = case.question
    existing.expected_answer = case.expected_answer
    existing.expected_citations = [citation.model_dump() for citation in case.expected_citations]
    existing.tags = list(case.tags)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed curated eval cases into a dataset.")
    parser.add_argument("--dataset", required=True, help="Dataset id to attach cases to")
    parser.add_argument("--file", required=True, type=Path, help="Path to YAML file with case definitions")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report counts without writing")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        cases = load_cases(args.file)
    except (OSError, ValueError, ValidationError) as exc:
        logger.error("seed_load_failed: %s", exc)
        return 2

    logger.info("seed_load_ok count=%d file=%s", len(cases), args.file)
    try:
        counts = seed_cases(args.dataset, cases, dry_run=args.dry_run)
    except ValueError as exc:
        logger.error("seed_failed: %s", exc)
        return 2
    mode = "dry_run" if args.dry_run else "applied"
    logger.info(
        "seed_done mode=%s created=%d updated=%d skipped=%d",
        mode,
        counts["created"],
        counts["updated"],
        counts["skipped"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
