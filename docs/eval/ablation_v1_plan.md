# Ablation v1 — pre-registration

Pre-registered: 2026-05-16. Locked before any production run was executed.

**Amendment 2026-05-18**: added the `single_pass_no_decomposition` knockout
(variant #9) covering the newly-introduced query-decomposition step in the
single_pass pipeline. The variant + its hypothesis (H9) are added below; the
FDR family expands from 24 to 27 tests. Variants 1-8 and their pre-registered
hypotheses are unchanged.

This document declares the hypotheses, endpoints, statistical tests, and
inclusion rules for the v1 component-lesion ablation study of the retrieval
pipeline. Any deviation from this plan during analysis must be flagged as
exploratory in the results write-up.

## 1. Objective

Quantify how much each retrieval component contributes to user-facing answer
quality and to verifiable retriever quality on the verified
`sec_filings_v1` corpus. The aim is to support component-level claims about
which pieces of the pipeline are doing real work, with paired statistical
inference, effect-size reporting, and FDR control across the family of
contrasts.

## 2. The variant matrix (locked)

Defined in `backend/packages/rag-common/rag_common/eval_variants.py` as
`LOCKED_ABLATION_VARIANTS`.

| #  | Variant name                       | retrieval_mode  | Overrides                                       | Isolates                              |
| -- | ---------------------------------- | --------------- | ----------------------------------------------- | ------------------------------------- |
| 1  | `full_agentic`                     | `full_agentic`  | —                                               | Baseline                              |
| 2  | `full_agentic_no_hyde`             | `full_agentic`  | `hyde_enabled=False`                            | HyDE                                  |
| 3  | `full_agentic_no_reranker`         | `full_agentic`  | `reranker_enabled=False`                        | Reranker                              |
| 4  | `full_agentic_no_hyde_no_reranker` | `full_agentic`  | `hyde_enabled=False, reranker_enabled=False`    | HyDE × Reranker interaction           |
| 5  | `single_pass`                      | `single_pass`   | —                                               | Agentic loop                          |
| 6  | `single_pass_semantic_only`        | `single_pass`   | `full_text_candidates=0`                        | Lexical (FTS) channel                 |
| 7  | `single_pass_lexical_only`         | `single_pass`   | `semantic_candidates=0`                         | Semantic (vector) channel             |
| 8  | `single_pass_no_reranker`          | `single_pass`   | `reranker_enabled=False`                        | Reranker outside the agent loop       |
| 9  | `single_pass_no_decomposition`     | `single_pass`   | `query_decomposition_enabled=False`             | Query decomposition (multi-query fan-out) |
| 10 | `llm_only`                         | `llm_only`      | —                                               | Retrieval-free floor                  |

All variants run inside one `EvalRun` against the same case set so the
contrasts are atomically paired.

## 3. Endpoints

### Primary (FDR-controlled)

| Endpoint               | Type        | Determinism                                     | Per-case key                          |
| ---------------------- | ----------- | ----------------------------------------------- | ------------------------------------- |
| `answer_accuracy`      | Continuous  | Deterministic (score_answer)                    | `metrics.answer_accuracy`             |
| `strict_recall_at_10`  | Continuous  | Deterministic (verified evidence only)          | `metrics.strict_recall_at_10`         |
| `expected_contains`    | Binary      | Deterministic (substring match)                 | `metrics.expected_contains`           |

The three primaries cover the retrieve / ground / answer layers of the
pipeline with no LLM-judge noise.

### Secondary (uncorrected)

`mrr`, `strict_mrr`, `page_evidence_f1`, `citation_validity`,
`citation_coverage`, `citation_gold_recall`, `citation_gold_precision`,
`metadata_filter_correctness`, `latency_ms` (log), `cost_usd` (log).

### Informational only

RAGAS `faithfulness`, `answer_relevancy`, `context_precision`,
`context_recall`. Reported in a separate diagnostics block, never under FDR
control: the judge LLM is non-deterministic even at temperature=0.

## 4. Hypotheses

Baseline = `full_agentic`. For each knockout the directional alternative is
that the baseline outperforms the knockout on accuracy/recall metrics. Tests
are one-sided in this direction for primary endpoints; secondary endpoints use
two-sided alternatives unless otherwise specified.

For each primary endpoint *E* ∈ {`answer_accuracy`, `strict_recall_at_10`,
`expected_contains`}:

- **H1**(*E*): `full_agentic` > `full_agentic_no_hyde`
- **H2**(*E*): `full_agentic` > `full_agentic_no_reranker`
- **H3**(*E*): `full_agentic` > `full_agentic_no_hyde_no_reranker`
- **H4**(*E*): `full_agentic` > `single_pass`
- **H5**(*E*): `full_agentic` > `single_pass_semantic_only`
- **H6**(*E*): `full_agentic` > `single_pass_lexical_only`
- **H7**(*E*): `full_agentic` > `single_pass_no_reranker`
- **H8**(*E*): `full_agentic` > `single_pass_no_decomposition`
- **H9**(*E*): `full_agentic` > `llm_only` (sanity check; expected largest effect)

FDR family = 9 contrasts × 3 endpoints = **27 tests**.

### Secondary (within-mode) contrast for decomposition

`single_pass` > `single_pass_no_decomposition` measures the lift of query
decomposition **inside** the single_pass pipeline, holding agency constant.
It is reported under "secondary (uncorrected)" — outside the FDR family —
because the primary family above is anchored to `full_agentic` as baseline
per the §4 policy. The within-mode contrast is the operationally interesting
one for the decision "should single_pass use decomposition by default?" but
is paired *under the same `EvalRun`* so the same case set + provider snapshot
underlies both arms.

## 5. Inclusion / exclusion

- **Population**: all 99 cases in `sec_filings_v1` with
  `verification_status = verified` and `gold_version = sec-filings-pdf-v1`.
- **Endpoint eligibility**: `answer_accuracy` is computed only when
  `answer_gold_eligible` is `true`; `strict_recall_at_10` only when
  `evidence_gold_eligible` is `true` (the same filtering already used by
  `runner._eligible_values`). `expected_contains` is computed for every
  case.
- **Pairing rule**: for any (metric, contrast), if either arm produced an
  error or a non-finite value for a case, that case is dropped from the
  contrast (and counted in `excluded_cases` in the report). The cross-variant
  count of dropouts is reported as `pairing_skew` at the top of the report.
- **Subgroup carve-outs**: `refusal` and `insufficient_evidence` categories
  score under different rubrics. They are *included* in the primary analysis
  (their per-case `answer_accuracy` is still 0..1 and well-defined), but
  flagged separately in the subgroup table.

## 6. Statistical recipe

### Continuous endpoints (paired)

- **Test**: Wilcoxon signed-rank with continuity correction. Exact
  enumeration when N ≤ 25 and no ties; normal approximation otherwise.
- **Alternative**: one-sided (greater) for primary endpoints per H1-H9;
  two-sided for secondaries.
- **Point + interval**: mean(b - a) ± 95 % paired bootstrap CI of the mean
  difference (5 000 resamples, seed=1729, paired indices).
- **Effect size**: paired Cliff's δ (Romano thresholds: 0.11 / 0.28 / 0.43)
  and paired Cohen's d (0.2 / 0.5 / 0.8).

### Binary endpoints (paired)

- **Test**: exact McNemar with mid-P on discordant pairs (b/c counts).
- **Point + interval**: risk difference = mean(b) − mean(a) with 95 % paired
  bootstrap CI on the 0/1 vectors.

### Latency / cost (log-paired)

- Log-transform first (`max(x, 1e-9)` guard); run Wilcoxon on the log
  vectors.
- Report geometric-mean ratio `exp(mean(log b) − mean(log a))` with the
  exponentiated CI.

### Multiple-comparison correction

- Benjamini-Hochberg step-up at **q = 0.05** across the 24-test family
  defined in §4. Both raw p and adjusted q are reported.
- Secondary endpoints are NOT in the FDR family — reported with raw p only
  and labelled "secondary (uncorrected)".
- Subgroup contrasts are explicitly exploratory; no FDR, no significance
  claims. Their purpose is hypothesis generation.

## 7. Power & sensitivity

With N=99 paired observations and α=0.05 one-sided Wilcoxon:

- Power 0.80 corresponds to roughly Cliff's δ ≈ 0.20 (between small and
  medium).
