from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field
from pydantic_ai import ModelRetry, RunContext
from rag_common.config import Settings, get_settings
from rag_common.usage import TokenUsage, safe_pydantic_ai_usage

from rag_retrieval.agents import (
    agent_available,
    build_agent,
    run_with_fallback,
)
from rag_retrieval.dataset_config import (
    DEFAULT_METRIC_TERMS,
    DEFAULT_VALID_FORMS,
    DatasetConfig,
    load_dataset_config,
)

if TYPE_CHECKING:
    from pydantic_ai import Agent
    from rag_common.schemas import QueryFilters
    from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)


VALID_QUERY_TYPES = (
    "fact_lookup",
    "table_lookup",
    "comparison",
    "trend",
    "thematic_synthesis",
    "latest_filing",
    "insufficient_evidence",
)
QueryType = Literal[
    "fact_lookup",
    "table_lookup",
    "comparison",
    "trend",
    "thematic_synthesis",
    "latest_filing",
    "insufficient_evidence",
]
# Back-compat re-exports; downstream code should prefer ``DatasetConfig.valid_forms`` /
# ``metric_terms``. Kept here so existing imports do not break.
VALID_FORMS = DEFAULT_VALID_FORMS


@dataclass(frozen=True)
class RetrievalPlan:
    target_tickers: list[str] = field(default_factory=list)
    forms: list[str] = field(default_factory=list)
    filing_date_start: date | None = None
    filing_date_end: date | None = None
    metrics: list[str] = field(default_factory=list)
    subquestions: list[str] = field(default_factory=list)
    query_type: str = "fact_lookup"
    latest: bool = False
    ambiguity: str | None = None
    reasoning: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "target_tickers": self.target_tickers,
            "forms": self.forms,
            "filing_date_start": self.filing_date_start.isoformat() if self.filing_date_start else None,
            "filing_date_end": self.filing_date_end.isoformat() if self.filing_date_end else None,
            "metrics": self.metrics,
            "subquestions": self.subquestions,
            "query_type": self.query_type,
            "latest": self.latest,
            "ambiguity": self.ambiguity,
            "reasoning": self.reasoning,
        }


class PlannerOutput(BaseModel):
    target_tickers: list[str] = Field(
        default_factory=list,
        description="Exact upper-case ticker symbols pulled from the known list.",
    )
    forms: list[str] = Field(
        default_factory=list,
        description="Subset of ['10-K', '10-Q', '8-K']. Empty list means no restriction.",
    )
    filing_date_start: str | None = Field(
        default=None,
        description="ISO date (YYYY-MM-DD) lower bound for filing_date, or null.",
    )
    filing_date_end: str | None = Field(
        default=None,
        description="ISO date (YYYY-MM-DD) upper bound for filing_date, or null.",
    )
    metrics: list[str] = Field(
        default_factory=list,
        description="Specific financial metrics or topics being asked about.",
    )
    subquestions: list[str] = Field(
        default_factory=list,
        description="Decomposition into independently-answerable subquestions.",
    )
    query_type: QueryType = Field(
        default="fact_lookup",
        description=(
            "One of: fact_lookup, table_lookup, comparison, trend, "
            "thematic_synthesis, latest_filing, insufficient_evidence."
        ),
    )
    latest: bool = Field(
        default=False,
        description="True when the user wants the most recent filing in scope.",
    )
    ambiguity: str | None = Field(
        default=None,
        description="A short note describing ambiguity, or null if the question is clear.",
    )
    reasoning: str = Field(
        default="",
        description="Concise rationale for the chosen plan (one or two sentences).",
    )


# Back-compat alias; downstream callers should prefer ``DatasetConfig.metric_terms``.
METRIC_TERMS = DEFAULT_METRIC_TERMS


_PLANNER_INSTRUCTIONS = """\
You are the query planner for a filings RAG system.

Your job: turn a user question into a structured RetrievalPlan that downstream hybrid
retrieval can filter and search with. You DO NOT answer the question.

Rules:
- Only pick tickers from the provided KNOWN_TICKERS list. Never invent a ticker.
- forms must be a subset of the dataset's KNOWN_FORMS (provided below). Leave empty if
  the user did not constrain.
- "Latest" / "most recent" / "current" filings should set latest=true. Latest is interpreted
  against the ingested dataset, NOT live external data.
- For multi-part or comparison questions, decompose into 2-5 concrete subquestions.
- query_type must be exactly one of:
  fact_lookup, table_lookup, comparison, trend, thematic_synthesis, latest_filing,
  insufficient_evidence.
- If the question is unanswerable from the ingested corpus, set
  query_type=insufficient_evidence and explain in `ambiguity`.
- Keep `reasoning` short - one or two sentences explaining why you picked this plan.
"""


