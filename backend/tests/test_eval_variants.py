"""Schema-level tests for the per-variant retrieval-config overrides."""

import pytest
from pydantic import SecretStr, ValidationError
from rag_common.config import Settings
from rag_common.eval_variants import (
    ABLATION_PRESETS,
    LOCKED_ABLATION_VARIANTS,
    apply_overrides,
)
from rag_common.schemas import (
    EvaluationCreate,
    RetrievalOverrides,
    RetrievalVariantSpec,
)


def test_overrides_apply_clones_settings() -> None:
    base = Settings(api_bearer_token=SecretStr("test-token"), allow_mock_providers=True, hyde_enabled=True)
    overrides = RetrievalOverrides(hyde_enabled=False, semantic_candidates=0)
    cloned = apply_overrides(base, overrides)
    assert cloned is not base
    assert cloned.hyde_enabled is False
    assert cloned.semantic_candidates == 0
    # Original Settings is untouched.
    assert base.hyde_enabled is True
    assert base.semantic_candidates == 50


def test_empty_overrides_returns_input_unchanged() -> None:
    base = Settings(api_bearer_token=SecretStr("test-token"), allow_mock_providers=True)
    assert apply_overrides(base, RetrievalOverrides()) is base


def test_relaxed_settings_constraints_accept_zero_candidates() -> None:
    Settings(api_bearer_token=SecretStr("test-token"), allow_mock_providers=True, semantic_candidates=0)
    Settings(api_bearer_token=SecretStr("test-token"), allow_mock_providers=True, full_text_candidates=0)


def test_overrides_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        RetrievalOverrides(hyde_enabled=False, made_up=True)  # type: ignore[call-arg]


def test_variant_name_pattern_rejects_uppercase() -> None:
    with pytest.raises(ValidationError):
        RetrievalVariantSpec(name="FullAgentic", retrieval_mode="full_agentic")


def test_locked_9_catalog_shape() -> None:
    names = [spec.name for spec in LOCKED_ABLATION_VARIANTS]
    assert names == [
        "full_agentic",
        "full_agentic_no_hyde",
        "full_agentic_no_reranker",
        "full_agentic_no_hyde_no_reranker",
        "single_pass",
        "single_pass_semantic_only",
        "single_pass_lexical_only",
        "single_pass_no_reranker",
        "llm_only",
    ]
    # Spot-check the override semantics that drive the lesion study.
    by_name = {spec.name: spec for spec in LOCKED_ABLATION_VARIANTS}
    assert by_name["full_agentic_no_hyde"].overrides.hyde_enabled is False
    assert by_name["full_agentic_no_reranker"].overrides.reranker_enabled is False
    assert by_name["single_pass_semantic_only"].overrides.full_text_candidates == 0
    assert by_name["single_pass_lexical_only"].overrides.semantic_candidates == 0
    assert by_name["llm_only"].retrieval_mode == "llm_only"


def test_ablation_presets_exposes_locked9() -> None:
    assert "locked9" in ABLATION_PRESETS
    assert len(ABLATION_PRESETS["locked9"]) == 9


def test_evaluation_create_back_compat_with_system_variants() -> None:
    payload = EvaluationCreate(dataset_id="x", system_variants=["full_agentic"])
    assert payload.variants is not None
    assert [v.name for v in payload.variants] == ["full_agentic"]
    assert payload.variants[0].retrieval_mode == "full_agentic"


def test_evaluation_create_rejects_both_fields_set() -> None:
    with pytest.raises(ValidationError):
        EvaluationCreate(
            dataset_id="x",
            system_variants=["full_agentic"],
            variants=[RetrievalVariantSpec(name="custom", retrieval_mode="full_agentic")],
        )


def test_evaluation_create_accepts_variants_with_default_system_variants() -> None:
    payload = EvaluationCreate(
        dataset_id="x",
        variants=[
            RetrievalVariantSpec(name="a", retrieval_mode="full_agentic"),
            RetrievalVariantSpec(name="b", retrieval_mode="single_pass"),
        ],
    )
    assert payload.variants is not None
    assert [v.name for v in payload.variants] == ["a", "b"]


def test_evaluation_create_rejects_duplicate_variant_names() -> None:
    with pytest.raises(ValidationError):
        EvaluationCreate(
            dataset_id="x",
            variants=[
                RetrievalVariantSpec(name="full_agentic", retrieval_mode="full_agentic"),
                RetrievalVariantSpec(name="full_agentic", retrieval_mode="single_pass"),
            ],
        )


def test_evaluation_create_default_materializes_three_variants() -> None:
    payload = EvaluationCreate(dataset_id="x")
    assert payload.variants is not None
    assert [v.name for v in payload.variants] == ["full_agentic", "single_pass", "llm_only"]
