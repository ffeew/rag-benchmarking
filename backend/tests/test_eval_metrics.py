from rag_evaluation.metrics import (
    ChunkSnapshot,
    CitationSnapshot,
    ExpectedCitation,
    PlanFilters,
    RetrievedChunkRef,
    chunk_evidence_f1,
    citation_coverage,
    citation_validity,
    mean_reciprocal_rank,
    metadata_filter_correctness,
    page_evidence_f1,
    recall_at_k,
    strict_chunk_evidence_f1,
    strict_mean_reciprocal_rank,
    strict_page_evidence_f1,
    strict_recall_at_k,
)


def _chunk(
    rank: int,
    ticker: str = "AAPL",
    form: str = "10-K",
    page_start: int = 10,
    page_end: int = 11,
) -> RetrievedChunkRef:
    return RetrievedChunkRef(
        chunk_id=f"c{rank}",
        document_id=f"doc-{ticker}-{form}",
        ticker=ticker,
        form_type=form,
        page_start=page_start,
        page_end=page_end,
        rank=rank,
    )


# ---------- recall_at_k ----------


def test_recall_at_k_exact_match() -> None:
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=10)]
    retrieved = [_chunk(1)]
    assert recall_at_k(expected, retrieved, k=5) == 1.0


def test_recall_at_k_partial_match() -> None:
    expected = [
        ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=10),
        ExpectedCitation(ticker="MSFT", form_type="10-K", page_number=20),
    ]
    retrieved = [_chunk(1)]
    assert recall_at_k(expected, retrieved, k=5) == 0.5


def test_recall_at_k_no_expected_returns_zero() -> None:
    assert recall_at_k([], [_chunk(1)], k=5) == 0.0


def test_recall_at_k_zero_k() -> None:
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K")]
    assert recall_at_k(expected, [_chunk(1)], k=0) == 0.0


def test_recall_at_k_matches_by_document_id() -> None:
    expected = [ExpectedCitation(document_id="doc-AAPL-10-K", page_number=10)]
    retrieved = [_chunk(1)]
    assert recall_at_k(expected, retrieved, k=5) == 1.0


def test_recall_at_k_page_out_of_range_misses() -> None:
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=99)]
    retrieved = [_chunk(1)]  # pages 10-11
    assert recall_at_k(expected, retrieved, k=5) == 0.0


def test_strict_recall_requires_page_and_document_or_form() -> None:
    retrieved = [_chunk(1)]
    assert strict_recall_at_k([ExpectedCitation(ticker="AAPL", form_type="10-K")], retrieved, k=5) == 0.0
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=10)]
    assert strict_recall_at_k(expected, retrieved, k=5) == 1.0


# ---------- mean_reciprocal_rank ----------


def test_mrr_first_position() -> None:
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=10)]
    retrieved = [_chunk(1), _chunk(2, ticker="MSFT")]
    assert mean_reciprocal_rank(expected, retrieved) == 1.0


def test_mrr_second_position() -> None:
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=10)]
    retrieved = [_chunk(1, ticker="MSFT", form="10-K"), _chunk(2)]
    assert mean_reciprocal_rank(expected, retrieved) == 0.5


def test_mrr_no_match() -> None:
    expected = [ExpectedCitation(ticker="GOOGL", form_type="10-K", page_number=99)]
    retrieved = [_chunk(1), _chunk(2)]
    assert mean_reciprocal_rank(expected, retrieved) == 0.0


def test_mrr_empty_returns_zero() -> None:
    assert mean_reciprocal_rank([], [_chunk(1)]) == 0.0
    assert mean_reciprocal_rank([ExpectedCitation(ticker="X")], []) == 0.0


def test_strict_mrr_rejects_ticker_only_hint() -> None:
    assert strict_mean_reciprocal_rank([ExpectedCitation(ticker="AAPL")], [_chunk(1)]) == 0.0


# ---------- page_evidence_f1 ----------


def test_page_f1_full_overlap() -> None:
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=10)]
    retrieved = [_chunk(1, page_start=10, page_end=10)]
    assert page_evidence_f1(expected, retrieved) == 1.0


def test_page_f1_disjoint_returns_zero() -> None:
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=10)]
    retrieved = [_chunk(1, ticker="MSFT", form="10-K", page_start=20, page_end=20)]
    assert page_evidence_f1(expected, retrieved) == 0.0


