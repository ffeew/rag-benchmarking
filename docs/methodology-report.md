# Methodology Report: Scientific Evaluation of a Retrieval-Augmented Generation System on SEC Filings

## Abstract

This report documents the evaluation methodology used to benchmark a retrieval-augmented generation (RAG) system for question-answering over United States Securities and Exchange Commission filings. The study employs a pre-registered, paired ablation design over a closed catalog of ten retrieval-pipeline variants applied to ninety-nine verified test cases drawn from a corpus of three hundred and thirty-seven 10-K and 10-Q filings across fifty issuers. Each variant differs from the agentic baseline by exactly one component lesion (Hypothetical Document Embeddings, cross-encoder reranking, lexical full-text channel, semantic vector channel, query decomposition, or removal of retrieval entirely). The implementation fixes two deterministic continuous primary endpoints under Benjamini-Hochberg false-discovery-rate control — answer accuracy and strict-evidence recall at ten — across an eighteen-test family of contrasts; a normalized-substring binary endpoint and a battery of citation, retrieval, latency, and cost metrics are reported as secondaries without correction. Inference is paired — Wilcoxon signed-rank or McNemar mid-P with the appropriate alternative — with effect sizes reported as paired Cliff's δ and Cohen's d, and ninety-five-percent confidence intervals from a seeded paired bootstrap with five thousand resamples. Operational metrics travel under log-paired tests with geometric-mean ratios; RAGAS judge metrics are reported as informational only, explicitly outside the confirmatory family. The methodology is implemented in version-controlled code and seeded for full numerical reproducibility.

---

## 1. Introduction

### 1.1 Motivation

Retrieval-augmented generation systems are commonly evaluated with end-to-end answer-quality scores produced by a large language model acting as a judge. Such scores, while convenient, conflate retrieval failure, grounding failure, and generation failure into one number, and they introduce a stochastic judge into the measurement loop. The methodology described here decomposes the evaluation into a retrieval layer, a grounding layer, and an answer layer; uses deterministic scoring wherever possible; and reserves the LLM judge for text-rubric questions where deterministic matching cannot capture paraphrase equivalence.

The benchmark was designed to support causal claims about which retrieval-pipeline components are contributing to user-facing answer quality. Because such claims rest on contrasts between similar systems applied to the same input cases, the design is fully paired: every variant under study evaluates the same case in the same evaluation run, against the same gold annotations, under temperature-zero generation. Statistical inference is conducted on the case-wise differences, not on aggregate means computed independently per arm.

### 1.2 Pre-registration and reproducibility commitments

The variant matrix, primary endpoints, hypothesis directions, multiple-comparisons family, and inclusion rules were locked in `docs/eval/ablation_v1_plan.md` prior to running any evaluation that contributed to the analysis. The pre-registration is dated 2026-05-16, with one documented amendment on 2026-05-18 that added the query-decomposition lesion (variant nine) and expanded the false-discovery-rate family from twenty-four to twenty-seven tests. All deviations from the pre-registered analysis at write-up time are flagged as exploratory.

Three reproducibility commitments support replay of the numerical results:

- A single bootstrap seed (1729) is propagated through the aggregator's confidence-interval helper and the ablation analyzer's paired-bootstrap helper.
- Generation, judge, and Retrieval-Augmented Generation Assessment (RAGAS) calls run at temperature zero whenever `eval_temperature_zero` is set.
- The gold annotations are pinned to a named version (`sec-filings-pdf-v1`); the corpus is checked in as PDF files under `sec_filings_pdf/`.

The remaining sources of residual non-determinism are enumerated in §10.

---

## 2. Experimental design

### 2.1 Population

The evaluation population comprises ninety-nine cases held in `backend/eval_cases/sec_filings_v1.yaml`, all with `verification_status = verified` and `gold_version = sec-filings-pdf-v1`. The cases were authored against PDF filings under `sec_filings_pdf/` and each gold answer and citation was verified by direct human inspection of the source document. The case set is structured into nine categories chosen to stress different parts of the pipeline:

| Category                  |  N | Stress target                                                     |
|---------------------------|---:|-------------------------------------------------------------------|
| single_company_lookup     | 35 | Direct factual retrieval from a single filing.                     |
| table_lookup              | 11 | Values residing in tabular content; table-aware chunking.          |
| multi_part                | 10 | Multi-clause questions; query decomposition.                       |
| trend                     |  8 | Multi-year direction; multi-document synthesis within an issuer.   |
| latest_filing             |  8 | Resolution of temporal references against ingested metadata.       |
| cross_company_comparison  |  8 | Same metric across multiple issuers; multi-document synthesis.     |
| sector_synthesis          |  7 | Thematic questions across a sector; multi-pass retrieval.          |
| insufficient_evidence     |  7 | Questions whose answer is not in the corpus; insufficiency rubric. |
| refusal                   |  5 | Questions outside the system's scope; refusal rubric.              |

The refusal and insufficient-evidence subsets are included in the primary analysis because their per-case answer accuracy is well-defined under their respective rubrics (§5.3); they are flagged in the subgroup table as separate strata for exploratory analysis.

### 2.2 Case schema

Each case is a structured record with the following fields, persisted to `EvalCase` rows:

- `case_key`, `category`, `difficulty`, `tags`: identifiers and metadata.
- `question`: the natural-language query submitted to the system.
- `expected_answer`: a free-text reference answer.
- `expected_answer_spec`: structured gold of type `ExpectedAnswerSpec` (defined at `backend/packages/rag-common/rag_common/schemas.py`), routing scoring on `answer_type ∈ {NUMERIC, TEXT, MULTI_PART, INSUFFICIENT, REFUSAL}` and carrying `expected_values`, `required_claims`, and `required_reason_keywords` as the rubric demands.
- `expected_citations`: lightweight per-case hints — ticker, form type, page number, optional document identifier and evidence text — used for the legacy retrieval metrics.
- `expected_evidence`: verified evidence records of type `ExpectedEvidenceSpec` carrying page number, filing date, evidence snippet, and optional `table_key`; these underlie the strict-recall variants and the parser-quality diagnostics.

### 2.3 Verification protocol

A case enters the strict subset for an endpoint only when two conditions hold simultaneously: its `verification_status` is `VERIFIED`, and the appropriate gold field is parseable. Concretely, `answer_gold_eligible` requires both `verified` status and a non-empty `expected_answer_spec` that resolves to a `score_answer`-reachable type; `evidence_gold_eligible` requires both `verified` status and at least one entry of `expected_evidence` that satisfies the strict-eligibility predicate (`page_number is not None` and either `document_id` or both `ticker` and `form_type` populated). The runner computes these flags at case-evaluation time (`runner.py:_compute_case_metrics`), and the aggregator uses them as eligibility filters (`eval_aggregation.py:_eligible_values`).

### 2.4 Benchmark profiles

