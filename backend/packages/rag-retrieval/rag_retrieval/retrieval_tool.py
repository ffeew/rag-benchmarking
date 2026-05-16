"""Tool-using retrieval agent.

This module replaces the historical planner -> retrieve -> verify -> retry pipeline for
the ``full_agentic`` retrieval mode with one bounded agent that exposes a single tool:
``retrieve_evidence``. The agent decides when, how many times, and with what filters to
call the tool, then emits a structured ``RetrievalAgentOutput`` carrying the chunks it
would cite plus verification-style signals (missing subclaims, contradictions). The
generator step downstream is unchanged.

The tool internally runs HyDE (Hypothetical Document Embeddings) + hybrid retrieval
(pgvector + Postgres FTS + RRF) + optional reranking, so every tool call benefits from
the full retrieval stack. When the chat agent is unavailable (mock providers, missing
key, or upstream failure), the orchestrator falls back to a single deterministic
``infer_query_plan`` + ``hybrid_retrieve`` + ``keyword_verify_evidence`` pass so
retrieval never goes dark.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, BeforeValidator, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import UsageLimits
from rag_common.config import Settings, get_settings
from rag_common.enums import Provider, QueryType
from rag_common.schemas import QueryFilters
from rag_common.usage import TokenUsage, merge, safe_pydantic_ai_usage

from rag_retrieval.agents import (
    AGENT_RETRYABLE_ERRORS,
    agent_available,
    build_chat_model,
    deterministic_model_settings,
)
from rag_retrieval.dataset_config import DatasetConfig
from rag_retrieval.hybrid import RetrievedChunk, hybrid_retrieve
from rag_retrieval.hyde import generate_hyde_passage
from rag_retrieval.observability import LogToolCalls
from rag_retrieval.planning import (
    VALID_QUERY_TYPES,
    RetrievalPlan,
    infer_query_plan,
)
from rag_retrieval.verification import keyword_verify_evidence

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool I/O and agent output schemas
# ---------------------------------------------------------------------------


class ToolRetrievalHit(BaseModel):
    """One chunk returned by ``retrieve_evidence``.

    The ``chunk_id`` is the stable identifier the agent should use when filling
    ``selected_chunk_ids`` in its final output. ``snippet`` is intentionally short so the
    LLM can read several hits without blowing the context window.
    """

    chunk_id: str
    ticker: str
    form_type: str
    filing_date: str | None
    page: int
    contains_table: bool
    score: float
    snippet: str


class RetrievalAgentOutput(BaseModel):
    """Final structured output of the retrieval agent.

    Combines what the legacy planner+verifier produced into one schema: the
    metadata the agent inferred (tickers, forms, query_type, latest, subquestions),
    the evidence it would cite (``selected_chunk_ids``), and the gaps it noticed
    (``missing_subclaims``, ``contradictions``).
    """

    selected_chunk_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Stable chunk_ids returned by earlier retrieve_evidence calls that materially "
            "support the question. Prefer 4-10; never more than 15."
        ),
    )
    missing_subclaims: list[str] = Field(
        default_factory=list,
        description="Parts of the question no retrieved chunk answered.",
    )
    contradictions: list[str] = Field(
        default_factory=list,
        description="Notable contradictions between retrieved chunks.",
    )
    target_tickers: list[str] = Field(
        default_factory=list,
        description="Upper-case tickers in scope (only those you used in tool calls).",
    )
    forms: list[str] = Field(
        default_factory=list,
        description="Subset of the dataset's known forms you scoped to, if any.",
    )
    metrics: list[str] = Field(
        default_factory=list,
        description="Specific metrics or topics the question asks about (e.g. revenue, R&D).",
    )
    query_type: QueryType = Field(
        default=QueryType.FACT_LOOKUP,
        description=(
            "One of: fact_lookup, table_lookup, comparison, trend, thematic_synthesis, "
            "latest_filing, insufficient_evidence."
        ),
    )
    latest: bool = Field(
        default=False,
        description="True if the user wanted the most recent filing in scope.",
    )
    subquestions: list[str] = Field(
        default_factory=list,
        description="Independently-answerable subquestions you decomposed the question into.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Calibrated confidence (0-1) that the selected chunks answer the question.",
    )
    insufficient_evidence: bool = Field(
        default=False,
        description="True if no combination of tool calls produced relevant evidence.",
    )
    insufficiency_reason: str | None = Field(
        default=None,
        description="Short explanation when insufficient_evidence is True; null otherwise.",
    )
    reasoning: str = Field(
        default="",
        description="One or two sentences explaining the retrieval strategy you used.",
    )


# ---------------------------------------------------------------------------
# RunContext deps and orchestrator result
# ---------------------------------------------------------------------------


@dataclass
class RetrievalAgentDeps:
    """Mutable state threaded through the retrieval agent's tool calls.

    ``chunk_lookup`` and ``tool_calls`` are appended to by the tool function so the
    orchestrator can materialize ``selected_chunk_ids`` back to full ``RetrievedChunk``
    objects and persist a per-call trace. ``usage_records`` collects every TokenUsage
    incurred inside the tool (HyDE, embedding, rerank) so the orchestrator can sum them
    once after the agent returns. ``dataset_config`` carries the corpus identity, valid
    forms, and entity label so dynamic instructions and ``_normalize_filters`` stay
    domain-neutral.
    """

    session: "Session"
    dataset_id: str
    settings: Settings
    user_question: str
    base_filters: QueryFilters
    base_plan: RetrievalPlan
    known_tickers: frozenset[str]
    dataset_config: DatasetConfig = field(default_factory=DatasetConfig.default_sec)
    chunk_lookup: dict[str, RetrievedChunk] = field(default_factory=dict)
    tool_calls: list[dict[str, object]] = field(default_factory=list)
    hyde_usage_records: list[TokenUsage] = field(default_factory=list)
    embedding_usage_records: list[TokenUsage] = field(default_factory=list)
    rerank_usage_records: list[TokenUsage] = field(default_factory=list)


@dataclass(frozen=True)
class AgentRetrievalResult:
    """The full retrieval-phase outcome returned to ``run_query``.

    ``chunks`` is the final evidence set (already truncated to ``evidence_top_k``),
    ``tool_calls`` is the per-call trace, and ``output`` is the agent's structured
    output (or a synthesized stand-in on the fallback path). Token usage is split
    by role so the orchestrator can route each slice into the correct ``RoleUsage``
    bucket without re-deriving where the tokens came from.
    """

    chunks: list[RetrievedChunk]
    tool_calls: list[dict[str, object]]
    output: RetrievalAgentOutput
    hyde_usage: TokenUsage
    embedding_usage: TokenUsage
    rerank_usage: TokenUsage


# ---------------------------------------------------------------------------
# Tool helpers
# ---------------------------------------------------------------------------


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()  # noqa: DTZ007 - tolerate naive ISO dates from LLM
        except ValueError:
            return None


def _coerce_str_list(value: object) -> object:
    """JSON-decode a string-encoded list so pydantic's array validator accepts it.

    Some chat models (glm-4.7 in particular) occasionally emit list-valued tool
    arguments as JSON-string-encoded literals (e.g. ``'["AAPL"]'``) instead of as
    real JSON arrays. Pydantic's strict ``list_type`` validator rejects these, and
    each rejection burns a tool-retry slot without ever reaching ``call_tool`` —
    the model just rebuilds the same malformed payload and times out. Try a single
    JSON-decode pass before validation; pass through unchanged on anything else so
    genuine type errors still surface for human-eyeballed diagnosis.
    """
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return value
    return value


_StrListArg = Annotated[list[str] | None, BeforeValidator(_coerce_str_list)]


def _short_snippet(text: str, limit: int = 400) -> str:
    import re

    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "..."


def _sum_usages(records: list[TokenUsage]) -> TokenUsage:
    accumulator = TokenUsage()
    for record in records:
        accumulator = merge(accumulator, record)
    return accumulator


@dataclass(frozen=True)
class _NormalizedFilters:
    """Filter normalization result that surfaces what the safe-list dropped.

    Previously the agent saw zero hits with no trace signal when the LLM picked a
    near-miss form name ("Form 10-K" instead of "10-K") or an off-corpus ticker.
    Returning the dropped values lets the tool wrapper surface them via ModelRetry
    so the agent can self-correct on the next call.
    """

    safe_tickers: list[str]
    safe_forms: list[str]
    dropped_tickers: list[str]
    dropped_forms: list[str]


def _normalize_filters(
    *,
    tickers: list[str] | None,
    form_types: list[str] | None,
    known_tickers: frozenset[str],
    valid_forms: tuple[str, ...] | frozenset[str],
) -> _NormalizedFilters:
    proposed_tickers = {ticker.upper() for ticker in (tickers or [])}
    safe_tickers = sorted(proposed_tickers & known_tickers)
    dropped_tickers = sorted(proposed_tickers - known_tickers)
    valid_form_set = {form.upper() for form in valid_forms}
    proposed_forms = {form.upper() for form in (form_types or [])}
    safe_forms = sorted(proposed_forms & valid_form_set)
    dropped_forms = sorted(proposed_forms - valid_form_set)
    return _NormalizedFilters(
        safe_tickers=safe_tickers,
        safe_forms=safe_forms,
        dropped_tickers=dropped_tickers,
        dropped_forms=dropped_forms,
    )


def _sub_plan(
    *,
    base: RetrievalPlan,
    tickers: list[str],
    forms: list[str],
    filing_date_start: date | None,
    filing_date_end: date | None,
) -> RetrievalPlan:
    return RetrievalPlan(
        target_tickers=tickers or base.target_tickers,
        forms=forms or base.forms,
        filing_date_start=filing_date_start or base.filing_date_start,
        filing_date_end=filing_date_end or base.filing_date_end,
        metrics=base.metrics,
        subquestions=base.subquestions,
        query_type=base.query_type,
        latest=base.latest,
        ambiguity=None,
        reasoning=None,
    )


def _materialize_selected(
    output: RetrievalAgentOutput,
    chunk_lookup: dict[str, RetrievedChunk],
    evidence_top_k: int,
) -> list[RetrievedChunk]:
    selected: list[RetrievedChunk] = []
    seen: set[str] = set()
    for chunk_id in output.selected_chunk_ids:
        item = chunk_lookup.get(chunk_id)
        if item is None or item.chunk.id in seen:
            continue
        selected.append(item)
        seen.add(item.chunk.id)
    if not selected and chunk_lookup:
        # The agent emitted an empty selection. Trust it when ``insufficient_evidence``
        # is set — that is the explicit "I found nothing useful" signal and the previous
        # top-K safety net silently overrode it, producing plausible-but-unsupported
        # answers. Otherwise treat the empty selection as a forgotten-IDs slip and fall
        # back to top-K of what the agent retrieved.
        if output.insufficient_evidence:
            return []
        ranked = sorted(
            chunk_lookup.values(),
            key=lambda item: item.rerank_score if item.rerank_score is not None else item.score,
            reverse=True,
        )
        selected = ranked[:evidence_top_k]
    return selected[:evidence_top_k]


def _validate_query_type(value: str) -> QueryType:
    return QueryType(value) if value in VALID_QUERY_TYPES else QueryType.FACT_LOOKUP


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


_RETRIEVAL_AGENT_INSTRUCTIONS = """\
You are the retrieval agent for a filings RAG system.

