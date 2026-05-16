from fastapi import APIRouter, HTTPException, status
from rag_common.db import models
from rag_common.schemas import DatasetCreate, DatasetRead, DatasetUpdate, Page
from sqlalchemy import select

from rag_benchmarking.api.deps import AuthDep, DbSession
from rag_benchmarking.api.pagination import LimitParam, OffsetParam, paged_query
from rag_benchmarking.api.serialization import dataset_to_read

router = APIRouter(prefix="/v1/datasets", tags=["datasets"])


@router.post("", status_code=status.HTTP_201_CREATED)
def create_dataset(payload: DatasetCreate, session: DbSession, _auth: AuthDep) -> DatasetRead:
    existing = session.scalar(select(models.Dataset).where(models.Dataset.name == payload.name))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Dataset name already exists")
    dataset = models.Dataset(
        name=payload.name,
        description=payload.description,
        default_query_settings=payload.default_query_settings,
        domain_label=payload.domain_label,
        entity_label=payload.entity_label,
        valid_forms=payload.valid_forms,
        metric_terms=payload.metric_terms,
        hyde_style_hint=payload.hyde_style_hint,
        citation_label_template=payload.citation_label_template,
    )
    session.add(dataset)
    session.commit()
    session.refresh(dataset)
    return dataset_to_read(session, dataset)


@router.get("")
def list_datasets(
    session: DbSession,
    _auth: AuthDep,
    limit: LimitParam = 50,
    offset: OffsetParam = 0,
) -> Page[DatasetRead]:
    base = select(models.Dataset)
    ordered = base.order_by(models.Dataset.created_at.desc())
    rows, total = paged_query(session, base=base, ordered=ordered, limit=limit, offset=offset)
    return Page[DatasetRead](
        items=[dataset_to_read(session, dataset) for dataset in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{dataset_id}")
def read_dataset(dataset_id: str, session: DbSession, _auth: AuthDep) -> DatasetRead:
    dataset = session.get(models.Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    return dataset_to_read(session, dataset)


@router.patch("/{dataset_id}")
def update_dataset(
    dataset_id: str,
    payload: DatasetUpdate,
    session: DbSession,
    _auth: AuthDep,
) -> DatasetRead:
    """Apply a partial update to a dataset.

    Only fields explicitly supplied in the request body are written; un-supplied fields
    are left untouched. Passing ``null`` for an override field clears it back to the
    SEC fallback at the next query.
    """
    dataset = session.get(models.Dataset, dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] != dataset.name:
        clash = session.scalar(
            select(models.Dataset).where(
                models.Dataset.name == updates["name"],
                models.Dataset.id != dataset_id,
            )
        )
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Dataset name already exists",
            )

    for field, value in updates.items():
        setattr(dataset, field, value)

    session.commit()
    session.refresh(dataset)
    return dataset_to_read(session, dataset)