Evaluation runs are launched under one of two named profiles, distinguished in `EvalRun.run_config.benchmark_profile`. The `SCIENTIFIC` profile is mandatory for confirmatory analysis: at launch, the API gate at `routes/evaluations.py:_validate_scientific_cases` rejects the run if any case lacks both `expected_answer_spec` and a non-empty `expected_evidence`. The `DIAGNOSTIC` profile relaxes this constraint to allow exploratory work on draft cases; results from diagnostic runs are excluded from the pre-registered analysis.

---

## 3. Variant matrix (independent variable)

### 3.1 The ten locked variants

The catalog `LOCKED_ABLATION_VARIANTS` in `backend/packages/rag-common/rag_common/eval_variants.py` defines ten retrieval-pipeline configurations. The baseline is the agentic full-pipeline configuration; each other variant differs from a named baseline by exactly one component lesion. The complete matrix:

| # | Variant name                          | Retrieval mode | Overrides applied                             | Isolated component                       |
|---|---------------------------------------|----------------|-----------------------------------------------|-------------------------------------------|
| 1 | `full_agentic`                        | FULL_AGENTIC   | —                                             | Primary baseline                          |
| 2 | `full_agentic_no_hyde`                | FULL_AGENTIC   | `hyde_enabled=False`                          | Hypothetical Document Embeddings (HyDE)   |
| 3 | `full_agentic_no_reranker`            | FULL_AGENTIC   | `reranker_enabled=False`                      | Cross-encoder reranker                    |
| 4 | `full_agentic_no_hyde_no_reranker`    | FULL_AGENTIC   | `hyde_enabled=False, reranker_enabled=False`  | HyDE × Reranker interaction               |
| 5 | `single_pass`                         | SINGLE_PASS    | —                                             | Agentic tool loop (vs single-pass)        |
| 6 | `single_pass_semantic_only`           | SINGLE_PASS    | `full_text_candidates=0`                      | Lexical (full-text-search) channel        |
| 7 | `single_pass_lexical_only`            | SINGLE_PASS    | `semantic_candidates=0`                       | Semantic (vector) channel                 |
| 8 | `single_pass_no_reranker`             | SINGLE_PASS    | `reranker_enabled=False`                      | Reranker inside the non-agentic pipeline  |
| 9 | `single_pass_no_decomposition`        | SINGLE_PASS    | `query_decomposition_enabled=False`           | Query decomposition (multi-query fan-out) |
|10 | `llm_only`                            | LLM_ONLY       | —                                             | All retrieval (sanity-check floor)        |

The names are the join key for the statistical analyzer (`ablation_analysis.py:_variant_of`), and the overrides are the only knob that distinguishes pipelines at runtime.

### 3.2 Component lesions

HyDE generates a hypothetical answer with a small LLM call and embeds that passage in place of (or alongside) the question; disabling it tests whether the query-rewriting step is contributing to retrieval. The cross-encoder reranker reorders the fused candidate list by a second pass; disabling it tests whether the fused first-stage ranking is by itself adequate. The lexical and semantic channels feed the reciprocal-rank-fusion stage in the non-agentic pipeline; zeroing one channel's candidate budget disables that channel without code changes. Query decomposition splits a multi-clause question into sub-questions whose retrieval results are fused; disabling it tests whether decomposition adds lift over a single retrieval pass. The `llm_only` arm bypasses retrieval entirely and answers directly from the model's parametric knowledge; it serves as a sanity-check floor on every primary endpoint.

### 3.3 Variant application

A `RetrievalVariantSpec` carries `name`, `retrieval_mode`, and an `overrides` object of type `RetrievalOverrides`. The function `apply_overrides(base, overrides)` clones the global `Settings` with the per-variant overrides applied (or returns the input unchanged if the override dictionary is empty, to avoid a needless copy on the baseline). At evaluation time, the runner materializes the variant specs once and applies them inside the per-case loop:

```python
overrides_dump = spec.overrides.model_dump(exclude_none=True)
effective = apply_overrides(resolved, spec.overrides)
response = run_query(session, request=..., settings=effective)
```

This pattern keeps the variant configuration entirely declarative — no code path is conditionally enabled by a variant name — so a new variant can be added by extending `LOCKED_ABLATION_VARIANTS` without touching the pipeline.

---

## 4. Evaluation procedure

### 4.1 End-to-end run loop

A single evaluation run iterates over the Cartesian product of `cases × variants`. The orchestrator `run_evaluation` in `backend/packages/rag-evaluation/rag_evaluation/runner.py` proceeds as follows. After validating that every selected case meets the scientific-profile constraint, it materializes the variant specs from `run_config['variants']` and constructs the LLM judge (or `None` if mock-providers mode is active). Then, for each `(case, variant)` pair, it:

1. Applies the variant's overrides to the run-wide settings.
2. Invokes the retrieval pipeline through `run_query`, requesting both the answer payload and the full retrieval trace (`include_trace=True, include_full_retrieval=True`).
3. Measures wall-clock latency in milliseconds.
4. Calls `_compute_case_metrics`, which produces the per-case metric dictionary detailed in §5.
5. Persists an `EvalResult` row carrying the answer text, the trace identifier, the metric dictionary, the token-usage breakdown by pipeline role, and the priced cost estimate.
6. Stores a `(EvalResult, sample)` tuple on the `pending_ragas` queue for the optional informational judge phase.

Upon completion of the per-case loop, the runner serially computes RAGAS metrics (§5.7) for cases that produced an answer, recomputes the aggregate over all `EvalResult` rows (§6), records the `pairing_skew` audit, and attaches the `AblationReport` (§7) to `eval_run.metrics`.

### 4.2 Per-case isolation and partial aggregation

Each `(case, variant)` evaluation runs inside a Postgres `SAVEPOINT` (`session.begin_nested()`). A failure mid-case rolls back only the inner transaction, leaving the outer transaction intact and allowing the loop to continue. On error, the runner persists a stub `EvalResult` row carrying the exception class and message, so the failure remains visible in the dataset even though the metric fields are empty.

The runner commits after every persisted row and, every `eval_partial_aggregate_every` cases, recomputes a partial aggregate over the in-database results and writes it to `eval_run.metrics` with a `_partial` marker. A worker crash mid-run therefore loses at most one in-flight case rather than the entire evaluation, and the API's read path can stream partial results to the dashboard while the loop is still running.

### 4.3 Determinism controls

Five settings control determinism for confirmatory runs:

- `eval_temperature_zero=True`: generation, the answer-text judge, and the RAGAS LLM wrapper are forced to temperature zero. Pydantic-AI agents construct `ModelSettings(temperature=0)` at agent build time.
- `bootstrap_seed=1729`: passed through `aggregate_metrics → bootstrap_mean_ci`, and through `run_ablation_analysis → paired_bootstrap_diff_ci`. Same artifact plus same seed always yields the same intervals.
- Same case set across every variant in one `EvalRun`: the pre-registration requires that variants be paired atomically rather than across separate runs.
- Fixed gold version (`sec-filings-pdf-v1`): annotations are pinned and changes are version-bumped.
- Fixed variant catalog (`LOCKED_ABLATION_VARIANTS`): the pre-registered nine plus the LLM-only floor.