You have ONE tool: `retrieve_evidence`. Call it as many times as you need (subject to a
small budget) to gather the chunks required to answer the user's question. You do NOT
write the final answer - a downstream generator does. Your job is to return the
chunk_ids worth citing plus structured signals about what was missing or contradictory.

Strategy:
- Single-entity factual lookups usually need one call.
- Comparisons across N entities: call the tool once per entity (e.g. ticker) so coverage
  is balanced rather than dominated by one entity.
- Thematic / cross-entity questions: call once per entity in scope, then optionally one
  final call with no entity filter for broader corpus wording.
- "Latest" or "current" questions: use the filing_date filters or the `latest`-style
  framing in your query; do NOT assume a calendar year.
- Use HyDE (the default `use_hyde=true`) for qualitative or vague queries. Turn it OFF
  (`use_hyde=false`) when the question hinges on an exact phrase, number, or proper
  noun that is more likely to appear in the corpus verbatim.

After your tool calls, emit:
- `selected_chunk_ids`: the chunk_ids from any tool result that materially support the
  question. Be selective - prefer 4-10, never more than 15. Use chunk_ids verbatim.
- `missing_subclaims`: parts of the question no retrieved chunk answered.
- `contradictions`: notable disagreements between retrieved chunks.
- `target_tickers`, `forms`, `query_type`, `latest`, `subquestions`: the planning
  metadata you inferred while working. These are used for the trace and the generator
  prompt; keep them faithful to what you actually scoped to.
