from dataclasses import dataclass
from typing import Any

from rag_common.config import Settings, get_settings
from rag_common.db import models
from rag_common.providers.openrouter import OpenRouterClient, ProviderError
from rag_common.schemas import QueryFilters
from rag_common.usage import TokenUsage, from_openrouter_usage
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from rag_retrieval.planning import RetrievalPlan


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: models.Chunk
    document: models.Document
    score: float
    semantic_rank: int | None
    lexical_rank: int | None
    rerank_score: float | None = None


def apply_filters(
    statement: Any,
    *,
    dataset_id: str,
    plan: RetrievalPlan,
    filters: QueryFilters,
) -> Any:
    statement = statement.join(models.Document, models.Document.id == models.Chunk.document_id)
    statement = statement.where(models.Document.dataset_id == dataset_id, models.Chunk.is_active.is_(True))
    tickers = sorted({*(filters.ticker or []), *plan.target_tickers})
    if tickers:
        statement = statement.where(models.Document.ticker.in_([ticker.upper() for ticker in tickers]))
    forms = sorted({*(filters.form_type or []), *plan.forms})
    if forms:
        statement = statement.where(models.Document.form_type.in_([form.upper() for form in forms]))
    if filters.filing_date_start:
        statement = statement.where(models.Document.filing_date >= filters.filing_date_start)
    if filters.filing_date_end:
        statement = statement.where(models.Document.filing_date <= filters.filing_date_end)
    if filters.report_period_start:
        statement = statement.where(models.Document.report_period >= filters.report_period_start)
    if filters.report_period_end:
        statement = statement.where(models.Document.report_period <= filters.report_period_end)
    if filters.document_ids:
        statement = statement.where(models.Document.id.in_(filters.document_ids))
    if plan.latest and (tickers or forms):
        # Build the "latest filing_date" subquery scoped to whatever dimensions the
        # caller asked about. Previously, a forms-only "latest" query (e.g. "latest
        # 10-K") used the dataset-wide max filing_date — almost certainly wrong on
        # corpora where 10-Ks lag 10-Qs.
        latest_conditions = [models.Document.dataset_id == dataset_id]
        if tickers:
            latest_conditions.append(models.Document.ticker.in_([t.upper() for t in tickers]))
        if forms:
            latest_conditions.append(models.Document.form_type.in_([form.upper() for form in forms]))
        latest_subquery = select(func.max(models.Document.filing_date)).where(*latest_conditions).scalar_subquery()
        statement = statement.where(
            or_(models.Document.filing_date == latest_subquery, models.Document.filing_date.is_(None))
        )
    return statement


def reciprocal_rank_fusion(
    semantic_rows: list[tuple[models.Chunk, models.Document, float]],
    lexical_rows: list[tuple[models.Chunk, models.Document, float]],
    limit: int,
) -> list[RetrievedChunk]:
    fused: dict[str, dict[str, Any]] = {}
    rank_constant = 60.0
    for rank, (chunk, document, distance) in enumerate(semantic_rows, start=1):
        entry = fused.setdefault(
            chunk.id,
            {
                "chunk": chunk,
                "document": document,
                "semantic_rank": None,
                "lexical_rank": None,
                "score": 0.0,
            },
        )
        entry["semantic_rank"] = rank
        entry["score"] += 1.0 / (rank_constant + rank)
        entry["score"] += max(0.0, 1.0 - float(distance)) * 0.01
    for rank, (chunk, document, lexical_score) in enumerate(lexical_rows, start=1):
        entry = fused.setdefault(
            chunk.id,
            {
                "chunk": chunk,
                "document": document,
                "semantic_rank": None,
                "lexical_rank": None,
                "score": 0.0,
            },
        )
        entry["lexical_rank"] = rank
        entry["score"] += 1.0 / (rank_constant + rank)
        entry["score"] += float(lexical_score) * 0.01
    ranked = sorted(fused.values(), key=lambda entry: entry["score"], reverse=True)
    return [
        RetrievedChunk(
            chunk=entry["chunk"],
            document=entry["document"],
            score=float(entry["score"]),
            semantic_rank=entry["semantic_rank"],
            lexical_rank=entry["lexical_rank"],
        )
        for entry in ranked[:limit]
    ]


