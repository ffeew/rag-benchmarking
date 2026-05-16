"""Eager SEC defaults backfill when registering the canonical SEC corpus.

The runtime fallback in ``rag_retrieval.dataset_config.load_dataset_config`` always
resolves nulls to SEC values, so existing rows behave identically without any data
change. But for the default ``"sec-filings"`` dataset, registering it should also
persist those values into the row so operators see the configuration explicitly when
they inspect the dataset (in DB or via the API).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rag_common.db import models
from rag_retrieval.dataset_config import (
    DEFAULT_CITATION_LABEL_TEMPLATE,
    DEFAULT_ENTITY_LABEL,
    DEFAULT_METRIC_TERMS,
    DEFAULT_VALID_FORMS,
)
from sqlalchemy import select

from rag_benchmarking.ingestion.documents import register_local_corpus

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.orm import Session


def _empty_corpus(tmp_path: Path) -> Path:
    """Empty corpus dir - the PDF scan finds nothing, so no MinIO writes are needed."""
    corpus = tmp_path / "empty_corpus"
    corpus.mkdir(exist_ok=True)
    return corpus


def test_sec_dataset_registration_eagerly_writes_overrides(
    db_session: Session, tmp_path: Path
) -> None:
    dataset, _docs, created, reused = register_local_corpus(
        db_session,
        dataset_name="sec-filings",
        description="seed",
        path=_empty_corpus(tmp_path),
    )
    db_session.refresh(dataset)

    assert created == 0
    assert reused == 0
    assert dataset.domain_label == "SEC filings of US public companies"
    assert dataset.entity_label == DEFAULT_ENTITY_LABEL
    assert tuple(dataset.valid_forms or ()) == DEFAULT_VALID_FORMS
    assert tuple(dataset.metric_terms or ()) == DEFAULT_METRIC_TERMS
    assert dataset.citation_label_template == DEFAULT_CITATION_LABEL_TEMPLATE
    # hyde_style_hint stays null even on the SEC dataset because the prompt is
    # corpus-neutral and the SEC corpus does not need an extra hint.
    assert dataset.hyde_style_hint is None


def test_non_sec_dataset_registration_leaves_overrides_null(
    db_session: Session, tmp_path: Path
) -> None:
    """A custom-named dataset stays null so the resolver still applies SEC fallback.

    This is intentional: operators registering a non-default dataset are expected to
    supply overrides via the API or PATCH later.
    """
    dataset, _docs, _created, _reused = register_local_corpus(
        db_session,
        dataset_name="compliance-memos",
        description=None,
        path=_empty_corpus(tmp_path),
    )
    db_session.refresh(dataset)

    assert dataset.domain_label is None
    assert dataset.entity_label is None
    assert dataset.valid_forms is None
    assert dataset.metric_terms is None
    assert dataset.citation_label_template is None


def test_sec_registration_does_not_overwrite_explicit_overrides(
    db_session: Session, tmp_path: Path
) -> None:
    """When the caller explicitly passes overrides, those win over the SEC defaults."""
    dataset, _docs, _created, _reused = register_local_corpus(
        db_session,
        dataset_name="sec-filings",
        description=None,
        path=_empty_corpus(tmp_path),
        domain_label="Custom SEC framing",
        valid_forms=["10-K"],
    )
    db_session.refresh(dataset)

    assert dataset.domain_label == "Custom SEC framing"
    assert dataset.valid_forms == ["10-K"]
    # Unspecified overrides still pick up the SEC defaults since the SEC backfill
    # path runs per field.
    assert dataset.entity_label == DEFAULT_ENTITY_LABEL
    assert tuple(dataset.metric_terms or ()) == DEFAULT_METRIC_TERMS


def test_sec_registration_is_idempotent_on_existing_dataset(
    db_session: Session, tmp_path: Path
) -> None:
    """A second registration call must not clobber the existing row's overrides.

    ``get_or_create_dataset`` returns the existing row when the name matches, which
    short-circuits the backfill block. An operator who has hand-tuned an override
    must not see it reverted when re-running the ingestion endpoint.
    """
    register_local_corpus(
        db_session,
        dataset_name="sec-filings",
        description="first call",
        path=_empty_corpus(tmp_path),
    )
    first = db_session.scalar(select(models.Dataset).where(models.Dataset.name == "sec-filings"))
    assert first is not None
    first.domain_label = "Operator override"
    db_session.commit()

    dataset, _docs, _created, _reused = register_local_corpus(
        db_session,
        dataset_name="sec-filings",
        description="second call",
        path=_empty_corpus(tmp_path),
    )
    db_session.refresh(dataset)

    assert dataset.domain_label == "Operator override"
