"""Locked retrieval-variant catalog for the v1 component-lesion ablation study.

The 9 variants below isolate each component of the retrieval pipeline. Names are
the join key for paired statistical analysis (see ``ablation_analysis.py``); the
underlying ``retrieval_mode`` picks the pipeline branch and ``overrides`` knock
individual components on/off without code changes.

Pre-registration: ``docs/eval/ablation_v1_plan.md``.
"""

from rag_common.config import Settings
from rag_common.enums import RetrievalMode
from rag_common.schemas import RetrievalOverrides, RetrievalVariantSpec

LOCKED_ABLATION_VARIANTS: list[RetrievalVariantSpec] = [
    RetrievalVariantSpec(name="full_agentic", retrieval_mode=RetrievalMode.FULL_AGENTIC),
    RetrievalVariantSpec(
        name="full_agentic_no_hyde",
        retrieval_mode=RetrievalMode.FULL_AGENTIC,
        overrides=RetrievalOverrides(hyde_enabled=False),
    ),
    RetrievalVariantSpec(
        name="full_agentic_no_reranker",
        retrieval_mode=RetrievalMode.FULL_AGENTIC,
        overrides=RetrievalOverrides(reranker_enabled=False),
    ),
    RetrievalVariantSpec(
        name="full_agentic_no_hyde_no_reranker",
        retrieval_mode=RetrievalMode.FULL_AGENTIC,
        overrides=RetrievalOverrides(hyde_enabled=False, reranker_enabled=False),
    ),
    RetrievalVariantSpec(name="single_pass", retrieval_mode=RetrievalMode.SINGLE_PASS),
    RetrievalVariantSpec(
        name="single_pass_semantic_only",
        retrieval_mode=RetrievalMode.SINGLE_PASS,
        overrides=RetrievalOverrides(full_text_candidates=0),
    ),
    RetrievalVariantSpec(
        name="single_pass_lexical_only",
        retrieval_mode=RetrievalMode.SINGLE_PASS,
        overrides=RetrievalOverrides(semantic_candidates=0),
    ),
    RetrievalVariantSpec(
        name="single_pass_no_reranker",
        retrieval_mode=RetrievalMode.SINGLE_PASS,
        overrides=RetrievalOverrides(reranker_enabled=False),
    ),
    RetrievalVariantSpec(
        name="single_pass_no_decomposition",
        retrieval_mode=RetrievalMode.SINGLE_PASS,
        overrides=RetrievalOverrides(query_decomposition_enabled=False),
    ),
    RetrievalVariantSpec(name="llm_only", retrieval_mode=RetrievalMode.LLM_ONLY),
]


ABLATION_PRESETS: dict[str, list[RetrievalVariantSpec]] = {
    "locked9": LOCKED_ABLATION_VARIANTS,
}


def apply_overrides(base: Settings, overrides: RetrievalOverrides) -> Settings:
    """Return a Settings clone with the supplied overrides applied.

    Returns the input unchanged when no fields are set, so callers can safely
    call this on every variant without paying the copy cost on the baseline.
    """

    diff = overrides.model_dump(exclude_none=True)
    if not diff:
        return base
    return base.model_copy(update=diff)
