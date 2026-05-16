from fastapi import APIRouter, HTTPException, Query, status
from rag_common.schemas import QueryRequest, QueryResponse, TraceRead, TraceSummary
from rag_retrieval.query import list_traces, read_trace, run_query

from rag_benchmarking.api.deps import AuthDep, DbSession, SettingsDep
from rag_benchmarking.api.serialization import citation_to_read

router = APIRouter(tags=["query"])


@router.post("/v1/query")
def query(
    payload: QueryRequest,
    session: DbSession,
    settings: SettingsDep,
    _auth: AuthDep,
) -> QueryResponse:
    try:
        response = run_query(session, request=payload, settings=settings)
        session.commit()
        return response
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/v1/traces")
def list_traces_endpoint(
    session: DbSession,
    _auth: AuthDep,
    dataset_id: str | None = None,
    question_contains: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[TraceSummary]:
    rows = list_traces(
        session,
        dataset_id=dataset_id,
        question_contains=question_contains,
        limit=limit,
    )
    summaries: list[TraceSummary] = []
    for row in rows:
        verifier = row.verifier_result or {}
        raw_confidence = verifier.get("confidence") if isinstance(verifier, dict) else None
        confidence: float | None
        try:
            confidence = float(raw_confidence) if raw_confidence is not None else None
        except (TypeError, ValueError):
            confidence = None
        summaries.append(
            TraceSummary(
                id=row.id,
                dataset_id=row.dataset_id,
                user_question=row.user_question,
                retrieval_mode=row.retrieval_mode,
                confidence=confidence,
                created_at=row.created_at,
            )
        )
    return summaries


@router.get("/v1/traces/{trace_id}")
def trace(trace_id: str, session: DbSession, _auth: AuthDep) -> TraceRead:
    try:
        query_trace, citation_rows = read_trace(session, trace_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return TraceRead(
        id=query_trace.id,
        dataset_id=query_trace.dataset_id,
        user_question=query_trace.user_question,
        retrieval_mode=query_trace.retrieval_mode,
        plan=query_trace.plan,
        retrieval_calls=query_trace.retrieval_calls,
        verifier_result=query_trace.verifier_result,
        model_metadata=query_trace.model_metadata,
        final_answer_metadata=query_trace.final_answer_metadata,
        answer=query_trace.answer,
        timings=query_trace.timings,
        citations=[citation_to_read(citation, document) for citation, document in citation_rows],
        created_at=query_trace.created_at,
    )