def hybrid_retrieve(
    session: Session,
    *,
    dataset_id: str,
    question: str,
    filters: QueryFilters,
    plan: RetrievalPlan,
    top_k: int,
    settings: Settings | None = None,
    semantic_query: str | None = None,
) -> tuple[list[RetrievedChunk], dict[str, Any], TokenUsage, TokenUsage]:
    """Hybrid retrieval over pgvector + Postgres FTS with optional rerank.

    When ``semantic_query`` is provided, it is embedded for vector search while FTS still
    uses the original ``question``. This supports HyDE: pass the hypothetical answer
    passage as ``semantic_query`` to align the vector probe with filing-style text while
    keeping lexical matches anchored on the literal investor terms.
    """
    resolved = settings or get_settings()
    provider = OpenRouterClient(resolved)
    embedding_model = resolved.openrouter_embedding_model or "mock-embedding"
    semantic_enabled = resolved.semantic_candidates > 0
    lexical_enabled = resolved.full_text_candidates > 0
    if not semantic_enabled and not lexical_enabled:
        raise ValueError(
            "hybrid_retrieve requires at least one channel: "
            "semantic_candidates and full_text_candidates cannot both be zero."
        )
    embedding_usage = TokenUsage()
    rerank_usage = TokenUsage()
    semantic_rows: list[tuple[models.Chunk, models.Document, float]] = []
    lexical_rows: list[tuple[models.Chunk, models.Document, float]] = []
    embedding_model_used: str | None = None
    embedding_provider_used: str | None = None

    if semantic_enabled:
        embedding_text = semantic_query if semantic_query else question
        embedding_result = provider.embeddings(
            [embedding_text],
            model=embedding_model,
            dimensions=resolved.embedding_dimension,
        )
        query_vector = embedding_result.vectors[0]
        embedding_usage = from_openrouter_usage(
            embedding_result.metadata.usage,
            provider=embedding_result.metadata.provider,
            model=embedding_result.metadata.model,
        )
        embedding_model_used = embedding_result.metadata.model
        embedding_provider_used = embedding_result.metadata.provider

        distance = models.Embedding.vector.cosine_distance(query_vector).label("distance")
        semantic_statement = (
            select(models.Chunk, models.Document, distance)
            .join(models.Embedding, models.Embedding.chunk_id == models.Chunk.id)
            .where(models.Embedding.model == (embedding_result.metadata.model or embedding_model))
            .order_by(distance)
            .limit(resolved.semantic_candidates)
        )
        semantic_statement = apply_filters(
            semantic_statement,
            dataset_id=dataset_id,
            plan=plan,
            filters=filters,
        )
        semantic_rows = [(row[0], row[1], float(row[2])) for row in session.execute(semantic_statement).all()]

    if lexical_enabled:
        ts_query = func.websearch_to_tsquery("english", question)
        rank = func.ts_rank_cd(func.to_tsvector("english", models.Chunk.normalized_text), ts_query).label("rank")
        lexical_statement = (
            select(models.Chunk, models.Document, rank)
            .where(func.to_tsvector("english", models.Chunk.normalized_text).op("@@")(ts_query))
            .order_by(desc(rank))
            .limit(resolved.full_text_candidates)
        )
        lexical_statement = apply_filters(
            lexical_statement,
            dataset_id=dataset_id,
            plan=plan,
            filters=filters,
        )
        lexical_rows = [(row[0], row[1], float(row[2])) for row in session.execute(lexical_statement).all()]

    fused = reciprocal_rank_fusion(semantic_rows, lexical_rows, resolved.fused_candidates)
    trace: dict[str, Any] = {
        "embedding_model": embedding_model_used,
        "embedding_provider": embedding_provider_used,
        "semantic_count": len(semantic_rows),
        "lexical_count": len(lexical_rows),
        "fused_count": len(fused),
        "semantic_enabled": semantic_enabled,
        "lexical_enabled": lexical_enabled,
        "rerank_degraded": False,
        "semantic_query_used": semantic_query is not None,
        "semantic_query_preview": (semantic_query[:200] if semantic_query else None),
    }
    if resolved.reranker_enabled and fused:
        try:
            candidates = fused[: resolved.rerank_candidates]
            rerank = provider.rerank(query=question, documents=[item.chunk.text for item in candidates])
            rerank_usage = from_openrouter_usage(
                rerank.metadata.usage,
                provider=rerank.metadata.provider,
                model=rerank.metadata.model,
            )
            by_index = dict(enumerate(candidates))
            reranked: list[RetrievedChunk] = []
            for index, score in zip(rerank.ranked_indices, rerank.scores, strict=False):
                if index in by_index:
                    item = by_index[index]
                    reranked.append(
                        RetrievedChunk(
                            chunk=item.chunk,
                            document=item.document,
                            score=item.score,
                            semantic_rank=item.semantic_rank,
                            lexical_rank=item.lexical_rank,
                            rerank_score=score,
                        )
                    )
            seen = {item.chunk.id for item in reranked}
            reranked.extend(item for item in fused if item.chunk.id not in seen)
            fused = reranked
            trace.update(
                {
                    "rerank_model": rerank.metadata.model,
                    "rerank_provider": rerank.metadata.provider,
                    "rerank_count": len(rerank.ranked_indices),
                }
            )
        except ProviderError as exc:
            trace["rerank_degraded"] = True
            trace["rerank_error"] = str(exc)
    return fused[:top_k], trace, embedding_usage, rerank_usage