### 4.4 Procedural diagram

```
        ┌──────────────────────────────────────────────────────────┐
        │  EvalRun.run_config (case_ids, variants, profile, seed)  │
        └────────────────────────────┬─────────────────────────────┘
                                     │
                          [ resolve cases & specs ]
                                     │
            ┌────────────────────────┴────────────────────────┐
            │  for case in cases:                              │
            │    for spec in specs:    ─────────────────────┐  │
            │      apply_overrides(settings, spec.over...)  │  │
            │      run_query(...)  → QueryResponse, trace   │  │
            │      _compute_case_metrics → metric dict      │  │
            │      persist EvalResult  + commit             │  │
            │    every N cases: partial aggregate snapshot  │  │
            └────────────────────────┬────────────────────────┘
                                     │
                           [ attach RAGAS (informational) ]
                                     │
                       [ aggregate_metrics(results, seed) ]
                                     │
                  [ run_ablation_analysis → AblationReport ]
                                     │
                       EvalRun.metrics ← final report
```

---

## 5. Metrics (dependent variables)

The per-case metric dictionary is produced by `_compute_case_metrics` and decomposes into the layers described in this section. Throughout, $E$ denotes the set of expected citations for a case, $R = (r_1, r_2, \ldots)$ the retrieval-ordered list of retrieved chunks, and $C$ the set of citations the generator emitted. The match predicate $\text{match}(e, r)$ is defined in §5.1.

### 5.1 Retrieval metrics

The retrieval layer measures whether the pipeline surfaced the documents and pages necessary to answer the question. Two variants of each metric are computed: a lenient variant against `expected_citations` (which permits ticker-only hints) and a strict variant against the `strict_evidence_eligible` filter applied to `expected_evidence` (which requires page number plus document identifier or ticker-plus-form-type). Both are implemented in `backend/packages/rag-evaluation/rag_evaluation/metrics.py`.

#### 5.1.1 Match predicate

For a lenient match between expected citation $e$ and retrieved chunk $r$:

$$
\text{match}(e, r) = \begin{cases}
[r.\text{document\_id} = e.\text{document\_id}] \wedge [\text{page}(e, r)] & \text{if } e.\text{document\_id} \neq \emptyset, \\[2pt]
[\text{ticker}(e, r)] \wedge [\text{form}(e, r)] \wedge [\text{page}(e, r)] & \text{otherwise},
\end{cases}
$$

where $\text{page}(e, r)$ is true iff $e.\text{page\_number}$ is null or falls within $[r.\text{page\_start}, r.\text{page\_end}]$.

The strict-match predicate (`_strict_single_match`) additionally requires $e.\text{page\_number}$ to be non-null and to fall within the chunk's page range, and disqualifies ticker-only hints by requiring both ticker and form type when no document identifier is supplied.

#### 5.1.2 Recall at k

The fraction of expected citations matched by the top-$k$ retrieved chunks:

$$
\mathrm{Recall@k}(E, R) = \frac{|\{e \in E : \exists r \in R_{1..k}, \text{match}(e, r)\}|}{|E|}.
$$

The function returns zero when $|E| = 0$ or $k \leq 0$. Both $k=5$ and $k=10$ are computed and persisted per case (`metrics.recall_at_5`, `metrics.recall_at_10`). The strict variant `strict_recall_at_k` applies the strict-match predicate over the `strict_evidence_eligible` filter.

#### 5.1.3 Mean reciprocal rank

The reciprocal rank of the first match, or zero if no match exists in $R$:

$$
\mathrm{MRR}(E, R) = \begin{cases}
1 / \max(1, \mathrm{rank}(r^*)) & \text{if } \exists r^* \in R, \exists e \in E, \text{match}(e, r^*), \\[2pt]
0 & \text{otherwise.}
\end{cases}
$$

The implementation iterates through $R$ in retrieval order and returns at the first match. Rank values are floored to one to prevent division by zero in degenerate trace data.

#### 5.1.4 Page-evidence F1

The set of retrieved chunks is flattened into page units — one $(r, p)$ tuple per page $p \in [r.\text{page\_start}, r.\text{page\_end}]$ — and deduplicated by $(r.\text{document\_id}, p)$. This deduplication is material: two overlapping chunks that share a page contribute one unit, not two, preventing double-counting that would inflate page-level recall on overlap-heavy variants. Let $U$ denote the deduplicated page units. Define the relevant set and the covered-expected set:

$$
\mathrm{rel}(U, E) = \{(r, p) \in U : \exists e \in E, \text{page\_match}(e, r, p)\},
$$
$$
\mathrm{cov}(E, U) = \{e \in E : \exists (r, p) \in U, \text{page\_match}(e, r, p)\}.
$$

Then page-evidence F1 is the harmonic mean of precision and recall over those sets:

$$
P = |\mathrm{rel}(U, E)| / |U|, \quad R_{\text{page}} = |\mathrm{cov}(E, U)| / |E|, \quad F_1 = \frac{2 P R_{\text{page}}}{P + R_{\text{page}}}.
$$

When both inputs are empty, the function returns one (vacuous truth); when only one is empty, it returns zero. The strict variant uses `_strict_page_match`, which requires the expected page to match exactly and disqualifies ticker-only hints.

#### 5.1.5 Chunk-evidence F1

Identical in structure to §5.1.4 but applied at chunk granularity rather than page granularity. Precision is the fraction of retrieved chunks that match some expected citation; recall is the fraction of expected citations matched by some retrieved chunk; $F_1$ is the harmonic mean. Same vacuous-truth and one-sided-empty conventions apply.

#### 5.1.6 Metadata filter correctness

A binary signal that audits the planner's filter selection. Let $T$ be the set of tickers in the planner's `target_tickers` filter and $F$ the set of forms in the planner's `forms` filter, both upper-cased. The metric returns zero if any expected citation $e \in E$ is excluded by the filter — that is, if $T$ is non-empty and $e.\text{ticker} \notin T$, or if $F$ is non-empty and $e.\text{form\_type} \notin F$. It returns one otherwise, and one trivially when $|E| = 0$. The metric is a confirmatory check on the planner: if it fails, the retrieval-side metrics are bounded above regardless of the embedding and reranker quality.

### 5.2 Citation metrics

The citation layer measures whether the generator's textual claims are grounded in the chunks it cites. The implementation lives in `metrics.py:citation_validity` and `metrics.py:citation_coverage`.

#### 5.2.1 Citation validity (grounding)

For each citation $c \in C$, the metric resolves $c.\text{chunk\_id}$ against the snapshot of chunks emitted with the response and tests whether $c.\text{evidence\_text}$ is grounded in the resolved chunk's text. Grounding is checked with a normalized prefix containment: both strings are lower-cased and have whitespace runs collapsed; the first eighty characters of the citation's evidence text must appear as a substring of the chunk's text:

$$
\text{grounded}(c) = \big[\text{prefix}_{80}\!\big(\mathrm{norm}(c.\text{evidence\_text})\big) \subseteq \mathrm{norm}(\text{chunk}(c).\text{text})\big].
$$

The metric is the fraction of citations satisfying $\text{grounded}$; it returns zero when $|C| = 0$. The eighty-character prefix is a deliberate compromise: short enough that chunker truncation does not flip the verdict, long enough that an LLM-fabricated evidence string is unlikely to coincidentally match.

#### 5.2.2 Citation coverage (material claims)

The answer text is split into sentences by a regex on terminal punctuation. A sentence is *material* if it contains a number, percentage, dollar amount, or one of the lexical markers (`million`, `billion`, `trillion`, `basis points`, `bps`). The coverage is the fraction of material sentences that contain at least one citation tag of the form `##eN` (`_CITATION_TAG_RE = ##e(\d+)`):

$$
\mathrm{Coverage} = \frac{|\{s \in S_{\text{material}} : \exists N, \text{\#\#e}N \in s\}|}{|S_{\text{material}}|}.
$$

If the answer contains no material claims the metric returns one (nothing to cite). To accommodate generators that strip raw tags in favor of rendered labels, the metric returns a fallback value of one-half when no `##e` tags are found but the `citations_used` list emitted by the generator is non-empty; this prevents a styling change in the renderer from collapsing the coverage rate to zero. The runner passes the pre-substitution `answer_with_tags` rather than the rendered answer when available, so this fallback path is rare in normal operation.

#### 5.2.3 Citation gold precision and recall

Where strict gold evidence is available, the runner also computes precision and recall of the generator's citation set against the verified evidence. A response citation matches an expected evidence entry on the conjunction of ticker, form type, and page number (`_citation_matches_expected`). Precision is the fraction of response citations matching at least one verified evidence entry; recall is the fraction of verified evidence entries matched by at least one response citation. These are reported as `citation_gold_precision` and `citation_gold_recall`; they are null on cases without verified evidence.

#### 5.2.4 Citation page hit

A simpler ratio used in the run-wide summary: the fraction of `(ticker, form_type, page_number)` triples in the expected citations that appear in the response's citations. Less strict than `citation_gold_*` because it ignores `document_id` and operates on the lenient hint set.

### 5.3 Answer quality

The answer layer measures whether the generator's response asserts the gold answer. Routing is by `expected_answer_spec.answer_type`; the entry point is `scoring.py:score_answer`.

#### 5.3.1 NUMERIC

Numeric candidates are extracted from the answer text by a single regex (`_NUMBER_RE`) that captures an optional dollar prefix, a signed integer or decimal with optional comma separators, and an optional unit suffix among `%`, `million`, `billion`, `trillion`, `basis points`, `bps`. For each expected value:

- Unit matching (`_unit_matches`) accepts `$` to match `million`, `billion`, or `trillion` (financial filings commonly state dollar amounts in those units); `percent`/`percentage` to match `%`; `basis points` to match `bps`. If a unit is required and at least one candidate satisfies it, the candidate set is restricted to unit-matching candidates; if none match, the full candidate set is retained.
- Tolerance is the maximum of (a) one one-hundredth (a small absolute floor), (b) `tolerance_abs` if supplied, (c) `|expected| × tolerance_pct / 100` if supplied, and (d) `|expected| × 0.005` (a half-percent default) if neither `tolerance_abs` nor `tolerance_pct` is supplied. The default 0.5 % tolerance allows for minor rounding differences in published figures.
- The value scores one if any retained candidate's absolute deviation from the expected value is within the tolerance, and zero otherwise.

#### 5.3.2 TEXT

A text expected value carries a string `value_text`. With an LLM judge configured (§5.4), the judge is asked to determine whether the answer asserts the statement (returning the binary verdict and a rationale). Without a judge — for example, in offline or mock-providers mode — the metric falls back to normalized substring containment: $\mathrm{norm}(\text{value\_text}) \in \mathrm{norm}(\text{answer})$, where `_normalize` lower-cases and collapses whitespace.

#### 5.3.3 INSUFFICIENT and REFUSAL

A correctly insufficient answer asserts that the corpus does not support an answer; a correctly refused answer states that the question is out of scope. Detection uses a small lexicon of phrases — `insufficient`, `not enough evidence`, `does not contain` for insufficiency; `refusal`, `cannot provide`, `personalized`, `investment advice` for refusal — checked against the normalized concatenation of the answer and any insufficiency reason. In addition, `required_reason_keywords` from the gold spec must achieve a one-hundred-percent normalized-substring hit rate. Accuracy is one only if both the correctness flag and the keyword hit rate are satisfied; otherwise it is zero.

#### 5.3.4 MULTI_PART

For multi-part questions, the scorer averages the value scores (each computed under §5.3.1 or §5.3.2 as the value's type dictates) with the `required_claims` hit rate. The claim hit rate is the mean of binary verdicts produced by the LLM judge over the claim list, falling back to substring containment when no judge is configured. The returned `value_scores` and `required_claim_verdicts` arrays carry the per-item match type and (when judged) the rationale, supporting per-claim audit in the dashboard.

#### 5.3.5 expected_contains

A deterministic sanity check independent of the structured spec: $\mathrm{norm}(\text{expected\_answer}) \in \mathrm{norm}(\text{answer})$. It is computed for every case (zero when no expected answer is provided), and forms the binary primary endpoint in §7.

#### 5.3.6 answer_present and insufficient

`answer_present` is a binary indicator of any non-empty answer. `insufficient` is the binary `answer_declined_to_respond`, which detects whether the rendered answer asserts insufficiency or refusal regardless of the gold-typed scoring path; it counts what the model actually said rather than what the planner upstream flagged, so it tracks generation-side hedging.

### 5.4 LLM-as-judge protocol

The LLM judge is a single chat-completion call against a Z.AI-compatible OpenAI client. It is built once per evaluation run via `judge.py:build_text_judge` and threaded through `score_answer`. The judge model identifier is `settings.zai_judge_model`; temperature is forced to zero when `eval_temperature_zero` is set; the response format is JSON.

The system prompt is (`judge.py:_JUDGE_SYSTEM_PROMPT`):

```
You are an expert evaluator. Decide whether a model's answer asserts a specific required statement.

SCORING RUBRIC (binary):
- Score 1.0 if the answer asserts the statement. Paraphrase, synonyms, alternate phrasing, and word reordering are acceptable as long as the propositional meaning is preserved.
- Score 0.0 if the statement is absent from the answer, contradicted by the answer, or only ambiguously implied.

Be lenient about phrasing; be strict about negation. "X did not happen" must not match an answer that says "X happened" (and vice versa).

If the statement contains a number, treat the answer as asserting it only when the same value appears (an equivalent representation is fine — "$1.5 billion" matches "$1,500 million").

Respond as a single JSON object: {"score": <0.0 or 1.0>, "rationale": "<one short sentence explaining the score>"}.
Do not include any text outside the JSON object.
```

The user message is the literal `STATEMENT TO LOOK FOR: <statement>\n\nMODEL ANSWER: <answer>`. The response is parsed with `_parse_verdict`, which strips markdown fences if present, falls back to a permissive `{...}` regex if JSON parsing fails, and coerces any off-rubric numeric score to the nearer of zero or one (so a model that returns 0.7 does not silently shift the mean). On parse failure or upstream exception, the judge returns a zero score and a structured rationale (`parse_error: ...`, `judge_error: ...`); a single ill-formed response cannot crash the per-case loop.

The judge is built only when Z.AI is configured and mock-providers mode is off; otherwise `build_text_judge` returns `None` and the text-scoring path falls back to deterministic substring matching. This fallback is the test-suite default and is documented as a degraded mode in §10.5.

### 5.5 Multi-criteria pass gate

The dashboard's per-case PASS/FAIL badge derives from `runner.py:_compute_passed`, which gates a case on the conjunction of answer accuracy and citation validity:

$$
\mathrm{passed} = \begin{cases}
\mathrm{None} & \text{if not } \mathrm{answer\_gold\_eligible}, \\[2pt]
\mathrm{True} & \text{if } \mathrm{answer\_accuracy} \geq \theta_{\text{acc}} \wedge \mathrm{citation\_validity} \geq \theta_{\text{val}}, \\[2pt]
\mathrm{False} & \text{otherwise.}
\end{cases}
$$

Thresholds are configurable; the production defaults are $\theta_{\text{acc}} = 1.0$ and $\theta_{\text{val}} = 0.5$. The gate is intentionally tri-valued: cases without verified gold answers surface as "N/A" in the dashboard rather than being silently failed. Recall@5 is deliberately not part of the gate — a case that produced the correct answer with grounded citations passes even if the retriever surfaced different valid pages than the annotator picked. `avg_recall_at_5` remains a per-variant diagnostic.

### 5.6 Operational metrics

Three operational metrics travel alongside the quality metrics. Latency is the wall-clock duration of `run_query` in milliseconds. Token usage is decomposed by pipeline role — `planner`, `verifier`, `generator`, `embedding`, `rerank`, `judge` — and persisted as a `TokenUsage` dict; the aggregator sums total tokens across roles. Cost is a per-role estimate produced by the `PricingResolver` against the resolved model identifier and the role's token counts; the per-case cost is the sum across roles. Latency and cost are subjected to log-paired statistical analysis in §7.5.

### 5.7 Informational metrics (RAGAS)

Following the per-case loop, the runner runs the RAGAS judge phase (`runner.py:_attach_ragas_scores`) when `eval_run_ragas` is set. RAGAS computes up to four metrics through the same Z.AI judge model: `faithfulness`, `context_precision`, `answer_relevancy` (when an embedding model is configured), and `context_recall` (when a reference answer is present). Each metric is one LLM call per case; failures are caught at the per-metric granularity and the affected case proceeds with the remaining metrics.

These scores are reported as informational only. They are not part of the confirmatory analysis and not subjected to FDR correction. The reasons are documented in the pre-registration: the judge LLM is non-deterministic even at temperature zero, the wrapper's temperature setter is best-effort and version-fragile, and RAGAS's structured-output retry behavior occasionally exhausts attempts on long answers. The scores are attached to `metrics.judge_diagnostics.ragas` and rendered in a separate diagnostics panel.

---

## 6. Aggregation

### 6.1 Per-variant summaries

`backend/packages/rag-common/rag_common/eval_aggregation.py:aggregate_metrics` buckets the per-case `EvalResult` rows on `variant_name` (falling back to `retrieval_mode` for legacy rows). For each bucket it produces a `_summary_for_metrics` block containing eligibility-filtered means, bootstrap confidence intervals on the primary endpoints, the multi-criteria pass rate and pass count, the absolute and percentage retrieval metrics with their strict variants, the citation metrics, the parser diagnostics, latency, cost, and total tokens. The aggregator never invokes scoring — every per-case metric is already a plain dict on the row by the time aggregation runs — so the read path can recompute aggregates at API serialization time without taking a dependency on the scoring stack.

### 6.2 Bootstrap confidence intervals

The aggregator's `bootstrap_mean_ci(values, seed, samples=500)` returns a two-sided ninety-five-percent percentile bootstrap CI of the mean. It is seeded so the same input and seed always yield the same interval; the same routine reports the run-wide CI on `answer_accuracy_rate` and on `evidence_recall_at_10`. The dashboard-level CIs are deliberately coarser (five hundred resamples) than the ablation analyzer's case-level CIs (five thousand resamples, §7.7); the dashboard CI describes uncertainty in the *aggregate mean*, while the ablation CI describes uncertainty in the *mean paired difference* and therefore needs more precision.

### 6.3 Breakdowns

Each per-variant summary is replicated per category, per difficulty, and per tag. The category and difficulty breakdowns are grouped by the metric dictionary's `category` and `difficulty` fields; the tag breakdown projects each case into one entry per tag (a case tagged `[revenue, 10k, factual]` contributes to all three buckets), with an `untagged` bucket for cases without tags. Each bucket carries the same `_summary_for_metrics` shape, so the dashboard can render any breakdown uniformly.

### 6.4 Pairing-skew audit

After the per-case loop, the runner constructs a `pairing_skew` block by passing the per-variant set of successfully-evaluated case identifiers through `_detect_pairing_skew`. The block reports the expected case count, the per-variant case counts, the per-variant missing-case lists, and a `balanced` flag. The ablation analyzer surfaces a warning at the top of the rendered report when `balanced` is false, and individual case-pair contrasts drop any case that is missing from either arm. A persistent imbalance — for example, one variant consistently crashing on `cross_company_comparison` cases — biases the contrasts and is the most common reason for re-running an evaluation.

---

## 7. Statistical methodology

The ablation analyzer (`backend/packages/rag-evaluation/rag_evaluation/ablation_analysis.py`) takes the per-case `EvalResult` rows, builds paired matrices on the endpoints, runs the appropriate test for each baseline-treatment pair, applies false-discovery-rate correction across the primary family, and returns an `AblationReport` dataclass.

### 7.1 Primary endpoints

The confirmatory family is restricted to two deterministic continuous endpoints that cover the retrieve-and-answer layers without LLM-judge noise. They are defined by the `PRIMARY_ENDPOINTS_DEFAULT` tuple in `ablation_analysis.py`:

| Endpoint              | Type       | Determinism                                | Per-case key                                              |
|-----------------------|------------|--------------------------------------------|-----------------------------------------------------------|
| `answer_accuracy`     | Continuous | Deterministic (regex / substring / judge)¹ | `metrics.answer_accuracy`                                 |
| `strict_recall_at_10` | Continuous | Deterministic (verified evidence only)     | `metrics.strict_recall_at_10` (or `evidence_recall_at_10`)|

¹ For TEXT and MULTI_PART rubrics the judge is in the loop; deterministic in the sense of "same seed-pinned judge, same answer, same verdict in practice," subject to the residual stochasticity in §10.

The pre-registration in `docs/eval/ablation_v1_plan.md` additionally lists `expected_contains` (a binary, normalized-substring sanity check) as a third primary. The current production code classifies `expected_contains` as a secondary endpoint, so the executed FDR family is two primaries × nine knockout contrasts = eighteen tests rather than the twenty-seven tests stated in the pre-registration. The discrepancy is acknowledged here; any write-up that references the pre-registered count must apply the running code's count instead, and the corresponding minimum detectable effect (§9) is recalibrated.

### 7.2 Secondary endpoints

Reported with raw p-values and confidence intervals but without false-discovery-rate correction: `expected_contains`, `mrr`, `strict_mrr`, `page_evidence_f1`, `chunk_evidence_f1`, `strict_chunk_f1`, `citation_validity`, `citation_coverage`, `citation_gold_recall`, `citation_gold_precision`, `metadata_filter_correctness`. Their purpose is descriptive — they help diagnose which layer of the pipeline produced an observed primary-endpoint movement — but they are not part of the confirmatory family.

### 7.3 Continuous primaries: paired Wilcoxon signed-rank

For a baseline-treatment pair on a continuous endpoint, the analyzer builds a paired matrix indexed by case identifier: a case is included if and only if it has a finite metric value for *every* variant in the variant set, ensuring same-N pairing across all contrasts. Let $a_i$ and $b_i$ denote the per-case metric values for baseline and treatment respectively, and $d_i = b_i - a_i$.

The Wilcoxon signed-rank statistic is computed in `paired_stats.py:wilcoxon_signed_rank`. Zero differences are dropped (the `wilcox` convention); absolute differences are rank-averaged with mid-ranks for ties. Define $W^+ = \sum_{d_i > 0} \mathrm{rank}(|d_i|)$ and $W^- = \sum_{d_i < 0} \mathrm{rank}(|d_i|)$; the reported statistic is $W = \min(W^+, W^-)$.

For $n \leq 25$ paired observations and no ties, the exact p-value is computed by enumerating all $2^n$ sign assignments. Otherwise the normal approximation with continuity correction is used, with tie-adjustment to the variance:

$$
\mu_W = \frac{n(n+1)}{4}, \qquad
\sigma^2_W = \frac{n(n+1)(2n+1)}{24} - \frac{1}{48}\sum_{t} (t^3 - t),
$$

where the sum runs over the tie group sizes $t$. For the pre-registered one-sided alternative (baseline > treatment, i.e., $b - a < 0$):

$$
z = \frac{(W^+ - \mu_W) + 0.5}{\sigma_W}, \qquad p = \Phi(z).
$$

The continuity correction of $\pm 0.5$ matches the direction of the alternative.

### 7.4 Binary endpoints: McNemar mid-P

The analyzer routes any endpoint listed in `BINARY_ENDPOINTS` (currently the singleton `expected_contains`) through the exact McNemar test with mid-P correction, irrespective of whether it is in the primary or secondary family. The per-case value is thresholded at one-half (`v ≥ 0.5`) into 0/1 arms (`paired_stats.py:mcnemar_midp`). Let $b$ count cases where the baseline is correct and the treatment is wrong, and $c$ count the inverse. Under the null hypothesis of equal split, the discordant count $X = \min(b, c)$ on $n = b + c$ trials follows a binomial:

$$
p_{\text{one-tailed}} = \sum_{i=0}^{k-1} \binom{n}{i} \cdot 2^{-n} + \tfrac{1}{2} \binom{n}{k} \cdot 2^{-n}, \quad k = \min(b, c),
$$

reported two-sided as $p_{\text{two-tailed}} = \min(1, 2 p_{\text{one-tailed}})$. The mid-P correction halves the point-mass contribution at the boundary, making the test less conservative than the exact McNemar when discordant pairs are few. The risk difference $b - a$ is computed as $(\mathrm{mean}(b) - \mathrm{mean}(a))$ on the binarized arms; its bootstrap CI is computed on the 0/1 vectors directly.

### 7.5 Latency and cost: log-paired Wilcoxon

For latency and cost, the analyzer applies a $\max(x, 10^{-9})$ floor and takes natural logarithms before running Wilcoxon, and reports the geometric-mean ratio:

$$
\mathrm{GMR}(a, b) = \exp\!\bigg(\frac{1}{n}\sum_{i=1}^{n} (\log b_i - \log a_i)\bigg).
$$

The bootstrap CI is computed on the log-vector differences; the reported interval $[\text{ci\_low}, \text{ci\_high}]$ is on the log scale, and the renderer exponentiates the geometric-mean ratio for display.

### 7.6 Effect sizes

Two effect sizes are reported for every contrast.

Paired Cliff's δ is the difference between the share of pairs where $b > a$ and the share where $b < a$:

$$
\delta = \frac{|\{i : b_i > a_i\}| - |\{i : b_i < a_i\}|}{n} \in [-1, 1].
$$

It is interpreted with the Romano thresholds: $|\delta| < 0.11$ negligible, $0.11 \leq |\delta| < 0.28$ small, $0.28 \leq |\delta| < 0.43$ medium, $|\delta| \geq 0.43$ large.

Paired Cohen's d is computed on the difference vector:

$$
d = \frac{\overline{b - a}}{s_{b - a}}, \quad s_{b - a} = \sqrt{\tfrac{1}{n-1} \sum_i (d_i - \bar d)^2}.
$$

It is interpreted with the conventional 0.2 / 0.5 / 0.8 thresholds. When the diff-vector standard deviation is near zero (constant differences within floating-point noise), the function returns NaN rather than an artificially large d; the renderer prints an em-dash in that cell. Cliff's δ remains informative under those conditions and is the report's primary tier classifier.

### 7.7 Paired bootstrap confidence interval

The point estimate $\overline{b - a}$ is reported with a paired bootstrap CI computed by `paired_bootstrap_diff_ci(a, b, seed=1729, samples=5000)`. The procedure resamples paired *indices* (so case-level pairing is preserved), recomputes the mean difference, and returns the 2.5- and 97.5-percentile means as the CI bounds. The seed is fixed at 1729 per pre-registration; the resample count is five thousand. With fewer than two paired observations the CI collapses to the point estimate.

### 7.8 Benjamini-Hochberg false-discovery-rate control

The confirmatory analysis is restricted to the primary family — two primary endpoints crossed with nine knockout treatments against the `full_agentic` baseline, for eighteen tests under the current code. Across these eighteen raw p-values, Benjamini-Hochberg step-up at $q = 0.05$ is applied (`paired_stats.py:benjamini_hochberg`). The pre-registration's twenty-seven-test figure assumed three primaries; see §7.1 for the discrepancy. With $p_{(1)} \leq p_{(2)} \leq \ldots \leq p_{(m)}$ the sorted raw p-values, the adjusted q-values are:

$$
q_{(i)} = \min_{j \geq i} \min\!\bigg(\frac{p_{(j)} \cdot m}{j},\ 1\bigg),
$$

with the monotonization from the bottom rank up that makes a test's adjusted q never larger than that of any test with a smaller raw p. Subgroup contrasts and within-mode (e.g., `single_pass` vs `single_pass_no_decomposition`) contrasts sit outside the primary family and are reported with raw p only.

### 7.9 Subgroup analysis

For each primary endpoint, the analyzer also constructs paired contrasts within each category and difficulty stratum. Subgroups with fewer than two paired observations are skipped. Subgroup results are flagged as exploratory in the rendered report and explicitly do not contribute to the FDR family. Their purpose is hypothesis generation — for example, a knockout whose primary-endpoint effect is concentrated on `table_lookup` cases motivates a follow-up study on table-aware retrieval.

### 7.10 Pre-registered hypotheses

For each primary endpoint $E \in \{\text{answer\_accuracy}, \text{strict\_recall\_at\_10}\}$ (and additionally `expected_contains` under the pre-registration; see §7.1), the directional alternative is that the baseline outperforms the knockout:

| Hyp. | Contrast                                                  | Isolates                              |
|------|-----------------------------------------------------------|---------------------------------------|
| H1   | `full_agentic` > `full_agentic_no_hyde`                   | HyDE                                  |
| H2   | `full_agentic` > `full_agentic_no_reranker`               | Reranker                              |
| H3   | `full_agentic` > `full_agentic_no_hyde_no_reranker`       | HyDE × Reranker interaction           |
| H4   | `full_agentic` > `single_pass`                            | Agentic tool loop                     |
| H5   | `full_agentic` > `single_pass_semantic_only`              | Lexical channel                       |
| H6   | `full_agentic` > `single_pass_lexical_only`               | Semantic channel                      |
| H7   | `full_agentic` > `single_pass_no_reranker`                | Reranker outside agent loop           |
| H8   | `full_agentic` > `single_pass_no_decomposition`           | Query decomposition                   |
| H9   | `full_agentic` > `llm_only`                               | Retrieval-free floor (sanity check)   |

H9 is a sanity check: if the retrieval-free arm does not yield the largest negative effect across all primaries, the run is treated as suspect and reviewed for ingestion or pipeline regressions before the rest of the contrasts are interpreted.

---

## 8. Reporting artifacts

### 8.1 AblationReport persistence

The analyzer returns an `AblationReport` dataclass holding the baseline name, the variant list, the primary and secondary endpoint lists, the flat list of `PairResult` entries (one per metric × contrast × subgroup), the subgroup-grouped results, the case count, the per-pair excluded-case counts, the methodology footer, and the pairing-skew block. The runner serializes this dataclass to a JSONB-safe dict (replacing non-finite floats with `None`, since Postgres JSONB rejects bare `NaN` or `Infinity`) and writes it to `EvalRun.metrics.ablation`. The serialized report is therefore retrievable through the API without invoking the analyzer on demand.

### 8.2 Markdown rendering

`render_markdown(report)` produces a six-section markdown report: a headline table of primary-endpoint contrasts with adjusted q-values; per-endpoint forest plots; a secondary-endpoint table with raw p-values and Cliff's δ tiers; a latency-and-cost geometric-mean-ratio table; a subgroup table flagged as exploratory; and a methodology footer carrying the case count, bootstrap seed, sample count, FDR family size and threshold, and a one-paragraph description of the test choices.

### 8.3 Forest-plot rendering

The forest-plot renderer draws each contrast on a fixed-width axis, with brackets `[` and `]` at the CI bounds, dashes filling the interval, an asterisk at the point estimate, and a vertical bar `|` at zero when the axis straddles it. A schematic example for one primary endpoint:

```
answer_accuracy (baseline = `full_agentic`)

llm_only                       [--*------------|------]   Δ=-0.421  q=<0.001
single_pass_lexical_only          [-----*--|---]          Δ=-0.180  q=0.014
full_agentic_no_reranker             [---*|--]            Δ=-0.097  q=0.031
single_pass                              [*|-]            Δ=-0.054  q=0.082
full_agentic_no_hyde                       [|*-]          Δ=+0.011  q=0.612
                            -0.45                +0.05
```

The annotation column on the right carries the point estimate and the FDR-adjusted q-value; the axis labels at the bottom show the CI extent shared across all rows of the plot. The renderer sorts the rows by point estimate so the most negative effect appears at the top.

### 8.4 CSV long-form output

`render_csv(report)` writes a long-form CSV row per metric × baseline × treatment × subgroup combination, with columns for the means, the point estimate, the CI bounds, the test kind, the Wilcoxon W (or McNemar discordance), the raw p-value, the BH-adjusted q-value, Cliff's δ, Cohen's d, a `primary` flag, and the geometric-mean ratio (filled only for log-paired tests). The CSV is intended as the durable data product for downstream meta-analysis or for cross-run comparison.

---

## 9. Power and sensitivity

At $N = 99$ paired observations and $\alpha = 0.05$ one-sided Wilcoxon, the design has approximately eighty-percent power to detect a Cliff's δ around 0.20 — between Romano-small and Romano-medium. After Benjamini-Hochberg adjustment across the running eighteen-test family at $q = 0.05$ (or the pre-registered twenty-seven-test family; see §7.1), the least-significant test in the family is effectively tested at $\alpha \approx 0.05 \cdot k / m$ where $k$ is its sorted rank and $m$ the family size; the minimum detectable effect at eighty-percent power rises to roughly $\delta \approx 0.28\text{–}0.30$ — Romano-medium.

Absence of a significant result at this $N$ is *not* evidence of no effect. Effects with $|\delta| < 0.20$ may be real but under-powered; the CI on the mean paired difference is the primary lens for those cases, and a CI that excludes zero with a tight bound around a small effect is more informative than a non-significant p-value. The report's methodology footer reproduces these figures so a reader interpreting a particular contrast knows the floor under which the test is silent.

---

## 10. Threats to validity

### 10.1 Provider non-determinism

The retrieval and generation pipelines call OpenRouter and Z.AI through hosted APIs. Neither provider pins model snapshots; a downstream model revision between an initial run and a replay can shift point estimates without any change in this codebase. The pre-registration acknowledges this and notes that pinning model snapshots is separate hardening work.

### 10.2 Agentic tool-loop variance

The `full_agentic` retrieval mode invokes a Pydantic-AI agent that can issue multiple `retrieve_evidence` tool calls per query, with the decision to retrieve again driven by the model's verification of the evidence so far. Even at temperature zero, the agent can branch on small numerical ties (for example, when two tool-call signatures have indistinguishable expected utilities), producing different trajectories on otherwise identical inputs. This is a known source of intra-arm variance for the agentic variants and contributes to a small amount of replay noise that is not present in `single_pass` variants.

### 10.3 RAGAS judge variance

The RAGAS metrics call the same Z.AI judge model that the answer-text judge uses, but the wrappers expose `temperature` inconsistently across RAGAS versions. The runner does a best-effort temperature-zero set on each candidate attribute path and falls through silently when the attribute does not exist. Residual judge variance is acknowledged and is the reason RAGAS metrics are excluded from the FDR family.

### 10.4 Embedding API revision drift

Embedding APIs may produce slightly different vectors across tokenizer or model revisions. The effect on cosine ranks is empirically small (typically below $10^{-3}$ in similarity score) and is expected to be small at the candidate top-K, but it constitutes a residual source of variance not controlled by the temperature setting.

### 10.5 Judge fallback to substring matching

When `zai_api_key` is unset or mock-providers mode is active, `build_text_judge` returns `None` and the text-scoring path falls back to normalized substring containment. The fallback is paraphrase-intolerant and will assign zero to a semantically-correct answer that does not contain the gold value text verbatim. Confirmatory runs must be conducted with the live judge configured; the substring fallback is only used in the test suite and offline development. The runner records the judge model identifier on every per-claim verdict, so the persisted artifact tells the auditor which scoring path actually ran.

### 10.6 Pairing skew

When one variant crashes on a subset of cases, that subset contributes to the contrast only for the variants that did succeed. The analyzer drops affected cases from the per-pair matrix (`build_paired_matrix` intersects the per-variant case sets); the missing cases are counted in `excluded_cases` and surfaced as `pairing_skew` at the top of the rendered report. A persistent imbalance — for example, an `llm_only` arm that fails on `cross_company_comparison` cases — biases the contrasts and triggers re-running the evaluation. The audit is purely descriptive; no automatic imputation is performed.

### 10.7 Multiple comparisons applied only to primaries

The FDR correction covers only the primary endpoint family. Secondary endpoints (MRR, page F1, citation validity, citation coverage, gold precision and recall, metadata-filter correctness, latency, cost) and subgroup contrasts are reported with raw p-values only. A reader interpreting a secondary contrast as significant should multiply effective $\alpha$ by the number of secondary contrasts they considered; the analyzer surfaces this concern through the explicit "secondary (uncorrected)" header on the secondary table and the "exploratory" header on the subgroup table.

---

## 11. Reproducibility

### 11.1 Seeds and locked artifacts

- Bootstrap seed: 1729, propagated through every random procedure (aggregate CI, paired bootstrap CI). Configurable in `EvalRun.run_config.bootstrap_seed` but defaulted to 1729 across the codebase.
- Variant catalog: `LOCKED_ABLATION_VARIANTS`, exposed as the `locked9` preset in `ABLATION_PRESETS`.
- Gold version: `sec-filings-pdf-v1`, enforced on each `EvalCase` row.

### 11.2 Run-config snapshot

`EvalRun.run_config` is a JSONB column that captures, at run launch, the dataset identifier, the selected case identifiers, the variant specification list (variant name plus override dict), the bootstrap seed, and the benchmark profile. The aggregator and the analyzer recover the variant identity from the per-result rows rather than from the run-config, so a corrupted run-config does not invalidate the analysis; but the snapshot remains the audit trail for "what did we ask the system to do."

### 11.3 Re-running an evaluation

The three command-line entry points are:

```bash
# Seed the eval cases (idempotent upsert on case_key).
uv run --directory backend python -m rag_benchmarking.scripts.seed_eval_cases \
  --dataset <dataset_id> \
  --file backend/eval_cases/sec_filings_v1.yaml

# Run the locked-nine ablation.
uv run --directory backend python -m rag_benchmarking.scripts.run_eval \
  --dataset <dataset_id> \
  --ablation-preset locked9 \
  --output markdown \
  --artifact-dir artifacts/evals

# Run the analyzer offline against a persisted artifact.
uv run --directory backend python -m rag_benchmarking.scripts.analyze_ablation \
  --artifact artifacts/evals/<eval_run_id>.json \
  --baseline full_agentic \
  --out docs/eval/ablation_v1_results.md \
  --csv docs/eval/ablation_v1_results.csv
```

The analyzer is idempotent over a given artifact and seed; the runner is idempotent under the per-case savepoint semantics in §4.2, modulo provider non-determinism (§10.1).

---

## 12. References

### Internal documents

- ADR-0009 *Evaluation Strategy*: `docs/adr/0009-evaluation-strategy.md`.
- ADR-0006 *Agentic Retrieval*: `docs/adr/0006-agentic-retrieval.md`.
- Pre-registration: `docs/eval/ablation_v1_plan.md`.
- Per-case verification log: `docs/eval/sec_filings_v1_verification.md`, `docs/eval/sec_filings_v1_review.md`.
- Implementation report (results): `docs/implementation-report.md`.

### Code anchors

- Retrieval, citation, and parser metrics: `backend/packages/rag-evaluation/rag_evaluation/metrics.py`.
- Answer scoring: `backend/packages/rag-evaluation/rag_evaluation/scoring.py`.
- LLM-as-judge: `backend/packages/rag-evaluation/rag_evaluation/judge.py`.
- Variant catalog: `backend/packages/rag-common/rag_common/eval_variants.py`.
- Aggregation and CI helpers: `backend/packages/rag-common/rag_common/eval_aggregation.py`.
- Paired statistical primitives: `backend/packages/rag-evaluation/rag_evaluation/paired_stats.py`.
- Ablation analyzer: `backend/packages/rag-evaluation/rag_evaluation/ablation_analysis.py`.
- Evaluation orchestrator: `backend/packages/rag-evaluation/rag_evaluation/runner.py`.

### External references

- Wilcoxon, F. (1945). Individual comparisons by ranking methods. *Biometrics Bulletin*, 1 (6), 80–83.
- McNemar, Q. (1947). Note on the sampling error of the difference between correlated proportions or percentages. *Psychometrika*, 12 (2), 153–157.
- Cliff, N. (1993). Dominance statistics: Ordinal analyses to answer ordinal questions. *Psychological Bulletin*, 114 (3), 494–509.
- Romano, J., Kromrey, J. D., Coraggio, J., and Skowronek, J. (2006). Appropriate statistics for ordinal level data. *Annual Meeting of the Florida Association of Institutional Research*.
- Benjamini, Y., and Hochberg, Y. (1995). Controlling the false discovery rate: A practical and powerful approach to multiple testing. *Journal of the Royal Statistical Society B*, 57 (1), 289–300.
- Es, S., James, J., Espinosa-Anke, L., and Schockaert, S. (2024). RAGAS: Automated evaluation of retrieval-augmented generation. *EACL System Demonstrations*.
- Gao, L., Ma, X., Lin, J., and Callan, J. (2023). Precise zero-shot dense retrieval without relevance labels (HyDE). *Annual Meeting of the Association for Computational Linguistics*.
