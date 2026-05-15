"""Unit tests for the seed_eval_cases module — focuses on loading + validation.

End-to-end DB-persistence tests for seed_cases() depend on the route-test conftest
introduced in Phase 4.3 (test_eval_cases_api.py); they are exercised there.
"""

from pathlib import Path

import pytest
from rag_benchmarking.scripts.seed_eval_cases import (
    SeedEvalCase,
    SeedExpectedCitation,
    load_cases,
)


def test_seed_eval_case_validates_minimal_fields() -> None:
    case = SeedEvalCase(case_key="x", question="What?")
    assert case.case_key == "x"
    assert case.expected_citations == []
    assert case.tags == []


def test_seed_eval_case_rejects_empty_question() -> None:
    with pytest.raises(ValueError):
        SeedEvalCase(case_key="x", question="")


def test_seed_eval_case_rejects_empty_case_key() -> None:
    with pytest.raises(ValueError):
        SeedEvalCase(case_key="", question="What?")


def test_seed_eval_case_truncates_long_case_key() -> None:
    too_long = "a" * 65
    with pytest.raises(ValueError):
        SeedEvalCase(case_key=too_long, question="What?")


def test_seed_expected_citation_accepts_partial_data() -> None:
    citation = SeedExpectedCitation(ticker="AAPL", form_type="10-K")
    assert citation.page_number is None
    assert citation.document_id is None


def test_load_cases_parses_full_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "cases.yaml"
    yaml_path.write_text(
        """
- case_key: aapl_q1
  category: single_company_lookup
  difficulty: easy
  question: "What was Apple's revenue?"
  expected_answer: "$94B"
  expected_citations:
    - {ticker: AAPL, form_type: 10-K, page_number: 32}
  tags: [revenue]
- case_key: msft_q1
  category: single_company_lookup
  question: "What was Microsoft's revenue?"
  expected_citations: []
  tags: []
""",
        encoding="utf-8",
    )
    cases = load_cases(yaml_path)
    assert len(cases) == 2
    assert cases[0].case_key == "aapl_q1"
    assert cases[0].expected_citations[0].page_number == 32
    assert cases[1].expected_answer is None


def test_load_cases_rejects_non_list_root(tmp_path: Path) -> None:
    yaml_path = tmp_path / "bad.yaml"
    yaml_path.write_text("not_a_list: true\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_cases(yaml_path)


def test_load_cases_rejects_invalid_entry(tmp_path: Path) -> None:
    yaml_path = tmp_path / "bad.yaml"
    yaml_path.write_text("- case_key: ''\n  question: 'x'\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_cases(yaml_path)


def test_load_cases_loads_full_corpus_yaml() -> None:
    """Smoke test against the curated corpus YAML in the repo."""
    repo_root = Path(__file__).resolve().parent.parent
    corpus_file = repo_root / "eval_cases" / "sec_filings_v1.yaml"
    if not corpus_file.exists():
        pytest.skip("Curated corpus file not present")
    cases = load_cases(corpus_file)
    assert len(cases) == 68
    # Spot-check category distribution per ADR-0009
    by_category: dict[str, int] = {}
    for case in cases:
        key = case.category or "uncategorized"
        by_category[key] = by_category.get(key, 0) + 1
    assert by_category["single_company_lookup"] == 10
    assert by_category["table_lookup"] == 10
    assert by_category["trend"] == 8
    assert by_category["cross_company_comparison"] == 8
    assert by_category["sector_synthesis"] == 6
    assert by_category["multi_part"] == 6
    assert by_category["latest_filing"] == 6
    assert by_category["ambiguous"] == 6
    assert by_category["insufficient_evidence"] == 8
