from pathlib import Path

from rag_common.config import Settings, get_settings
from rag_common.db import models
from rag_common.storage.minio import ObjectStore
from rag_retrieval.dataset_config import (
    DEFAULT_CITATION_LABEL_TEMPLATE,
    DEFAULT_ENTITY_LABEL,
    DEFAULT_METRIC_TERMS,
    DEFAULT_VALID_FORMS,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag_benchmarking.ingestion.metadata import parse_filing_filename, raw_object_key, sha256_file

SEC_DATASET_NAME = "sec-filings"
SEC_DOMAIN_LABEL = "SEC filings of US public companies"


def get_or_create_dataset(
    session: Session,
    *,
    name: str,
    description: str | None,
    default_query_settings: dict[str, object] | None = None,
    domain_label: str | None = None,
    entity_label: str | None = None,
    valid_forms: list[str] | None = None,
    metric_terms: list[str] | None = None,
    hyde_style_hint: str | None = None,
    citation_label_template: str | None = None,
) -> models.Dataset:
    dataset = session.scalar(select(models.Dataset).where(models.Dataset.name == name))
    if dataset:
        return dataset
    dataset = models.Dataset(
        name=name,
        description=description,
        default_query_settings=default_query_settings or {},
        domain_label=domain_label,
        entity_label=entity_label,
        valid_forms=valid_forms,
        metric_terms=metric_terms,
        hyde_style_hint=hyde_style_hint,
        citation_label_template=citation_label_template,
    )
    session.add(dataset)
    session.flush()
    return dataset


def register_pdf_path(
    session: Session,
    *,
    dataset: models.Dataset,
    path: Path,
    settings: Settings | None = None,
) -> tuple[models.Document, bool]:
    resolved = settings or get_settings()
    metadata = parse_filing_filename(path)
    checksum = sha256_file(path)
    existing = session.scalar(
        select(models.Document).where(
            models.Document.dataset_id == dataset.id,
            models.Document.checksum == checksum,
        )
    )
    if existing:
        return existing, False

    key = raw_object_key(
        dataset_id=dataset.id,
        ticker=metadata.ticker,
        form_type=metadata.form_type,
        filing_date=metadata.filing_date,
        checksum=checksum,
    )
    stored = ObjectStore(resolved).put_file(
        bucket=resolved.raw_document_bucket,
        key=key,
        path=path,
        content_type="application/pdf",
    )
    document = models.Document(
        dataset_id=dataset.id,
        ticker=metadata.ticker,
        form_type=metadata.form_type,
        filing_date=metadata.filing_date,
        report_period=None,
        fiscal_year=metadata.filing_date.year if metadata.filing_date else None,
        fiscal_quarter=None,
        checksum=checksum,
        minio_bucket=stored.bucket,
        minio_key=stored.key,
        minio_version_id=stored.version_id,
        byte_size=stored.size,
    )
    session.add(document)
    session.flush()
    return document, True


def register_local_corpus(
    session: Session,
    *,
    dataset_name: str,
    description: str | None,
    path: Path | None = None,
    settings: Settings | None = None,
    domain_label: str | None = None,
    entity_label: str | None = None,
    valid_forms: list[str] | None = None,
    metric_terms: list[str] | None = None,
    hyde_style_hint: str | None = None,
    citation_label_template: str | None = None,
) -> tuple[models.Dataset, list[models.Document], int, int]:
    resolved = settings or get_settings()
    corpus_path = path or resolved.local_corpus_path
    # Eagerly populate SEC defaults when the caller registers the canonical SEC corpus
    # without supplying explicit overrides. Non-default dataset names stay null and
    # rely on the runtime fallback in rag_retrieval.dataset_config.load_dataset_config.
    if dataset_name == SEC_DATASET_NAME:
        if domain_label is None:
            domain_label = SEC_DOMAIN_LABEL
        if entity_label is None:
            entity_label = DEFAULT_ENTITY_LABEL
        if valid_forms is None:
            valid_forms = list(DEFAULT_VALID_FORMS)
        if metric_terms is None:
            metric_terms = list(DEFAULT_METRIC_TERMS)
        if citation_label_template is None:
            citation_label_template = DEFAULT_CITATION_LABEL_TEMPLATE
    dataset = get_or_create_dataset(
        session,
        name=dataset_name,
        description=description,
        domain_label=domain_label,
        entity_label=entity_label,
        valid_forms=valid_forms,
        metric_terms=metric_terms,
        hyde_style_hint=hyde_style_hint,
        citation_label_template=citation_label_template,
    )
    documents: list[models.Document] = []
    created = 0
    reused = 0
    for pdf_path in sorted(corpus_path.glob("*/*.pdf")):
        document, is_created = register_pdf_path(
            session,
            dataset=dataset,
            path=pdf_path,
            settings=resolved,
        )
        documents.append(document)
        if is_created:
            created += 1
        else:
            reused += 1
    return dataset, documents, created, reused