def test_page_f1_partial_overlap() -> None:
    # expected pages 10, 11 against retrieved chunk covering pages 10-12.
    # page_units = [(chunk, 10), (chunk, 11), (chunk, 12)]; matched 2/3, covered 2/2.
    expected = [
        ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=10),
        ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=11),
    ]
    retrieved = [_chunk(1, page_start=10, page_end=12)]
    score = page_evidence_f1(expected, retrieved)
    # precision = 2/3, recall = 2/2, F1 = 2 * 2/3 * 1 / (2/3 + 1) = 0.8
    assert abs(score - 0.8) < 1e-9


def test_page_f1_both_empty_returns_one() -> None:
    assert page_evidence_f1([], []) == 1.0


def test_page_f1_one_empty_returns_zero() -> None:
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=10)]
    assert page_evidence_f1(expected, []) == 0.0
    assert page_evidence_f1([], [_chunk(1)]) == 0.0


def test_page_f1_ticker_only_expected_not_halved_by_dual_keying() -> None:
    # Regression: with the old _retrieved_page_set adding BOTH (document_id, page) and
    # (ticker, page), precision was artificially halved for ticker-only expected
    # citations. Now we count unique pages once, so a single retrieved page matching
    # a single expected page yields F1 == 1.0.
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=34)]
    retrieved = [_chunk(1, page_start=34, page_end=34)]
    assert page_evidence_f1(expected, retrieved) == 1.0


def test_page_f1_dedupes_overlapping_chunks() -> None:
    # Two chunks both covering page 10 should not double-count.
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=10)]
    retrieved = [_chunk(1, page_start=10, page_end=10), _chunk(2, page_start=10, page_end=10)]
    assert page_evidence_f1(expected, retrieved) == 1.0


def test_strict_page_f1_requires_page_and_doc_or_form() -> None:
    retrieved = [_chunk(1, page_start=10, page_end=10)]
    # ticker-only hint: rejected by strict matching
    assert strict_page_evidence_f1([ExpectedCitation(ticker="AAPL")], retrieved) == 0.0
    # page + ticker + form: accepted
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=10)]
    assert strict_page_evidence_f1(expected, retrieved) == 1.0


# ---------- chunk_evidence_f1 ----------


def test_chunk_f1_both_empty_returns_one() -> None:
    assert chunk_evidence_f1([], []) == 1.0


def test_chunk_f1_one_empty_returns_zero() -> None:
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=10)]
    assert chunk_evidence_f1(expected, []) == 0.0
    assert chunk_evidence_f1([], [_chunk(1)]) == 0.0


def test_chunk_f1_perfect_match() -> None:
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=10)]
    retrieved = [_chunk(1)]
    assert chunk_evidence_f1(expected, retrieved) == 1.0


def test_chunk_f1_penalises_irrelevant_chunks() -> None:
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=10)]
    retrieved = [_chunk(1), _chunk(2, ticker="MSFT")]  # one relevant, one not
    # precision 1/2 = 0.5, recall 1/1 = 1.0 -> F1 = 2*0.5*1.0/(0.5+1.0) ≈ 0.6667
    score = chunk_evidence_f1(expected, retrieved)
    assert score == 2 * 0.5 * 1.0 / (0.5 + 1.0)


def test_chunk_f1_penalises_missing_coverage() -> None:
    expected = [
        ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=10),
        ExpectedCitation(ticker="MSFT", form_type="10-K", page_number=20),
    ]
    retrieved = [_chunk(1)]  # covers AAPL only
    # precision 1/1 = 1.0, recall 1/2 = 0.5 -> F1 = 2*1.0*0.5/(1.0+0.5) ≈ 0.6667
    score = chunk_evidence_f1(expected, retrieved)
    assert score == 2 * 1.0 * 0.5 / (1.0 + 0.5)


def test_chunk_f1_no_overlap_returns_zero() -> None:
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=99)]
    retrieved = [_chunk(1)]  # pages 10-11, not 99
    assert chunk_evidence_f1(expected, retrieved) == 0.0


def test_strict_chunk_f1_skips_ticker_only_hint() -> None:
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K")]  # no page
    retrieved = [_chunk(1)]
    assert strict_chunk_evidence_f1(expected, retrieved) == 0.0


def test_strict_chunk_f1_full_match_when_page_present() -> None:
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K", page_number=10)]
    retrieved = [_chunk(1)]
    assert strict_chunk_evidence_f1(expected, retrieved) == 1.0


# ---------- metadata_filter_correctness ----------


def test_metadata_filter_correctness_no_filters_passes() -> None:
    filters = PlanFilters()
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K")]
    assert metadata_filter_correctness(filters, expected) == 1.0


def test_metadata_filter_correctness_ticker_match_passes() -> None:
    filters = PlanFilters(target_tickers=["AAPL"])
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K")]
    assert metadata_filter_correctness(filters, expected) == 1.0


