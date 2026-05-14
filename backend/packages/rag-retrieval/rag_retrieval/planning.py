from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field
from rag_common.config import Settings, get_settings
from rag_common.db import models
from sqlalchemy import select

from rag_retrieval.agents import (
    agent_available,
    build_agent,
    run_with_fallback,
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
VALID_FORMS = ("10-K", "10-Q", "8-K")


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
    query_type: str = Field(
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


METRIC_TERMS = (
    "revenue",
    "debt",
    "cash",
    "gross margin",
    "research and development",
    "r&d",
    "segment",
    "risk",
    "ai",
    "artificial intelligence",
    "demand",
    "margin",
    "income",
    "expense",
)


_PLANNER_SYSTEM_PROMPT = """\
You are the query planner for an SEC filings RAG system.

Your job: turn a user question into a structured RetrievalPlan that downstream hybrid
retrieval can filter and search with. You DO NOT answer the question.

Rules:
- Only pick tickers from the provided KNOWN_TICKERS list. Never invent a ticker.
- forms must be a subset of [10-K, 10-Q, 8-K]. Leave empty if the user did not constrain.
- "Latest" / "most recent" / "current" filings should set latest=true. Latest is interpreted
  against the ingested dataset, NOT live SEC data.
- For multi-part or comparison questions, decompose into 2-5 concrete subquestions.
- query_type must be exactly one of:
  fact_lookup, table_lookup, comparison, trend, thematic_synthesis, latest_filing,
  insufficient_evidence.
- If the question is unanswerable from SEC filings, set query_type=insufficient_evidence
  and explain in `ambiguity`.
- Keep `reasoning` short - one or two sentences explaining why you picked this plan.
"""


@lru_cache(maxsize=2)
def _build_planner_agent_for(model_id: str) -> Agent[None, PlannerOutput]:  # noqa: ARG001
    return build_agent(
        output_type=PlannerOutput,
        system_prompt=_PLANNER_SYSTEM_PROMPT,
        name="sec-rag-planner",
    )


def _planner_agent(settings: Settings) -> Agent[None, PlannerOutput]:
    return _build_planner_agent_for(settings.openrouter_chat_model or "")


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
    known_tickers: set[str],
    filters: QueryFilters,
) -> RetrievalPlan:
    upper_known = {ticker.upper() for ticker in known_tickers}
    proposed_tickers = {ticker.upper() for ticker in output.target_tickers}
    safe_tickers = sorted(proposed_tickers & upper_known)
    if filters.ticker:
        safe_tickers = sorted({*safe_tickers, *[ticker.upper() for ticker in filters.ticker]})
    valid_forms = sorted(
        {form.upper() for form in output.forms if form.upper() in VALID_FORMS}
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
    known_tickers: set[str],
) -> RetrievalPlan:
    words = {word.upper().replace(".", "-") for word in re.findall(r"[A-Za-z][A-Za-z0-9.-]{0,8}", question)}
    inferred_tickers = sorted(words & known_tickers)
    forms: list[str] = []
    upper_question = question.upper()
    for form in VALID_FORMS:
        if form in upper_question:
            forms.append(form)
    if filters.form_type:
        forms = sorted({*forms, *[form.upper() for form in filters.form_type]})
    target_tickers = sorted({*(filters.ticker or []), *inferred_tickers})
    metrics = [term for term in METRIC_TERMS if term in question.lower()]
    lowered = question.lower()
    latest = any(term in lowered for term in ("latest", "last reported", "most recent", "current"))
    query_type = (
        "table_lookup" if any(term in lowered for term in ("break down", "table", "segment")) else "fact_lookup"
    )
    if any(term in lowered for term in ("compare", "between", "versus", "vs.")):
        query_type = "comparison"
    if any(term in lowered for term in ("trend", "over the past", "three-year", "3 year")):
        query_type = "trend"
    if any(term in lowered for term in ("summarize", "overview", "discussing")):
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


def _build_planner_prompt(
    *,
    question: str,
    known_tickers: set[str],
    filters: QueryFilters,
    today: date,
) -> str:
    known_list = ", ".join(sorted(known_tickers)) if known_tickers else "(none)"
    filter_lines = []
    if filters.ticker:
        filter_lines.append(f"user_filter_ticker: {', '.join(filters.ticker)}")
    if filters.form_type:
        filter_lines.append(f"user_filter_form_type: {', '.join(filters.form_type)}")
    if filters.filing_date_start or filters.filing_date_end:
        filter_lines.append(
            f"user_filter_filing_date: {filters.filing_date_start or '...'} to {filters.filing_date_end or '...'}"
        )
    user_filters = "\n".join(filter_lines) if filter_lines else "(none supplied)"
    return (
        f"TODAY: {today.isoformat()}\n"
        f"KNOWN_TICKERS: {known_list}\n"
        f"USER_FILTERS:\n{user_filters}\n\n"
        f"QUESTION:\n{question}"
    )


def plan_query(
    session: Session,
    *,
    dataset_id: str,
    question: str,
    filters: QueryFilters,
    settings: Settings | None = None,
) -> tuple[RetrievalPlan, dict[str, object]]:
    resolved = settings or get_settings()
    known_tickers = {
        ticker
        for ticker in session.scalars(
            select(models.Document.ticker).where(models.Document.dataset_id == dataset_id).distinct()
        )
        if ticker is not None
    }
    today = datetime.now(UTC).date()
    metadata: dict[str, object] = {"agent_used": False, "model": None, "error": None}

    if not agent_available(resolved):
        plan = infer_query_plan(question=question, filters=filters, known_tickers=known_tickers)
        metadata["model"] = resolved.openrouter_chat_model
        metadata["fallback_reason"] = "agent_unavailable"
        return plan, metadata

    def run_agent() -> RetrievalPlan:
        agent = _planner_agent(resolved)
        prompt = _build_planner_prompt(
            question=question,
            known_tickers=known_tickers,
            filters=filters,
            today=today,
        )
        result = agent.run_sync(prompt)
        return _normalize_planner_output(result.output, known_tickers, filters)

    def fallback() -> RetrievalPlan:
        return infer_query_plan(question=question, filters=filters, known_tickers=known_tickers)

    plan, used_agent, error = run_with_fallback(run_agent, fallback, label="planner")
    metadata["agent_used"] = used_agent
    metadata["model"] = resolved.openrouter_chat_model
    metadata["error"] = error
    return plan, metadata