- After BH across 27 tests at q=0.05, the *least-significant* test in the
  family is effectively tested at α ≈ 0.05·k/27, so the minimum detectable
  effect at 80 % power rises to roughly **δ ≈ 0.30** (medium). The 24-test
  baseline figure is preserved in the git history for reference.

**Reporting note**: absence of a significant result at this N is not
evidence of no effect. Effects with Cliff's δ < 0.20 may be real but
under-powered; the CI of the mean difference is the primary lens for those
cases.

## 8. Determinism & stochasticity

Pinned for this study:

- `eval_temperature_zero=True` → OpenRouter chat payload sends
  `temperature: 0`; Pydantic AI agents are constructed with
  `ModelSettings(temperature=0)`; best-effort RAGAS judge temperature=0 (see
  caveat below).
- Bootstrap seed: 1729 (default). Same artifact + same seed → same numbers.
- Same case set across every variant inside one `EvalRun`.

Acknowledged residual stochasticity:

- OpenRouter does not pin model snapshots; provider may silently rev model
  versions between this run and a re-run.
- RAGAS judge wrappers expose temperature inconsistently across versions;
  the implementation does a best-effort set, but residual judge variance is
  acknowledged and RAGAS metrics are reported informational-only.
- Embedding APIs may produce slightly different vectors across batches /
  tokenizer revisions; the effect on cosine ranks is typically < 1e-3 and
  expected to be small at our top-k.
- The `full_agentic` tool loop can branch on small numerical ties even at
  temperature=0; this is a known source of agentic-loop variance.

## 9. Operational plan

1. **Smoke**: run 5 cases × 10 variants to verify schema, pairing-skew check,
   and analyzer output shape.
2. **Full study**:
   ```bash
   uv run --directory backend python -m rag_benchmarking.scripts.run_eval \
     --dataset <sec_filings_v1_id> \
     --ablation-preset locked9 \
     --output markdown \
     --artifact-dir artifacts/evals
   ```
3. **Analysis**:
   ```bash
   uv run --directory backend python -m rag_benchmarking.scripts.analyze_ablation \
     --artifact artifacts/evals/<eval_run_id>.json \
     --baseline full_agentic \
     --out docs/eval/ablation_v1_results.md \
     --csv docs/eval/ablation_v1_results.csv
   ```
4. **Sanity checks** before publishing the report:
   - `llm_only` shows the largest negative effect on every primary endpoint.
   - Pairing-skew block reports 0 missing cases (or ≤ a handful, documented).
   - Cost / latency geometric ratios are < 1 for every knockout vs the
     baseline.
   - Each variant's `retrieval_mode` + `overrides_applied` in the run config
     matches §2.

## 10. Out of scope (for v1)

- Parametric sweeps (tool-call budget, top-k) — separate study v2.
- Chunk-size sweep — requires re-ingestion of the corpus.
- Multi-seed estimates of generation variance — single seed for v1.
- Pinning OpenRouter model snapshots — separate hardening work.