def test_metadata_filter_correctness_ticker_mismatch_fails() -> None:
    filters = PlanFilters(target_tickers=["MSFT"])
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K")]
    assert metadata_filter_correctness(filters, expected) == 0.0


def test_metadata_filter_correctness_form_mismatch_fails() -> None:
    filters = PlanFilters(forms=["10-Q"])
    expected = [ExpectedCitation(ticker="AAPL", form_type="10-K")]
    assert metadata_filter_correctness(filters, expected) == 0.0


def test_metadata_filter_correctness_no_expected_returns_one() -> None:
    assert metadata_filter_correctness(PlanFilters(target_tickers=["AAPL"]), []) == 1.0


def test_plan_filters_from_dict_handles_missing_fields() -> None:
    plan: dict[str, object] = {}
    assert PlanFilters.from_plan_dict(plan).target_tickers == []
    assert PlanFilters.from_plan_dict(plan).forms == []


# ---------- citation_validity ----------


def test_citation_validity_all_grounded() -> None:
    chunk = ChunkSnapshot(
        chunk_id="c1",
        document_id="doc",
        text="The total revenue was $94 billion.",
        page_start=10,
        page_end=11,
    )
    citations = [
        CitationSnapshot(chunk_id="c1", document_id="doc", page_number=10, evidence_text="total revenue was $94")
    ]
    assert citation_validity(citations, {"c1": chunk}) == 1.0


def test_citation_validity_missing_chunk_id() -> None:
    citations = [CitationSnapshot(chunk_id="missing", document_id="doc", page_number=10, evidence_text="hi")]
    assert citation_validity(citations, {}) == 0.0


def test_citation_validity_evidence_not_in_chunk() -> None:
    chunk = ChunkSnapshot(
        chunk_id="c1",
        document_id="doc",
        text="The total revenue was $94 billion.",
        page_start=10,
        page_end=11,
    )
    citations = [
        CitationSnapshot(
            chunk_id="c1",
            document_id="doc",
            page_number=10,
            evidence_text="completely fabricated quote",
        )
    ]
    assert citation_validity(citations, {"c1": chunk}) == 0.0


def test_citation_validity_empty_list_returns_zero() -> None:
    assert citation_validity([], {}) == 0.0


def test_citation_validity_partial() -> None:
    c1 = ChunkSnapshot(chunk_id="c1", document_id="d", text="Revenue was $94B.", page_start=10, page_end=11)
    c2 = ChunkSnapshot(chunk_id="c2", document_id="d", text="R&D rose.", page_start=20, page_end=21)
    citations = [
        CitationSnapshot(chunk_id="c1", document_id="d", page_number=10, evidence_text="Revenue was"),
        CitationSnapshot(chunk_id="c2", document_id="d", page_number=20, evidence_text="totally fabricated"),
    ]
    assert citation_validity(citations, {"c1": c1, "c2": c2}) == 0.5


# ---------- citation_coverage ----------


def test_citation_coverage_every_material_claim_cited() -> None:
    answer = "Apple revenue was $94 billion ##e1. Microsoft revenue was $245 billion ##e2."
    score = citation_coverage(answer, ["##e1", "##e2"])
    assert score == 1.0


def test_citation_coverage_no_material_claims_returns_one() -> None:
    answer = "There is no information about this topic in the filings."
    assert citation_coverage(answer, []) == 1.0


def test_citation_coverage_partial_coverage() -> None:
    answer = "Apple revenue was $94 billion ##e1. R&D spending rose 12% ."
    score = citation_coverage(answer, ["##e1"])
    assert score == 0.5


def test_citation_coverage_returns_half_when_tags_rendered_to_labels() -> None:
    # Legacy fallback: when only the rendered answer is available (older eval rows
    # without ``answer_with_tags``), the regex misses and we return 0.5.
    answer = "Apple revenue was $94 billion [AAPL 2024-10-31 10-K, p. 32]."
    score = citation_coverage(answer, ["##e1"])
    assert score == 0.5


def test_citation_coverage_real_signal_with_raw_tagged_answer() -> None:
    # New behavior: when the runner threads the pre-substitution answer through,
    # citation_coverage sees the ##eN tags directly and reports a real fraction.
    raw_answer = "Apple revenue was $94 billion ##e1. R&D rose 12% ."
    score = citation_coverage(raw_answer, ["##e1"])
    assert score == 0.5  # one of two material sentences carries a tag


def test_citation_coverage_empty_answer_returns_one() -> None:
    assert citation_coverage("", []) == 1.0
