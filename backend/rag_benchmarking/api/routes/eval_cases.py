from fastapi import APIRouter, HTTPException, status
from rag_common.db import models
from rag_common.schemas import (
    EvalCaseCreateRequest,
    EvalCaseRead,
    EvalCaseUpdate,
    Page,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from rag_benchmarking.api.deps import AuthDep, DbSession
from rag_benchmarking.api.pagination import LimitParam, OffsetParam, paged_query

router = APIRouter(tags=["eval-cases"])


def _to_read(case: models.EvalCase) -> EvalCaseRead:
    return EvalCaseRead(
        id=case.id,
        dataset_id=case.dataset_id,
        case_key=case.case_key,
        category=case.category,
        difficulty=case.difficulty,
        question=case.question,
        expected_answer=case.expected_answer,
        expected_citations=case.expected_citations or [],
        expected_answer_spec=case.expected_answer_spec or {},
        expected_evidence=case.expected_evidence or [],
        verification_status=case.verification_status,
        verified_by=case.verified_by,
        verified_at=case.verified_at,
        gold_version=case.gold_version,
        tags=case.tags or [],
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


@router.post("/v1/eval-cases", status_code=status.HTTP_201_CREATED)
def create_eval_case(
    payload: EvalCaseCreateRequest,
    session: DbSession,
    _auth: AuthDep,
) -> EvalCaseRead:
    dataset = session.get(models.Dataset, payload.dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")
    if payload.case_key is not None:
        duplicate = session.scalar(
            select(models.EvalCase).where(
                models.EvalCase.dataset_id == payload.dataset_id,
                models.EvalCase.case_key == payload.case_key,
            )
        )
        if duplicate is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"case_key {payload.case_key!r} already exists for this dataset",
            )
    case = models.EvalCase(
        dataset_id=payload.dataset_id,
        case_key=payload.case_key,
        category=payload.category,
        difficulty=payload.difficulty,
        question=payload.question,
        expected_answer=payload.expected_answer,
        expected_citations=payload.expected_citations,
        expected_answer_spec=payload.expected_answer_spec.model_dump(mode="json"),
        expected_evidence=[item.model_dump(mode="json") for item in payload.expected_evidence],
        verification_status=payload.verification_status,
        verified_by=payload.verified_by,
        verified_at=payload.verified_at,
        gold_version=payload.gold_version,
        tags=payload.tags,
    )
    session.add(case)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Case violates a unique constraint (likely duplicate case_key).",
        ) from exc
    session.refresh(case)
    return _to_read(case)


@router.get("/v1/eval-cases")
def list_eval_cases(
    session: DbSession,
    _auth: AuthDep,
    dataset_id: str | None = None,
    category: str | None = None,
    difficulty: str | None = None,
    tag: str | None = None,
    limit: LimitParam = 50,
    offset: OffsetParam = 0,
) -> Page[EvalCaseRead]:
    base = select(models.EvalCase)
    if dataset_id is not None:
        base = base.where(models.EvalCase.dataset_id == dataset_id)
    if category is not None:
        base = base.where(models.EvalCase.category == category)
    if difficulty is not None:
        base = base.where(models.EvalCase.difficulty == difficulty)
    if tag is not None:
        # JSONB contains operator: tags column stores a list[str]
        base = base.where(models.EvalCase.tags.op("@>")([tag]))
    ordered = base.order_by(models.EvalCase.created_at.desc())
    rows, total = paged_query(session, base=base, ordered=ordered, limit=limit, offset=offset)
    return Page[EvalCaseRead](
        items=[_to_read(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/v1/eval-cases/{case_id}")
def read_eval_case(case_id: str, session: DbSession, _auth: AuthDep) -> EvalCaseRead:
    case = session.get(models.EvalCase, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Eval case not found")
    return _to_read(case)


@router.patch("/v1/eval-cases/{case_id}")
def update_eval_case(
    case_id: str,
    payload: EvalCaseUpdate,
    session: DbSession,
    _auth: AuthDep,
) -> EvalCaseRead:
    case = session.get(models.EvalCase, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Eval case not found")
    if payload.case_key is not None and payload.case_key != case.case_key:
        duplicate = session.scalar(
            select(models.EvalCase).where(
                models.EvalCase.dataset_id == case.dataset_id,
                models.EvalCase.case_key == payload.case_key,
                models.EvalCase.id != case.id,
            )
        )
        if duplicate is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"case_key {payload.case_key!r} already exists for this dataset",
            )
    update_data = payload.model_dump(exclude_unset=True)
    if "expected_answer_spec" in update_data:
        update_data["expected_answer_spec"] = (
            payload.expected_answer_spec.model_dump(mode="json") if payload.expected_answer_spec is not None else {}
        )
    if "expected_evidence" in update_data:
        update_data["expected_evidence"] = (
            [item.model_dump(mode="json") for item in payload.expected_evidence]
            if payload.expected_evidence is not None
            else []
        )
    for field, value in update_data.items():
        setattr(case, field, value)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Case violates a unique constraint.",
        ) from exc
    session.refresh(case)
    return _to_read(case)


@router.delete("/v1/eval-cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_eval_case(case_id: str, session: DbSession, _auth: AuthDep) -> None:
    case = session.get(models.EvalCase, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Eval case not found")
    referenced = session.scalar(
        select(func.count()).select_from(models.EvalResult).where(models.EvalResult.eval_case_id == case_id)
    )
    if referenced and referenced > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Eval case {case_id} is referenced by {referenced} eval_result(s). "
                "Delete the parent evaluation runs first if you want to remove this case."
            ),
        )
    session.delete(case)
    session.commit()