@dataclass(frozen=True)
class PlannerDeps:
    """Per-run context the planner agent consults via dynamic instructions.

    Carries the resolved dataset config (corpus identity, valid forms, metric hints,
    known tickers), the user's pre-supplied filters, and TODAY so the agent can resolve
    "latest" / "this year" against the ingested data rather than the model's training
    cutoff.
    """

    today: date
    dataset_config: DatasetConfig
    user_filters: QueryFilters

    @property
    def known_tickers(self) -> frozenset[str]:
        return self.dataset_config.known_tickers


@lru_cache(maxsize=2)
def _build_planner_agent_for(model_id: str) -> Agent[PlannerDeps, PlannerOutput]:  # noqa: ARG001
    agent: Agent[PlannerDeps, PlannerOutput] = build_agent(
        deps_type=PlannerDeps,
        output_type=PlannerOutput,
        instructions=_PLANNER_INSTRUCTIONS,
        name="rag-planner",
        output_retries=1,
    )

    @agent.instructions
    def planner_context(ctx: RunContext[PlannerDeps]) -> str:
        deps = ctx.deps
        config = deps.dataset_config
        known = ", ".join(sorted(deps.known_tickers)) if deps.known_tickers else "(none)"
        forms = ", ".join(config.valid_forms) if config.valid_forms else "(any)"
        metric_hint = ", ".join(config.metric_terms) if config.metric_terms else "(unspecified)"
        filter_lines: list[str] = []
        if deps.user_filters.ticker:
            filter_lines.append(f"user_filter_ticker: {', '.join(deps.user_filters.ticker)}")
        if deps.user_filters.form_type:
            filter_lines.append(f"user_filter_form_type: {', '.join(deps.user_filters.form_type)}")
        if deps.user_filters.filing_date_start or deps.user_filters.filing_date_end:
            filter_lines.append(
                "user_filter_filing_date: "
                f"{deps.user_filters.filing_date_start or '...'} to "
                f"{deps.user_filters.filing_date_end or '...'}"
            )
        filters = "\n".join(filter_lines) if filter_lines else "(none supplied)"
        return (
            f"TODAY: {deps.today.isoformat()}\n"
            f"CORPUS: {config.domain_label}\n"
            f"KNOWN_FORMS: {forms}\n"
            f"METRIC HINTS: {metric_hint}\n"
            f"KNOWN_TICKERS: {known}\n"
            f"USER_FILTERS:\n{filters}"
        )

    @agent.output_validator
    def validate_query_type(_ctx: RunContext[PlannerDeps], output: PlannerOutput) -> PlannerOutput:
        if output.query_type not in VALID_QUERY_TYPES:
            raise ModelRetry(
                f"query_type must be one of {list(VALID_QUERY_TYPES)}; got {output.query_type!r}."
            )
        return output

    return agent


def _planner_agent(settings: Settings) -> Agent[PlannerDeps, PlannerOutput]:
    return _build_planner_agent_for(settings.zai_chat_model or "")


def _coerce_date(value: str | None) -> date | None:
    if value is None or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()  # noqa: DTZ007
        except ValueError:
            return None


def _normalize_planner_output(
    output: PlannerOutput,
    dataset_config: DatasetConfig,
    filters: QueryFilters,
) -> RetrievalPlan:
    upper_known = {ticker.upper() for ticker in dataset_config.known_tickers}
    proposed_tickers = {ticker.upper() for ticker in output.target_tickers}
    safe_tickers = sorted(proposed_tickers & upper_known)
    if filters.ticker:
        safe_tickers = sorted({*safe_tickers, *[ticker.upper() for ticker in filters.ticker]})
    valid_form_set = {form.upper() for form in dataset_config.valid_forms}
    valid_forms = sorted(
        {form.upper() for form in output.forms if form.upper() in valid_form_set}
        | {form.upper() for form in (filters.form_type or [])}
    )
    query_type = output.query_type if output.query_type in VALID_QUERY_TYPES else "fact_lookup"
    return RetrievalPlan(
        target_tickers=safe_tickers,
        forms=valid_forms,
        filing_date_start=_coerce_date(output.filing_date_start) or filters.filing_date_start,
        filing_date_end=_coerce_date(output.filing_date_end) or filters.filing_date_end,
        metrics=[metric.strip() for metric in output.metrics if metric.strip()],
        subquestions=[item.strip() for item in output.subquestions if item.strip()],
        query_type=query_type,
        latest=bool(output.latest),
        ambiguity=output.ambiguity,
        reasoning=output.reasoning or None,
    )


