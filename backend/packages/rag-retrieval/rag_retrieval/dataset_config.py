"""Dataset-scoped retrieval configuration.

Replaces the module-level SEC-specific constants (``VALID_FORMS``, ``METRIC_TERMS``)
and the hard-coded "SEC filings RAG system" identity in the agent prompts with values
that can be overridden per dataset via columns on the ``datasets`` row. Resolves null
columns to the SEC defaults so existing behavior is preserved when no overrides are
supplied.

Loaded once per query in ``run_query`` and threaded through every agent (planner,
HyDE, retrieval-agent, verifier, generator) and the deterministic fallbacks.
"""

import logging
from dataclasses import dataclass
from typing import Self

from rag_common.db import models
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


DEFAULT_SEC_DOMAIN_LABEL = "SEC filings of US public companies"
DEFAULT_ENTITY_LABEL = "ticker"
DEFAULT_VALID_FORMS: tuple[str, ...] = ("10-K", "10-Q", "8-K")
DEFAULT_METRIC_TERMS: tuple[str, ...] = (
    "revenue",
    "debt",
    "cash",
    "gross margin",
    "research and development",
    "r&d",
    "segment",
    "risk",
    "ai",
    "artificial intelligence",
    "demand",
    "margin",
    "income",
    "expense",
)
DEFAULT_CITATION_LABEL_TEMPLATE = "[{entity} {filing_date} {form_type}, p. {page}]"


def _str_tuple(value: object, default: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, list | tuple) and value:
        return tuple(str(item) for item in value)
    return default


@dataclass(frozen=True)
class DatasetConfig:
    """Resolved per-dataset retrieval configuration.

    All fields except ``known_tickers`` have static SEC-equivalent defaults available
    via :meth:`default_sec`. ``known_tickers`` is dataset-specific and loaded from the
    ``documents.ticker`` column for that dataset (which stores whatever entity identifier
    the loader inserted — ticker on SEC corpora, CUSIP/drug-name/etc. elsewhere).
    """

    id: str
    name: str
    description: str | None
    domain_label: str
    entity_label: str
    valid_forms: tuple[str, ...]
    metric_terms: tuple[str, ...]
    hyde_style_hint: str | None
    citation_label_template: str
    known_tickers: frozenset[str]

    @classmethod
    def default_sec(
        cls,
        *,
        dataset_id: str = "default",
        dataset_name: str = "sec-filings",
        known_tickers: frozenset[str] | set[str] | None = None,
    ) -> Self:
        return cls(
            id=dataset_id,
            name=dataset_name,
            description=None,
            domain_label=DEFAULT_SEC_DOMAIN_LABEL,
            entity_label=DEFAULT_ENTITY_LABEL,
            valid_forms=DEFAULT_VALID_FORMS,
            metric_terms=DEFAULT_METRIC_TERMS,
            hyde_style_hint=None,
            citation_label_template=DEFAULT_CITATION_LABEL_TEMPLATE,
            known_tickers=frozenset(t.upper() for t in (known_tickers or ())),
        )


def load_known_tickers(session: Session, dataset_id: str) -> frozenset[str]:
    rows = session.scalars(select(models.Document.ticker).where(models.Document.dataset_id == dataset_id).distinct())
    return frozenset(ticker.upper() for ticker in rows if ticker)


def load_dataset_config(session: Session, dataset_id: str) -> DatasetConfig:
    """Read the dataset row and resolve every field with code-level fallbacks.

    ``domain_label``, ``entity_label``, ``citation_label_template`` fall back to the
    SEC-flavored defaults. ``hyde_style_hint`` falls back to ``None`` (no hint). The
    JSONB list columns (``valid_forms``, ``metric_terms``) fall back to the SEC
    defaults when null or empty.
    """
    dataset = session.get(models.Dataset, dataset_id)
    if dataset is None:
        raise ValueError(f"Dataset {dataset_id!r} was not found")

    domain_label = getattr(dataset, "domain_label", None) or DEFAULT_SEC_DOMAIN_LABEL
    entity_label = getattr(dataset, "entity_label", None) or DEFAULT_ENTITY_LABEL
    valid_forms = _str_tuple(getattr(dataset, "valid_forms", None), DEFAULT_VALID_FORMS)
    metric_terms = _str_tuple(getattr(dataset, "metric_terms", None), DEFAULT_METRIC_TERMS)
    hyde_style_hint = getattr(dataset, "hyde_style_hint", None) or None
    citation_label_template = getattr(dataset, "citation_label_template", None) or DEFAULT_CITATION_LABEL_TEMPLATE

    return DatasetConfig(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        domain_label=domain_label,
        entity_label=entity_label,
        valid_forms=valid_forms,
        metric_terms=metric_terms,
        hyde_style_hint=hyde_style_hint,
        citation_label_template=citation_label_template,
        known_tickers=load_known_tickers(session, dataset_id),
    )


def format_citation(
    *,
    entity: str,
    filing_date: object,
    form_type: str,
    page: int,
    template: str = DEFAULT_CITATION_LABEL_TEMPLATE,
) -> str:
    """Render a citation label from primitive fields.

    Kept primitive (no SQLAlchemy or RetrievedChunk import) so both
    ``verification._evidence_label`` and ``generation.citation_label`` can share it.
    ``filing_date`` accepts anything with an ``isoformat()`` method or a string;
    falsy values render as ``"undated"``.

    Templates are validated at the API boundary (see ``_validate_citation_label_template``
    in ``rag_common.schemas``); the try/except below is defense-in-depth for templates
    that bypass validation (legacy rows, programmatic construction) so a misconfigured
    dataset does not crash every query.
    """
    if filing_date is None:
        rendered_date = "undated"
    elif hasattr(filing_date, "isoformat"):
        rendered_date = filing_date.isoformat()
    else:
        rendered_date = str(filing_date) or "undated"
    try:
        return template.format(
            entity=entity,
            filing_date=rendered_date,
            form_type=form_type,
            page=page,
        )
    except (KeyError, IndexError, ValueError) as exc:
        logger.error(
            "citation_template_render_failed",
            extra={"template": template, "error_class": type(exc).__name__, "error": str(exc)},
        )
        return DEFAULT_CITATION_LABEL_TEMPLATE.format(
            entity=entity,
            filing_date=rendered_date,
            form_type=form_type,
            page=page,
        )


__all__ = [
    "DEFAULT_CITATION_LABEL_TEMPLATE",
    "DEFAULT_ENTITY_LABEL",
    "DEFAULT_METRIC_TERMS",
    "DEFAULT_SEC_DOMAIN_LABEL",
    "DEFAULT_VALID_FORMS",
    "DatasetConfig",
    "format_citation",
    "load_dataset_config",
    "load_known_tickers",
]