- `confidence`: 0-1 calibrated; <0.3 if you found little, 0.5-0.7 partial, >=0.8 firm.
- `insufficient_evidence` + `insufficiency_reason`: only if no combination of tool calls
  produced relevant evidence.
- `reasoning`: one or two sentences naming the strategy you used.

NEVER invent a chunk_id you did not receive from a tool call. Only known tickers and
known forms are honored by the filter - unknown values are silently dropped.
"""


def perform_retrieve_evidence(
    deps: RetrievalAgentDeps,
    query: str,
    *,
    tickers: list[str] | None = None,
    form_types: list[str] | None = None,
    filing_date_start: str | None = None,
    filing_date_end: str | None = None,
    top_k: int = 6,
    use_hyde: bool = True,
) -> list[ToolRetrievalHit]:
    """Execute one retrieve_evidence call.

    Extracted from the agent tool closure so it can be tested without spinning up a
    full ``Agent`` and ``RunContext``. The agent tool is a thin wrapper that just
    unpacks ``ctx.deps`` and forwards to this function.
    """
    normalized = _normalize_filters(
        tickers=tickers,
        form_types=form_types,
        known_tickers=deps.known_tickers,
        valid_forms=deps.dataset_config.valid_forms,
    )
    safe_tickers = normalized.safe_tickers
    safe_forms = normalized.safe_forms
    safe_top_k = max(1, min(top_k, 12))
    sub_plan = _sub_plan(
        base=deps.base_plan,
        tickers=safe_tickers,
        forms=safe_forms,
        filing_date_start=_parse_iso_date(filing_date_start),
        filing_date_end=_parse_iso_date(filing_date_end),
    )
    # Unknown filter values are silently dropped (and surfaced in the trace via
    # dropped_tickers / dropped_forms on call_entry below). Earlier this branch raised
    # ModelRetry when every proposed value was out-of-corpus, but that burned the
    # per-tool retry budget (pydantic-ai tracks retries per tool, with default 1; we
    # set 2) on stochastic ticker hallucinations and tripped "exceeded max retries"
    # before the agent could converge. Returning [] is a meaningful signal the agent
    # can recover from by retrying without filters.
    semantic_query: str | None = None
    hyde_meta: dict[str, object] = {"agent_used": False}
    if use_hyde:
        passage, hyde_meta, hyde_usage = generate_hyde_passage(query, deps.settings, dataset_config=deps.dataset_config)
        if passage and passage != query:
            semantic_query = passage
        deps.hyde_usage_records.append(hyde_usage)

    call_entry: dict[str, object] = {
        "tool": "retrieve_evidence",
        "query": query,
        "semantic_query_preview": (semantic_query[:200] if semantic_query else None),
        "tickers": safe_tickers,
        "form_types": safe_forms,
        "dropped_tickers": normalized.dropped_tickers,
        "dropped_forms": normalized.dropped_forms,
        "filing_date_start": filing_date_start,
        "filing_date_end": filing_date_end,
        "top_k": safe_top_k,
        "use_hyde": use_hyde,
        "hyde_meta": hyde_meta,
    }

    try:
        retrieved, retrieval_trace, embedding_usage, rerank_usage = hybrid_retrieve(
            deps.session,
            dataset_id=deps.dataset_id,
            question=query,
            semantic_query=semantic_query,
            filters=deps.base_filters,
            plan=sub_plan,
            top_k=safe_top_k,
            settings=deps.settings,
        )
    except Exception as exc:  # noqa: BLE001 - pgvector/SQLAlchemy/provider stack raises a wide variety
        # Surface the failure to the model via ModelRetry so it can retry with different
        # filters / wording. Empty-but-successful results stay as `[]` below (a legitimate
        # "nothing matched" signal that the agent should distinguish from "tool failed").
        # Log at ERROR with error_class so operators can stratify "transient DB blip"
        # from "config regression" in the trace dashboard.
        logger.error(
            "retrieval_tool_call_failed",
            extra={"error_class": type(exc).__name__, "error": str(exc)},
        )
        call_entry["error"] = f"{type(exc).__name__}: {exc}"
        call_entry["error_class"] = type(exc).__name__
        call_entry["returned"] = 0
        deps.tool_calls.append(call_entry)
        raise ModelRetry(
            f"retrieve_evidence failed for filters tickers={safe_tickers} forms={safe_forms} "
            f"({type(exc).__name__}: {exc}). Try different filters or rephrased query."
        ) from exc

    deps.embedding_usage_records.append(embedding_usage)
    deps.rerank_usage_records.append(rerank_usage)
    for item in retrieved:
        deps.chunk_lookup[item.chunk.id] = item

    call_entry["retrieval_trace"] = retrieval_trace
    call_entry["returned"] = len(retrieved)
    call_entry["returned_chunk_ids"] = [item.chunk.id for item in retrieved]
    call_entry["returned_tickers"] = sorted({item.document.ticker for item in retrieved})
    call_entry["returned_forms"] = sorted({item.document.form_type for item in retrieved})
    # ``candidates`` is the field the trace UI reads to render the per-call result list.
    # Keep snippets short — the trace JSON balloons fast otherwise, and the UI truncates
    # to ~90 chars on display anyway.
    call_entry["candidates"] = [
        {
            "rank": rank,
            "chunk_id": item.chunk.id,
            "ticker": item.document.ticker,
            "form_type": item.document.form_type,
            "filing_date": item.document.filing_date.isoformat() if item.document.filing_date else None,
            "page_start": item.chunk.page_start,
            "score": float(item.score),
            "rerank_score": float(item.rerank_score) if item.rerank_score is not None else None,
            "snippet": _short_snippet(item.chunk.text),
        }
        for rank, item in enumerate(retrieved, start=1)
    ]
    deps.tool_calls.append(call_entry)

    return [
        ToolRetrievalHit(
            chunk_id=item.chunk.id,
            ticker=item.document.ticker,
            form_type=item.document.form_type,
            filing_date=item.document.filing_date.isoformat() if item.document.filing_date else None,
            page=item.chunk.page_start,
            contains_table=item.chunk.contains_table,
            score=float(item.rerank_score) if item.rerank_score is not None else float(item.score),
            snippet=_short_snippet(item.chunk.text),
        )
        for item in retrieved
    ]


def build_retrieval_agent(
    settings: Settings,
) -> Agent[RetrievalAgentDeps, RetrievalAgentOutput]:
    """Construct the tool-using retrieval agent.

    Each call builds a fresh ``Agent`` - the underlying chat model and chat provider
    are cached upstream, so this is cheap. We do not ``lru_cache`` the agent itself
    because the tool closure binds to a fresh ``deps`` for every run.
    """
    # ``tool_retries`` is per-tool (pydantic-ai tracks the counter on each function
    # tool independently, not globally) and ``output_retries`` is per-run. Bumping
    # both to 2 (default is 1) gives the chunk-id validator and the hybrid_retrieve
    # error path one near-miss correction each before the run dies — glm-4.7 sometimes
    # fabricates a chunk_id on the first emit and self-corrects on the next. The
    # global ``tool_calls_limit=retrieval_agent_tool_call_budget`` (4 by default)
    # passed via UsageLimits is still the backstop on runaway loops.
    # Retrieval is structured tool-calling work — temperature=0 unconditionally, not
    # gated on ``eval_temperature_zero``. Other agents (HyDE, generator) still consult
    # ``deterministic_model_settings`` because their stochasticity can be useful during
    # debug runs, but here non-determinism manifests as malformed tool args (e.g. glm-4.7
    # emitting ``tickers='["AAPL"]'`` as a JSON-string instead of an array) that burn the
    # retry budget without anything productive to retry against.
    base_settings = deterministic_model_settings(settings) or ModelSettings()
    base_settings["temperature"] = 0
    agent: Agent[RetrievalAgentDeps, RetrievalAgentOutput] = Agent(
        model=build_chat_model(settings),
        deps_type=RetrievalAgentDeps,
        output_type=RetrievalAgentOutput,
        instructions=_RETRIEVAL_AGENT_INSTRUCTIONS,
        name="rag-retrieval-agent",
        model_settings=base_settings,
        output_retries=2,
        tool_retries=2,
        capabilities=[LogToolCalls()],
    )

    @agent.instructions
    def retrieval_context(ctx: RunContext[RetrievalAgentDeps]) -> str:
        config = ctx.deps.dataset_config
        listed = ", ".join(sorted(ctx.deps.known_tickers)) if ctx.deps.known_tickers else "(none)"
        forms = ", ".join(config.valid_forms) if config.valid_forms else "(any)"
        today = datetime.now(UTC).date()
        return (
            f"TODAY: {today.isoformat()}\nCORPUS: {config.domain_label}\nKNOWN_FORMS: {forms}\nKNOWN_TICKERS: {listed}"
        )

    @agent.output_validator
    def validate_selected_ids(
        ctx: RunContext[RetrievalAgentDeps],
        output: RetrievalAgentOutput,
    ) -> RetrievalAgentOutput:
        # Fabricated chunk_ids are the single most common failure mode for a tool-using
        # retrieval agent. Surface this back to the model via ModelRetry so it re-emits
        # using only ids it actually received from `retrieve_evidence`.
        seen_ids = ctx.deps.chunk_lookup.keys()
        invalid = [chunk_id for chunk_id in output.selected_chunk_ids if chunk_id not in seen_ids]
        if invalid:
            raise ModelRetry(
                f"selected_chunk_ids contains ids that were never returned by a tool call: "
                f"{invalid}. Use only chunk_ids from retrieve_evidence results, verbatim."
            )
        return output

    @agent.tool
    def retrieve_evidence(
        ctx: RunContext[RetrievalAgentDeps],
        query: str,
        tickers: _StrListArg = None,
        form_types: _StrListArg = None,
        filing_date_start: str | None = None,
        filing_date_end: str | None = None,
        top_k: int = 6,
        use_hyde: bool = True,  # noqa: FBT001,FBT002 - agent tool param; LLM passes all args by keyword via JSON tool input
    ) -> list[ToolRetrievalHit]:
        """Retrieve evidence chunks via hybrid search + optional HyDE + rerank.

        Args:
            query: The information to search for. A question, phrase, topic, or even a
                domain term. FTS uses this verbatim; HyDE (when enabled) uses an
                LLM-generated hypothetical passage for the vector probe.
            tickers: Restrict to these tickers (see KNOWN_TICKERS in the system
                context). Unknown tickers are silently dropped. Leave None for no
                ticker filter.
            form_types: Restrict to a subset of the dataset's known forms (see
                KNOWN_FORMS in the system context). Unknown forms are silently dropped.
                Leave None for no form filter.
            filing_date_start: ISO date (YYYY-MM-DD) lower bound on filing_date.
            filing_date_end: ISO date (YYYY-MM-DD) upper bound on filing_date.
            top_k: Maximum chunks to return (clamped to 1-12). Default 6.
            use_hyde: When True, generate a hypothetical passage in the corpus's
                disclosure register for the vector probe. Default True. Set False for
                exact-phrase or exact-number lookups where the question itself is
                likely to appear verbatim in the corpus.

        Returns:
            A list of ToolRetrievalHit. Empty list if nothing matched or the call failed
            (a failed call is recorded in the trace; you can retry with different
            filters or wording).

        If you are not sure which ticker or form applies, leave both as None — a broad
        search is preferable to a filter that throws away all results.
        """
        return perform_retrieve_evidence(
            ctx.deps,
            query,
            tickers=tickers,
            form_types=form_types,
            filing_date_start=filing_date_start,
            filing_date_end=filing_date_end,
            top_k=top_k,
            use_hyde=use_hyde,
        )

    return agent


# ---------------------------------------------------------------------------
# Heuristic fallback
# ---------------------------------------------------------------------------


def _heuristic_retrieval(
    session: "Session",
    *,
    dataset_id: str,
    question: str,
    filters: QueryFilters,
    known_tickers: set[str],
    settings: Settings,
    dataset_config: DatasetConfig | None = None,
) -> AgentRetrievalResult:
    """Deterministic fallback used when the chat agent is unavailable or fails.

    One pass of: heuristic plan -> hybrid_retrieve -> keyword verifier. Wraps the result
    in the same ``AgentRetrievalResult`` shape so downstream code does not need to know
    which path produced the chunks.
    """
    config = dataset_config or DatasetConfig.default_sec(
        known_tickers=frozenset(ticker.upper() for ticker in known_tickers)
    )
    plan = infer_query_plan(
        question=question,
        filters=filters,
        dataset_config=config,
    )
    try:
        retrieved, retrieval_trace, embedding_usage, rerank_usage = hybrid_retrieve(
            session,
            dataset_id=dataset_id,
            question=question,
            filters=filters,
            plan=plan,
            top_k=settings.evidence_top_k,
            settings=settings,
        )
    except Exception as exc:  # noqa: BLE001 - heuristic is the last-resort path; surface all failures structurally
        # Log at ERROR with error_class so dashboards can stratify hard failures (DB
        # unreachable, programmer regressions) from "the corpus has nothing relevant".
        logger.error(
            "heuristic_retrieval_failed",
            extra={"error_class": type(exc).__name__, "error": str(exc)},
        )
        return AgentRetrievalResult(
            chunks=[],
            tool_calls=[
                {
                    "tool": "heuristic-hybrid_retrieve",
                    "query": question,
                    "error": f"{type(exc).__name__}: {exc}",
                    "error_class": type(exc).__name__,
                    "returned": 0,
                }
            ],
            output=RetrievalAgentOutput(
                selected_chunk_ids=[],
                target_tickers=plan.target_tickers,
                forms=plan.forms,
                metrics=plan.metrics,
                query_type=plan.query_type,
                latest=plan.latest,
                subquestions=plan.subquestions,
                insufficient_evidence=True,
                insufficiency_reason="Heuristic hybrid_retrieve failed before any evidence was returned.",
                reasoning="agent_unavailable; heuristic path errored",
            ),
            hyde_usage=TokenUsage(),
            embedding_usage=TokenUsage(),
            rerank_usage=TokenUsage(),
        )
    verification = keyword_verify_evidence(question, retrieved)
    selected_ids = list(verification.supported_chunk_ids)
    if not selected_ids:
        selected_ids = [item.chunk.id for item in retrieved]
    return AgentRetrievalResult(
        chunks=retrieved,
        tool_calls=[
            {
                "tool": "heuristic-hybrid_retrieve",
                "query": question,
                "tickers": plan.target_tickers,
                "form_types": plan.forms,
                "top_k": settings.evidence_top_k,
                "use_hyde": False,
                "retrieval_trace": retrieval_trace,
                "returned": len(retrieved),
                "verifier": "keyword",
                "verifier_confidence": verification.confidence,
                "candidates": [
                    {
                        "rank": rank,
                        "chunk_id": item.chunk.id,
                        "ticker": item.document.ticker,
                        "form_type": item.document.form_type,
                        "filing_date": item.document.filing_date.isoformat() if item.document.filing_date else None,
                        "page_start": item.chunk.page_start,
                        "score": float(item.score),
                        "rerank_score": float(item.rerank_score) if item.rerank_score is not None else None,
                        "snippet": _short_snippet(item.chunk.text),
                    }
                    for rank, item in enumerate(retrieved, start=1)
                ],
            }
        ],
        output=RetrievalAgentOutput(
            selected_chunk_ids=selected_ids,
            missing_subclaims=verification.missing_subclaims,
            contradictions=verification.contradictions,
            target_tickers=plan.target_tickers,
            forms=plan.forms,
            metrics=plan.metrics,
            query_type=plan.query_type,
            latest=plan.latest,
            subquestions=plan.subquestions,
            confidence=verification.confidence,
            insufficient_evidence=not selected_ids,
            insufficiency_reason=("Heuristic retrieval returned no supported evidence." if not selected_ids else None),
            reasoning="agent_unavailable; heuristic plan + single hybrid_retrieve",
        ),
        hyde_usage=TokenUsage(),
        embedding_usage=embedding_usage,
        rerank_usage=rerank_usage,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _build_agent_prompt(question: str) -> str:
    """User message body for the retrieval agent.

    TODAY and KNOWN_TICKERS now live in ``@agent.instructions`` (pulled from
    ``RetrievalAgentDeps``), so the user message carries only the question.
    """
    return f"QUESTION:\n{question}"


def run_retrieval_agent(
    session: "Session",
    *,
    dataset_id: str,
    question: str,
    filters: QueryFilters,
    known_tickers: set[str],
    settings: Settings | None = None,
    dataset_config: DatasetConfig | None = None,
) -> tuple[AgentRetrievalResult, dict[str, object], TokenUsage]:
    """Run the tool-using retrieval agent.

    Returns ``(result, metadata, agent_chat_usage)``. ``result.usage`` already covers
    HyDE + embedding + rerank usage incurred inside tool calls. ``agent_chat_usage`` is
    the chat tokens consumed by the agent itself (planning turns + tool synthesis +
    final emit) and is returned separately so the orchestrator can route it into
    ``RoleUsage.planner``. Both are empty when the heuristic fallback is used.
    """
    resolved = settings or get_settings()
    config = dataset_config or DatasetConfig.default_sec(
        known_tickers=frozenset(ticker.upper() for ticker in known_tickers)
    )
    metadata: dict[str, object] = {
        "agent_used": False,
        "model": resolved.zai_chat_model,
        "error": None,
    }

    if not agent_available(resolved):
        metadata["fallback_reason"] = "agent_unavailable"
        return (
            _heuristic_retrieval(
                session,
                dataset_id=dataset_id,
                question=question,
                filters=filters,
                known_tickers=known_tickers,
                settings=resolved,
                dataset_config=config,
            ),
            metadata,
            TokenUsage(),
        )

    base_plan = infer_query_plan(
        question=question,
        filters=filters,
        dataset_config=config,
    )
    deps = RetrievalAgentDeps(
        session=session,
        dataset_id=dataset_id,
        settings=resolved,
        user_question=question,
        base_filters=filters,
        base_plan=base_plan,
        known_tickers=frozenset(ticker.upper() for ticker in known_tickers),
        dataset_config=config,
    )

    try:
        agent = build_retrieval_agent(resolved)
        budget = resolved.retrieval_agent_tool_call_budget
        # `request_limit` counts every model request, including retry rounds (each
        # `ModelRetry` causes another chat completion). Worst-case budget: one request
        # per tool call plus up to `tool_retries=2` retries each, then a final emit
        # plus up to `output_retries=2` validator retries. `budget * 3 + 3` covers
        # that envelope without giving runaway loops infinite headroom — the agent
        # comment block above keeps `tool_calls_limit=budget` as the primary cap on
        # actual tool invocations.
        usage_limits=UsageLimits(tool_calls_limit=budget, request_limit=budget * 3 + 3)
        result = agent.run_sync(
            _build_agent_prompt(question),
            deps=deps,
            usage_limits=usage_limits,
        )
    except AGENT_RETRYABLE_ERRORS as exc:
        message = f"{type(exc).__name__}: {exc}"
        logger.warning("retrieval_agent_failed", extra={"error": message})
        metadata["fallback_reason"] = "agent_error"
        metadata["error"] = message
        # Surface what the agent managed to do before dying so dashboards can stratify
        # "agent never got off the ground" (0 calls) from "agent burned its retry budget
        # on ModelRetries" (tool_retry_count high, tool_call_count low).
        metadata["tool_call_count"] = len(deps.tool_calls)
        metadata["tool_retry_count"] = sum(1 for call in deps.tool_calls if call.get("error_class"))
        return (
            _heuristic_retrieval(
                session,
                dataset_id=dataset_id,
                question=question,
                filters=filters,
                known_tickers=known_tickers,
                settings=resolved,
                dataset_config=config,
            ),
            metadata,
            TokenUsage(),
        )

    output = result.output
    # Normalize a couple of fields the LLM might mis-fill; the Pydantic schema already
    # constrains types and range, so we only sanity-check the closed-set strings.
    valid_form_set = {form.upper() for form in config.valid_forms}
    normalized_output = output.model_copy(
        update={
            "query_type": _validate_query_type(output.query_type),
            "target_tickers": sorted({t.upper() for t in output.target_tickers} & deps.known_tickers),
            "forms": sorted({f.upper() for f in output.forms if f.upper() in valid_form_set}),
        }
    )

    chunks = _materialize_selected(normalized_output, deps.chunk_lookup, resolved.evidence_top_k)
    # _materialize_selected falls back to top-K when the LLM emits an empty
    # selected_chunk_ids (or otherwise misses the curation step). Reflect the actual
    # materialized chunks back onto ``selected_chunk_ids`` so the verifier section
    # of the trace shows the chunks that fed the answer instead of an empty list.
    # When the LLM did curate, this is a no-op — the materialized chunks match the
    # original selection in id order.
    materialized_ids = [c.chunk.id for c in chunks]
    if materialized_ids != list(normalized_output.selected_chunk_ids):
        normalized_output = normalized_output.model_copy(update={"selected_chunk_ids": materialized_ids})
    agent_chat_usage = safe_pydantic_ai_usage(
        result,
        provider=Provider.ZAI,
        model=resolved.zai_chat_model,
    )
    metadata["agent_used"] = True
    metadata["tool_call_count"] = len(deps.tool_calls)
    metadata["tool_retry_count"] = sum(1 for call in deps.tool_calls if call.get("error_class"))
    metadata["tool_call_budget"] = resolved.retrieval_agent_tool_call_budget

    return (
        AgentRetrievalResult(
            chunks=chunks,
            tool_calls=list(deps.tool_calls),
            output=normalized_output,
            hyde_usage=_sum_usages(deps.hyde_usage_records),
            embedding_usage=_sum_usages(deps.embedding_usage_records),
            rerank_usage=_sum_usages(deps.rerank_usage_records),
        ),
        metadata,
        agent_chat_usage,
    )


__all__ = [
    "AgentRetrievalResult",
    "RetrievalAgentDeps",
    "RetrievalAgentOutput",
    "ToolRetrievalHit",
    "build_retrieval_agent",
    "perform_retrieve_evidence",
    "run_retrieval_agent",
]
