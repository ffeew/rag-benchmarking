from fastapi import APIRouter, HTTPException, status
from rag_common.db import models
from rag_common.schemas import EvalRunRead, EvaluationCreate, EvaluationCreateResponse, Page
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from rag_benchmarking.api.deps import AuthDep, DbSession, SettingsDep
from rag_benchmarking.api.pagination import LimitParam, OffsetParam, paged_query
from rag_benchmarking.api.serialization import eval_run_to_read
from rag_benchmarking.workers.dispatch import dispatch_job

router = APIRouter(tags=["evaluations"])


def _has_scientific_gold(case: models.EvalCase) -> bool:
    answer_spec = case.expected_answer_spec or {}
    expected_evidence = case.expected_evidence or []
    answer_type = answer_spec.get("answer_type")
    has_answer_gold = answer_type in {"insufficient", "refusal"} or bool(
        answer_spec.get("expected_values") or answer_spec.get("required_claims")
    )
    has_evidence_gold = any(
        isinstance(item, dict)
        and item.get("page_number") is not None
        and (item.get("document_id") or (item.get("ticker") and item.get("form_type")))
        for item in expected_evidence
    )
    return case.verification_status == "verified" and (has_answer_gold or has_evidence_gold)


def _validate_scientific_cases(session: DbSession, dataset_id: str, case_ids: list[str]) -> None:
    statement = select(models.EvalCase).where(models.EvalCase.dataset_id == dataset_id)
    if case_ids:
        statement = statement.where(models.EvalCase.id.in_(case_ids))
    cases = list(session.scalars(statement.order_by(models.EvalCase.created_at).limit(80)))
    if not cases:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Scientific evaluations require at least one verified eval case.",
        )
    invalid = [case.case_key or case.id for case in cases if not _has_scientific_gold(case)]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Scientific evaluations require verified cases with structured expected_answer_spec "
                f"or expected_evidence. Invalid cases: {', '.join(invalid[:10])}"
            ),
        )


@router.post("/v1/evaluations")
def create_evaluation(
    payload: EvaluationCreate,
    session: DbSession,
    settings: SettingsDep,
    _auth: AuthDep,
) -> EvaluationCreateResponse:
    dataset = session.get(models.Dataset, payload.dataset_id)
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    case_ids = list(payload.case_ids or [])
    if payload.cases:
        for case in payload.cases:
            db_case = models.EvalCase(
                dataset_id=payload.dataset_id,
                question=case.question,
                expected_answer=case.expected_answer,
                expected_citations=case.expected_citations,
                expected_answer_spec=case.expected_answer_spec.model_dump(mode="json"),
                expected_evidence=[item.model_dump(mode="json") for item in case.expected_evidence],
                verification_status=case.verification_status,
                verified_by=case.verified_by,
                verified_at=case.verified_at,
                gold_version=case.gold_version,
                tags=case.tags,
            )
            session.add(db_case)
            session.flush()
            case_ids.append(db_case.id)

    if payload.benchmark_profile == "scientific":
        _validate_scientific_cases(session, payload.dataset_id, case_ids)

    eval_run = models.EvalRun(
        dataset_id=payload.dataset_id,
        status="queued",
        run_config={
            "case_ids": case_ids,
            "system_variants": payload.system_variants,
            "benchmark_profile": payload.benchmark_profile,
            "bootstrap_seed": 1729,
        },
        system_variant=",".join(payload.system_variants),
        model_metadata={
            "chat_model": settings.openrouter_chat_model,
            "judge_model": settings.openrouter_judge_model,
            "embedding_model": settings.openrouter_embedding_model,
            "rerank_model": settings.openrouter_rerank_model,
        },
    )
    session.add(eval_run)
    session.flush()
    job = models.Job(
        job_type="evaluation",
        status="queued",
        progress=0,
        current_step="queued",
        dataset_id=payload.dataset_id,
        eval_run_id=eval_run.id,
        metadata_={"variants": payload.system_variants},
    )
    session.add(job)
    session.flush()
    eval_run.job_id = job.id
    # Commit the queued row before dispatching so the sweeper can recover it
    # even if this request crashes before we can write back the task id.
    session.commit()

    task_id = dispatch_job(job)
    if task_id is not None:
        job.celery_task_id = task_id
        session.commit()

    return EvaluationCreateResponse(eval_run_id=eval_run.id, job_id=job.id)


@router.get("/v1/evaluations/{eval_run_id}")
def read_evaluation(eval_run_id: str, session: DbSession, _auth: AuthDep) -> EvalRunRead:
    eval_run = session.scalar(
        select(models.EvalRun).options(selectinload(models.EvalRun.results)).where(models.EvalRun.id == eval_run_id)
    )
    if eval_run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation not found")
    return eval_run_to_read(eval_run)


@router.get("/v1/evaluations")
def list_evaluations(
    session: DbSession,
    _auth: AuthDep,
    dataset_id: str | None = None,
    limit: LimitParam = 50,
    offset: OffsetParam = 0,
) -> Page[EvalRunRead]:
    base = select(models.EvalRun)
    if dataset_id:
        base = base.where(models.EvalRun.dataset_id == dataset_id)
    # selectinload is attached to `ordered` only — counting via `base` must not
    # trigger a child SELECT for the results relationship.
    ordered = base.options(selectinload(models.EvalRun.results)).order_by(models.EvalRun.created_at.desc())
    rows, total = paged_query(session, base=base, ordered=ordered, limit=limit, offset=offset)
    return Page[EvalRunRead](
        items=[eval_run_to_read(run) for run in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
