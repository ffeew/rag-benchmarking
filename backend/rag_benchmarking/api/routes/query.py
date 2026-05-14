from fastapi import APIRouter, HTTPException, status
from rag_common.schemas import QueryRequest, QueryResponse, TraceRead
from rag_retrieval.query import read_trace, run_query

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
        timings=query_trace.timings,
        citations=[citation_to_read(citation, document) for citation, document in citation_rows],
        created_at=query_trace.created_at,
    )
