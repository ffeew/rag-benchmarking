"""Dataset-aware prompt content checks.

These tests assert that the five agent prompts (planner, HyDE, verifier, generator,
retrieval agent) no longer hard-code SEC identity and that dynamic ``@agent.instructions``
inject the dataset's ``domain_label`` / ``valid_forms`` / ``hyde_style_hint`` so the same
agent can serve any registered dataset. The check inspects the static instructions
strings and the dynamic-instructions functions directly so it runs without an LLM
provider.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic_ai.models.test import TestModel
from rag_common.schemas import QueryFilters
from rag_retrieval.dataset_config import DatasetConfig


@pytest.fixture(autouse=True)
def _stub_build_chat_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the real OpenAI-compatible client builder with a pydantic-ai TestModel.

    The agent factories in agents.py call ``build_chat_model`` to materialize the LLM
    backend. The real builder needs a ZAI api key; these tests inspect prompt structure
    only and never call ``agent.run_sync``, so a ``TestModel`` is sufficient. The
    ``_build_*_agent_for`` lru_caches need to be invalidated each test so the patched
    builder is actually exercised.
    """
    from rag_retrieval import agents, generation, hyde, planning, verification

    test_model = TestModel()
    monkeypatch.setattr(agents, "build_chat_model", lambda _s=None: test_model)
    planning._build_planner_agent_for.cache_clear()
    hyde._build_hyde_agent_for.cache_clear()
    verification._build_verifier_agent_for.cache_clear()
    generation._build_generator_agent_for.cache_clear()


def test_static_planner_instructions_drop_sec_identity() -> None:
    from rag_retrieval.planning import _PLANNER_INSTRUCTIONS

    assert "SEC filings RAG system" not in _PLANNER_INSTRUCTIONS
    assert "SEC filings" not in _PLANNER_INSTRUCTIONS
    assert "filings RAG system" in _PLANNER_INSTRUCTIONS
    assert "KNOWN_FORMS" in _PLANNER_INSTRUCTIONS


def test_static_hyde_instructions_drop_sec_register_cues() -> None:
    from rag_retrieval.hyde import _HYDE_INSTRUCTIONS

    assert "SEC filing" not in _HYDE_INSTRUCTIONS
    assert "10-K" not in _HYDE_INSTRUCTIONS
    assert "management's discussion" not in _HYDE_INSTRUCTIONS.lower()
    assert "accounting terminology" not in _HYDE_INSTRUCTIONS.lower()
    assert "MD&A" not in _HYDE_INSTRUCTIONS
    assert "formal disclosure register" in _HYDE_INSTRUCTIONS


def test_static_verifier_instructions_drop_sec_identity() -> None:
    from rag_retrieval.verification import _VERIFIER_INSTRUCTIONS

    assert "SEC filings RAG system" not in _VERIFIER_INSTRUCTIONS
    assert "filings RAG system" in _VERIFIER_INSTRUCTIONS


def test_static_generator_instructions_drop_investor_framing() -> None:
    from rag_retrieval.generation import _GENERATOR_INSTRUCTIONS

    assert "SEC filings RAG system" not in _GENERATOR_INSTRUCTIONS
    assert "investor-style" not in _GENERATOR_INSTRUCTIONS
    assert "investment-recommendation" not in _GENERATOR_INSTRUCTIONS
    assert "live market data" not in _GENERATOR_INSTRUCTIONS
    assert "filings RAG system" in _GENERATOR_INSTRUCTIONS


def test_static_retrieval_agent_instructions_use_entity_language() -> None:
    from rag_retrieval.retrieval_tool import _RETRIEVAL_AGENT_INSTRUCTIONS

    assert "SEC filings RAG system" not in _RETRIEVAL_AGENT_INSTRUCTIONS
    assert "Single-company" not in _RETRIEVAL_AGENT_INSTRUCTIONS
    assert "Single-entity" in _RETRIEVAL_AGENT_INSTRUCTIONS
    assert "Comparisons across N entities" in _RETRIEVAL_AGENT_INSTRUCTIONS


def _custom_config() -> DatasetConfig:
    return DatasetConfig(
        id="d-custom",
        name="compliance-memos",
        description=None,
        domain_label="Internal compliance memos",
        entity_label="subject",
        valid_forms=("MEMO", "INCIDENT"),
        metric_terms=("incident", "escalation"),
        hyde_style_hint="Compliance memo register: incident, remediation, control mapping.",
        citation_label_template="[{entity} {filing_date} {form_type}, p. {page}]",
        known_tickers=frozenset({"TEAM_A"}),
    )


