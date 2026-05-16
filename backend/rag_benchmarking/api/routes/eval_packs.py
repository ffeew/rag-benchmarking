from fastapi import APIRouter, HTTPException, status
from rag_common.db import models
from rag_common.schemas import (
    EvalPackImportRequest,
    EvalPackImportResponse,
    EvalPackSummary,
)
from sqlalchemy import select

from rag_benchmarking.api.deps import AuthDep, DbSession
from rag_benchmarking.eval_packs import get_pack, list_packs
from rag_benchmarking.scripts.seed_eval_cases import seed_cases

router = APIRouter(tags=["eval-packs"])


@router.get("/v1/eval-packs")
def list_eval_packs(_auth: AuthDep) -> list[EvalPackSummary]:
    return list_packs()


@router.post("/v1/eval-packs/{pack_id}/import")
def import_eval_pack(
    pack_id: str,
    payload: EvalPackImportRequest,
    session: DbSession,
    _auth: AuthDep,
) -> EvalPackImportResponse:
    try:
        _summary, cases = get_pack(pack_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown eval pack: {pack_id}",
        ) from exc
    try:
        counts = seed_cases(payload.dataset_id, cases, dry_run=payload.dry_run)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    case_keys = [case.case_key for case in cases]
    if payload.dry_run or not case_keys:
        case_ids: list[str] = []
    else:
        # seed_cases opens its own session and commits; reload ids fresh here
        # via the request-scoped session so the response reflects committed state.
        case_ids = list(
            session.scalars(
                select(models.EvalCase.id).where(
                    models.EvalCase.dataset_id == payload.dataset_id,
                    models.EvalCase.case_key.in_(case_keys),
                )
            )
        )

    return EvalPackImportResponse(
        pack_id=pack_id,
        dataset_id=payload.dataset_id,
        created=counts["created"],
        updated=counts["updated"],
        skipped=counts["skipped"],
        case_ids=case_ids,
    )