def infer_query_plan(
    *,
    question: str,
    filters: QueryFilters,
    known_tickers: set[str] | frozenset[str] | None = None,
    dataset_config: DatasetConfig | None = None,
) -> RetrievalPlan:
    """Deterministic heuristic planner used by the fallback paths.

    Either ``known_tickers`` (back-compat) or ``dataset_config`` may be supplied. When
    both are provided, ``dataset_config`` wins; the ``known_tickers`` argument is
    treated as an override only when no config is given. Form types and metric terms
    are read from the config so non-SEC corpora are not biased to 10-K/10-Q/8-K.
    """
    config = dataset_config or DatasetConfig.default_sec(
        known_tickers=frozenset(known_tickers or ())
    )
    upper_known = {ticker.upper() for ticker in config.known_tickers}
    words = {word.upper().replace(".", "-") for word in re.findall(r"[A-Za-z][A-Za-z0-9.-]{0,8}", question)}
    inferred_tickers = sorted(words & upper_known)
    forms: list[str] = []
    upper_question = question.upper()
    for form in config.valid_forms:
        if form.upper() in upper_question:
            forms.append(form.upper())
    if filters.form_type:
        forms = sorted({*forms, *[form.upper() for form in filters.form_type]})
    target_tickers = sorted({*(filters.ticker or []), *inferred_tickers})
    lowered_question = question.lower()
    metrics = [term for term in config.metric_terms if term in lowered_question]
    latest = any(term in lowered_question for term in ("latest", "last reported", "most recent", "current"))
    query_type: QueryType = (
        "table_lookup"
        if any(term in lowered_question for term in ("break down", "table", "segment"))
        else "fact_lookup"
    )
    if any(term in lowered_question for term in ("compare", "between", "versus", "vs.")):
        query_type = "comparison"
    if any(term in lowered_question for term in ("trend", "over the past", "three-year", "3 year")):
        query_type = "trend"
    if any(term in lowered_question for term in ("summarize", "overview", "discussing")):
        query_type = "thematic_synthesis"
    ambiguity = None
    if not target_tickers and query_type in {"fact_lookup", "table_lookup", "trend"}:
        ambiguity = "No ticker was inferred; retrieval will search the whole dataset."
    return RetrievalPlan(
        target_tickers=[ticker.upper() for ticker in target_tickers],
        forms=forms,
        filing_date_start=filters.filing_date_start,
        filing_date_end=filters.filing_date_end,
        metrics=metrics,
        subquestions=[],
        query_type=query_type,
        latest=latest,
        ambiguity=ambiguity,
        reasoning=None,
    )


def _build_planner_prompt(question: str) -> str:
    """User message body for the planner.

    TODAY, KNOWN_TICKERS, and USER_FILTERS now live in ``@agent.instructions`` via
    ``PlannerDeps``, so the user message carries only the question itself - this lets
    the static instructions block stay cacheable by providers that support prompt
    caching (Anthropic, Bedrock).
    """
    return f"QUESTION:\n{question}"


def plan_query(
    session: Session,
    *,
    dataset_id: str,
    question: str,
    filters: QueryFilters,
    settings: Settings | None = None,
    force_heuristic: bool = False,
    dataset_config: DatasetConfig | None = None,
) -> tuple[RetrievalPlan, dict[str, object], TokenUsage]:
    resolved = settings or get_settings()
    config = dataset_config or load_dataset_config(session, dataset_id)
    today = datetime.now(UTC).date()
    metadata: dict[str, object] = {"agent_used": False, "model": None, "error": None}

    if force_heuristic:
        plan = infer_query_plan(question=question, filters=filters, dataset_config=config)
        metadata["model"] = resolved.zai_chat_model
        metadata["fallback_reason"] = "forced_heuristic"
        return plan, metadata, TokenUsage()

    if not agent_available(resolved):
        plan = infer_query_plan(question=question, filters=filters, dataset_config=config)
        metadata["model"] = resolved.zai_chat_model
        metadata["fallback_reason"] = "agent_unavailable"
        return plan, metadata, TokenUsage()

    deps = PlannerDeps(today=today, dataset_config=config, user_filters=filters)

    def run_agent() -> tuple[RetrievalPlan, TokenUsage]:
        agent = _planner_agent(resolved)
        result = agent.run_sync(_build_planner_prompt(question), deps=deps)
        usage = safe_pydantic_ai_usage(
            result,
            provider="zai",
            model=resolved.zai_chat_model,
        )
        return _normalize_planner_output(result.output, config, filters), usage

    def fallback() -> RetrievalPlan:
        return infer_query_plan(question=question, filters=filters, dataset_config=config)

    plan, used_agent, error, usage = run_with_fallback(run_agent, fallback, label="planner")
    metadata["agent_used"] = used_agent
    metadata["model"] = resolved.zai_chat_model
    metadata["error"] = error
    return plan, metadata, usage
