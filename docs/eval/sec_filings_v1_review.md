# `sec_filings_v1` eval set validation review

## Executive summary

The 63 hand-curated eval cases in `backend/eval_cases/sec_filings_v1.yaml` were audited against the underlying PDF corpus in `sec_filings_pdf/`. **Accuracy is clean:** programmatic re-verification (see `rag_benchmarking.scripts.verify_eval_cases`) confirms every numeric value, evidence-text quotation, page number, and filing date in the original set matches the cited PDF page, with one exception that has been corrected. **Coverage was thin:** 10 of 50 tickers, 1 substantive 10-Q case, and 2 metadata-only 8-K cases.

To address the coverage gap we extended the set to **99 cases** (36 new), bringing ticker coverage to **26 / 50** (52%) and adding the first content-bearing 10-Q/8-K cases, the first pharma / energy / retail / telecom / industrial / non-GS-megabank cases, the first risk-factor and MD&A-narrative cases, and edge cases for period disambiguation, footnote-dependent values, and missing-filing handling.

All 99 cases pass:
- `rag_benchmarking.scripts.verify_eval_cases` (page-level PDF content check)
- `rag_benchmarking.scripts.seed_eval_cases.load_cases` (pydantic schema validation)

## Verification methodology

A new CLI script, `backend/rag_benchmarking/scripts/verify_eval_cases.py`, loads the YAML and for every case:
1. Resolves `expected_evidence[].(ticker, form_type, filing_date)` to a PDF under `sec_filings_pdf/`.
2. Confirms the cited `page_number` exists.
3. Extracts the page text via `pypdf`.
4. Confirms every `evidence_text` substring appears on the page (whitespace- and ligature-tolerant; `ﬁrst`/`first` both match).
5. Confirms every `expected_values[].value_numeric` appears on at least one cited page, with the case's `tolerance_abs`/`tolerance_pct`, accepting unit equivalents (16.6 billion = 16,600 million; `$`-prefixed numbers count as million/billion/dollar when the column header sets the unit).
6. Confirms every `expected_values[].value_text` appears either on a cited page (whitespace-permissive, also tries the space-stripped form) or in a PDF filename (for `YYYY-MM-DD` date answers).
7. For `latest_filing`-tagged cases, confirms the cited PDF is genuinely the newest of its `(ticker, form_type)` in the corpus.
8. Computed values - comparison winners (`higher_company`, `highest_company`, etc.) and derived ratios (`*_pct`, `*_ratio`, `*_yoy_growth`, ...) - are tracked as informational notes rather than failures, since the scorer in `rag_evaluation_worker.scoring` only matches them against the agent's answer text.

The verifier mirrors `_NUMBER_RE` / `_unit_matches` / `_numeric_tolerance` from `backend/packages/rag-evaluation-worker/rag_evaluation_worker/scoring.py:16` so what the verifier accepts is a superset of what the scorer would accept.

## Findings on the original 63 cases

### Accuracy (spot-check + programmatic re-verification)

All numeric values, page numbers, filing dates, and evidence-text quotations were verified against the corpus. Spot-checks covered AAPL / MSFT / NVDA / AMZN / META / GOOG / AMD / JPM / BAC / TSLA pages from the 10-K cases and all `latest_filing` filing-date metadata - 30+ assertions all passed verbatim.

**One real bug found and fixed**: `semiconductor_data_center_ai_demand_2025` previously cited NVDA 10-K p.67 alone (which contains "Data Center revenue for fiscal year 2026 was up 68%" but not the absolute $193,737M figure). The absolute figure is on NVDA 10-K p.125 (Revenue by End Market table). Without p.125 in the evidence list, a perfect agent would still need the second hop to support the numeric answer. Fix: added p.125 to `expected_citations` and `expected_evidence`. After the fix, the verifier passes the case cleanly.

### Coverage gaps in the original set

| Dimension | Original (63 cases) | Notes |
| --- | --- | --- |
| Tickers covered | **10 / 50** | AAPL, AMD, AMZN, BAC, GOOG, JPM, META, MSFT, NVDA, TSLA |
| Form types in `expected_evidence` | 10-K: 71 · 10-Q: 1 · 8-K: 2 | All 10-Q/8-K cases were metadata-only (filing-date lookups), zero content questions |
| Sectors absent | Pharma, energy, retail/consumer, telecom, industrials, most semis, most banks, software-other | Only tech megacap + 2 megabanks |
| Question shape | ~57 of 63 numeric extraction | No risk-factor / MD&A-narrative / accounting-policy / legal-proceedings questions |
| Edge cases present | Future-period (3), out-of-corpus (1), partial-disclosure (1), refusals (5) | Good range for these |
| Edge cases missing | Period disambiguation, footnote-dependent values, cross-period within one filing, narrow line items, missing-filing in corpus | None addressed |

### Minor consistency observations (applied)

- Switched three `latest_*_filing_date` cases from `answer_type: multi_part` (with a single value) to `answer_type: text` for cleaner semantics. (Schema in `rag_common/schemas.py:150` allows `text`.)
- `.DS_Store` was already implicitly ignored by `.gitignore` (the whole `sec_filings_pdf` folder is gitignored); no fix needed.