def _find_instructions_fn(agent: object, name: str) -> object:
    """Locate the ``@agent.instructions`` callable registered on a pydantic-ai Agent.

    Pydantic-AI stores instructions callables in ``Agent._instructions`` (a list of
    callables). The corresponding ``static`` instruction string is held separately
    so we can rely on identifier match-by-name to isolate ``planner_context``,
    ``hyde_context``, etc.
    """
    callables = list(getattr(agent, "_instructions", []) or [])
    for fn in callables:
        if callable(fn) and getattr(fn, "__name__", "") == name:
            return fn
    raise AssertionError(f"no @agent.instructions callable named {name!r} on {agent!r}")


def test_planner_dynamic_instructions_emit_domain_label_and_known_forms() -> None:
    """The planner's dynamic @agent.instructions function builds a corpus-aware block."""
    from rag_retrieval.planning import PlannerDeps, _build_planner_agent_for

    agent = _build_planner_agent_for("test-model")
    planner_context = _find_instructions_fn(agent, "planner_context")
    deps = PlannerDeps(
        today=date(2026, 5, 16),
        dataset_config=_custom_config(),
        user_filters=QueryFilters(),
    )
    ctx = cast("object", SimpleNamespace(deps=deps))
    rendered = planner_context(ctx)  # type: ignore[operator]

    assert "CORPUS: Internal compliance memos" in rendered
    assert "KNOWN_FORMS: MEMO, INCIDENT" in rendered
    assert "KNOWN_TICKERS: TEAM_A" in rendered
    assert "10-K" not in rendered  # SEC defaults must not leak in for a custom corpus.
    assert "TODAY: 2026-05-16" in rendered


def test_hyde_dynamic_instructions_include_style_hint_when_set() -> None:
    """When the dataset supplies a HyDE style hint, dynamic instructions surface it."""
    from rag_retrieval.hyde import HydeDeps, _build_hyde_agent_for

    agent = _build_hyde_agent_for("test-model")
    hyde_context = _find_instructions_fn(agent, "hyde_context")
    deps = HydeDeps(dataset_config=_custom_config())
    ctx = cast("object", SimpleNamespace(deps=deps))
    rendered = hyde_context(ctx)  # type: ignore[operator]

    assert "CORPUS: Internal compliance memos" in rendered
    assert "STYLE_HINT: Compliance memo register" in rendered


def test_hyde_dynamic_instructions_omit_style_hint_when_blank() -> None:
    from rag_retrieval.hyde import HydeDeps, _build_hyde_agent_for

    agent = _build_hyde_agent_for("test-model-2")
    hyde_context = _find_instructions_fn(agent, "hyde_context")
    deps = HydeDeps(dataset_config=DatasetConfig.default_sec())
    ctx = cast("object", SimpleNamespace(deps=deps))
    rendered = hyde_context(ctx)  # type: ignore[operator]

    assert "CORPUS:" in rendered
    assert "STYLE_HINT" not in rendered


def test_verifier_dynamic_instructions_emit_domain_label() -> None:
    from rag_retrieval.verification import _build_verifier_agent_for

    agent = _build_verifier_agent_for("test-model-v")
    verifier_context = _find_instructions_fn(agent, "verifier_context")
    deps = SimpleNamespace(
        valid_chunk_ids=frozenset(),
        dataset_config=_custom_config(),
    )
    ctx = cast("object", SimpleNamespace(deps=deps))
    rendered = verifier_context(ctx)  # type: ignore[operator]

    assert rendered == "CORPUS: Internal compliance memos"


def test_generator_dynamic_instructions_emit_domain_label() -> None:
    from rag_retrieval.generation import _build_generator_agent_for

    agent = _build_generator_agent_for("test-model-g")
    generator_context = _find_instructions_fn(agent, "generator_context")
    deps = SimpleNamespace(
        valid_tags=frozenset(),
        dataset_config=_custom_config(),
    )
    ctx = cast("object", SimpleNamespace(deps=deps))
    rendered = generator_context(ctx)  # type: ignore[operator]

    assert rendered == "CORPUS: Internal compliance memos"