### Dataset-side observations (not eval bugs, but worth knowing)

- **MCD** has only one PDF (an 8-K). No 10-K or 10-Q is in the corpus. A new negative-coverage case (`mcd_2025_10k_total_revenue_insufficient`) now tests that the agent recognises this gap.
- **NFLX** has 5 of the expected 7 filings - no Q1 2025 10-Q. A negative case (`nflx_q1_2025_revenue_insufficient`) now covers it.
- **WFC**'s 10-K PDF is only 36 pages (looks truncated or a cover-only document); no detailed financials are extractable. We routed WFC questions through other cases (BAC/JPM) rather than relying on the incomplete file.
- The 8-K PDFs are predominantly cover sheets that reference but do not embed the press-release exhibits (Exhibit 99.1). Content-bearing 8-K cases therefore target what *is* in the cover sheet (reporting period, exhibit title, item type) plus the one outlier (PM 8-K filed 2026-03-13) that does include a substantive segment-realignment disclosure on p.6.

## Extension: 36 new cases

| Group | Count | Key cases |
| --- | --- | --- |
| 10-Q content | 6 | MSFT/AAPL/NVDA/JPM/TSLA/AMZN quarterly revenue or segment numbers |
| 8-K content | 4 | AAPL/NVDA/TSLA cover-sheet metadata + PM segment-realignment narrative |
| Sector coverage | 16 | LLY, MRK, JNJ, UNH (pharma); XOM, CVX (energy); WMT, COST, KO (retail/consumer); T, VZ (telecom); GS (other bank); CAT (industrial); AVGO, INTC (semis); plus a 6-way cross-sector revenue ranking |
| Qualitative / narrative | 4 | AAPL supply-chain risk factor, NVDA H20 export charge, META advertising drivers, MSFT AI-infrastructure cost commentary |
| Edge cases | 4 | AAPL Q1 FY26 vs FY25 period-disambiguation, NVDA FY25+FY26 in one 10-K, META EPS+capex bullet pair, TSLA regulatory-credits narrow line item |
| Negative coverage | 2 | MCD has no 10-K · NFLX has no Q1 2025 10-Q |

All new cases carry `verification_status: verified`, `verified_by: validation-extension-v1`, `verified_at: 2026-05-15T00:00:00Z`, `gold_version: sec-filings-pdf-v1`, and pass the programmatic verifier.

## Coverage after extension

| Dimension | Original | After extension |
| --- | --- | --- |
| Total cases | 63 | **99** |
| Tickers covered | 10 / 50 (20%) | **26 / 50 (52%)** |
| 10-K content cases | ~60 | ~85 |
| 10-Q content cases | 0 (metadata only) | **6** |
| 8-K content cases | 0 (metadata only) | **4** (incl. 1 substantive narrative) |
| Pharma / energy / retail / telecom / non-megabank / industrial cases | 0 | **15** |
| Risk-factor / MD&A-narrative cases | 0 | **4** |
| Period-disambiguation / cross-period / footnote cases | 0 | **4** |
| Negative coverage (missing-filing) cases | 0 | **2** |

Tickers still uncovered (24): ABBV, AMAT, AXP, BRK-B, CSCO, GE, GEV, HD, IBM, LRCX, MA, MCD (negative only), MS, MU, NFLX (negative only), ORCL, PEP, PG, PLTR, RTX, TMUS, TXN, V, WFC. A future v2 extension could close these with one numeric-lookup case each.

## How to reproduce

```bash
# 1. Schema validation (parses every case via SeedEvalCase pydantic)
uv run --directory backend python -m rag_benchmarking.scripts.seed_eval_cases \
  --dataset _verify \
  --file backend/eval_cases/sec_filings_v1.yaml \
  --dry-run

# 2. Programmatic PDF re-verification (writes a per-case PASS/FAIL report)
uv run --directory backend python -m rag_benchmarking.scripts.verify_eval_cases \
  --yaml backend/eval_cases/sec_filings_v1.yaml \
  --pdf-root sec_filings_pdf \
  --out docs/eval/sec_filings_v1_verification.md
```

The verifier exits non-zero if any case fails. After the changes in this audit it should report `cases=99 failed=0`.

## Recommendations for future iterations

1. **Close the remaining 24-ticker coverage gap** with one numeric-lookup case per uncovered ticker (template: `<ticker>_2025_<top_line>_millions`). This is the highest-yield extension.
2. **Add a "v2 narrative" block** that exercises legal-proceedings, accounting-policy and forward-looking-language passages; these are differential vs numeric extraction.
3. **Add multi-page table cases** (e.g. JPM segment results that span p.108-p.110) to test the chunker's table boundary handling.
4. **Add restated / non-GAAP cases** (e.g. PM 2026-03-13 recast historicals, AMD GAAP vs non-GAAP reconciliations) to pressure-test which version the retriever surfaces.
5. **Consider a `derived: true` field on `expected_values`** to make computed values (comparison winners, ratios) explicit at the schema level, so future verifiers can distinguish extraction targets from synthesis targets without label-name heuristics.
