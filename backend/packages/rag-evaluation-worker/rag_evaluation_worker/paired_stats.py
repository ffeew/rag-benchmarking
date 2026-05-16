"""Paired statistical primitives for the ablation analyzer.

Stdlib + numpy only (no scipy). Each function is intentionally small enough to
audit by eye; correctness is asserted against worked examples in
``backend/tests/test_paired_stats.py``.

Conventions:
- ``a`` is the baseline arm, ``b`` is the treatment arm; all functions expect
  paired vectors aligned on the same case_id ordering.
- ``alternative`` follows the SciPy convention: ``"two-sided"`` |
  ``"greater"`` (test that b > a) | ``"less"``.
- Bootstrap and any internal RNG state is seeded via the ``seed`` arg so the
  same artifact + seed always produces the same numbers.
"""

from __future__ import annotations

import math
import random
from itertools import product
from typing import Literal

import numpy as np

Alternative = Literal["two-sided", "greater", "less"]


def _to_float_pair(a: list[float], b: list[float]) -> tuple[list[float], list[float]]:
    if len(a) != len(b):
        raise ValueError(f"paired vectors must have equal length; got {len(a)} vs {len(b)}")
    return [float(x) for x in a], [float(x) for x in b]


def paired_bootstrap_diff_ci(
    a: list[float],
    b: list[float],
    *,
    seed: int = 1729,
    samples: int = 5000,
    confidence: float = 0.95,
) -> tuple[float, float, float]:
    """Paired bootstrap of ``mean(b - a)`` with a percentile CI.

    Samples paired indices (so case-level pairing is preserved). Returns
    ``(mean_diff, ci_low, ci_high)``. With fewer than 2 pairs, the CI
    collapses to the point estimate.
    """

    a_vals, b_vals = _to_float_pair(a, b)
    n = len(a_vals)
    if n == 0:
        return 0.0, 0.0, 0.0
    diffs = [b_vals[i] - a_vals[i] for i in range(n)]
    mean_diff = sum(diffs) / n
    if n < 2:
        return mean_diff, mean_diff, mean_diff
    rng = random.Random(seed)  # noqa: S311 - deterministic resampling, not security-sensitive
    means: list[float] = []
    for _ in range(samples):
        draw_sum = 0.0
        for _ in range(n):
            draw_sum += diffs[rng.randrange(n)]
        means.append(draw_sum / n)
    means.sort()
    alpha = (1.0 - confidence) / 2.0
    lo = means[int(alpha * (len(means) - 1))]
    hi = means[int((1.0 - alpha) * (len(means) - 1))]
    return mean_diff, lo, hi


def _wilcoxon_exact_pvalue(signs: list[int], abs_ranks: list[float], alternative: Alternative) -> float:
    """Exact Wilcoxon p-value via combinatorial enumeration. n must be small."""

    n = len(signs)
    if n == 0:
        return 1.0
    observed_w_plus = sum(rank for sign, rank in zip(signs, abs_ranks, strict=True) if sign > 0)
    total = 0
    ge_observed = 0
    le_observed = 0
    for assignment in product((1, -1), repeat=n):
        w_plus = sum(rank for sign, rank in zip(assignment, abs_ranks, strict=True) if sign > 0)
        total += 1
        if w_plus >= observed_w_plus:
            ge_observed += 1
        if w_plus <= observed_w_plus:
            le_observed += 1
    if alternative == "greater":
        return ge_observed / total
    if alternative == "less":
        return le_observed / total
    return min(1.0, 2.0 * min(ge_observed, le_observed) / total)


def _midrank(values: list[float]) -> list[float]:
    """Return midranks (ties get the mean of the rank span they cover)."""

    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(values):
        j = i
        while j + 1 < len(values) and values[order[j + 1]] == values[order[i]]:
            j += 1
        mid = (i + j) / 2.0 + 1.0  # 1-based midrank
        for k in range(i, j + 1):
            ranks[order[k]] = mid
        i = j + 1
    return ranks


def wilcoxon_signed_rank(
    a: list[float],
    b: list[float],
    *,
    alternative: Alternative = "two-sided",
    zero_method: Literal["wilcox", "pratt"] = "wilcox",
) -> tuple[float, float]:
    """Continuity-corrected Wilcoxon signed-rank test.

    Returns ``(W, p_value)`` where W is the smaller of W+/W- (matches scipy's
    classic two-sided definition). For ``n <= 25`` and no ties, an exact
    enumeration is used; otherwise we use the normal approximation with a
    continuity correction.

    ``zero_method`` controls how exact-zero differences are handled:
    ``"wilcox"`` drops them (default; matches scipy's pre-1.9 behavior),
    ``"pratt"`` ranks them but excludes from the sum.
    """

    a_vals, b_vals = _to_float_pair(a, b)
    diffs = [b_vals[i] - a_vals[i] for i in range(len(a_vals))]
    if zero_method == "wilcox":
        diffs = [d for d in diffs if d != 0.0]
    n = len(diffs)
    if n == 0:
        return 0.0, 1.0
    abs_diffs = [abs(d) for d in diffs]
    ranks = _midrank(abs_diffs)
    signs = [1 if d > 0 else (-1 if d < 0 else 0) for d in diffs]
    w_plus = sum(rank for sign, rank in zip(signs, ranks, strict=True) if sign > 0)
    w_minus = sum(rank for sign, rank in zip(signs, ranks, strict=True) if sign < 0)
    w = min(w_plus, w_minus)

    has_ties = len(set(abs_diffs)) != len(abs_diffs)
    if n <= 25 and not has_ties:
        p = _wilcoxon_exact_pvalue(signs, ranks, alternative)
        return w, p

    mean_w = n * (n + 1) / 4.0
    tie_counts: dict[float, int] = {}
    for rank in abs_diffs:
        tie_counts[rank] = tie_counts.get(rank, 0) + 1
    tie_correction = sum(t**3 - t for t in tie_counts.values()) / 48.0
    var_w = n * (n + 1) * (2 * n + 1) / 24.0 - tie_correction
    if var_w <= 0:
        return w, 1.0
    if alternative == "greater":
        z = (w_plus - mean_w - 0.5) / math.sqrt(var_w)
        p = 1.0 - _normal_cdf(z)
    elif alternative == "less":
        z = (w_plus - mean_w + 0.5) / math.sqrt(var_w)
        p = _normal_cdf(z)
    else:
        diff = w_plus - mean_w
        z_num = diff - 0.5 * (1.0 if diff > 0 else -1.0 if diff < 0 else 0.0)
        z = z_num / math.sqrt(var_w)
        p = 2.0 * (1.0 - _normal_cdf(abs(z)))
    return w, max(0.0, min(1.0, p))


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def mcnemar_midp(a_bin: list[int], b_bin: list[int]) -> tuple[int, int, float]:
    """Exact McNemar test with mid-P correction on discordant pairs.

    Returns ``(b_count, c_count, p_value)`` where ``b_count`` is the number of
    cases the baseline got right but the treatment got wrong (a=1, b=0), and
    ``c_count`` is the inverse. Mid-P is the conventional less-conservative
    variant when discordant pairs are few.
    """

    if len(a_bin) != len(b_bin):
        raise ValueError("paired binary vectors must have equal length")
    b_count = sum(1 for ai, bi in zip(a_bin, b_bin, strict=True) if ai == 1 and bi == 0)
    c_count = sum(1 for ai, bi in zip(a_bin, b_bin, strict=True) if ai == 0 and bi == 1)
    n = b_count + c_count
    if n == 0:
        return 0, 0, 1.0
    k = min(b_count, c_count)
    # P(X = i) under H0 of equal split = C(n, i) * 0.5^n
    cumulative = sum(math.comb(n, i) for i in range(k)) * (0.5**n)
    point = math.comb(n, k) * (0.5**n)
    p_one = cumulative + 0.5 * point  # mid-P one-tailed
    p_two = min(1.0, 2.0 * p_one)
    return b_count, c_count, p_two


def cliffs_delta(a: list[float], b: list[float]) -> float:
    """Paired Cliff's delta = (#{b>a} - #{b<a}) / n.

    Range is [-1, 1]; sign indicates direction (positive = treatment > baseline).
    Reported thresholds (Romano 2006): |delta| < 0.11 negligible · 0.11-0.28
    small · 0.28-0.43 medium · >= 0.43 large.
    """

    a_vals, b_vals = _to_float_pair(a, b)
    if not a_vals:
        return 0.0
    pos = sum(1 for ai, bi in zip(a_vals, b_vals, strict=True) if bi > ai)
    neg = sum(1 for ai, bi in zip(a_vals, b_vals, strict=True) if bi < ai)
    return (pos - neg) / len(a_vals)


def paired_cohens_d(a: list[float], b: list[float]) -> float:
    """Cohen's d on the diff vector: mean(b - a) / sd(b - a, ddof=1).

    Returns NaN when the diff vector has near-zero variance (constant difference);
    the magnitude is well-defined but d is conventionally undefined and would
    otherwise blow up to ±1e15 due to FP noise. Cliff's δ remains informative in
    that regime — that's the metric the report leans on for tier classification.
    """

    a_vals, b_vals = _to_float_pair(a, b)
    if len(a_vals) < 2:
        return float("nan")
    diffs = np.array([b_vals[i] - a_vals[i] for i in range(len(a_vals))], dtype=float)
    sd = float(np.std(diffs, ddof=1))
    mean_d = float(np.mean(diffs))
    # Treat sd ≤ 1e-9 as "constant" (FP noise around zero). NaN propagates and
    # the renderer prints "—".
    scale = max(abs(mean_d), 1.0)
    if sd <= 1e-9 * scale:
        return float("nan")
    return mean_d / sd


def benjamini_hochberg(p_values: list[float], q: float = 0.05) -> tuple[list[bool], list[float]]:
    """Benjamini-Hochberg FDR step-up.

    Returns ``(rejected_flags, bh_adjusted_q_values)`` in the original order.
    Adjusted q-values are monotonised from the bottom rank up (the standard
    correction); a test with raw p larger than its neighbor still receives the
    neighbor's adjusted q.
    """

    n = len(p_values)
    if n == 0:
        return [], []
    indexed = sorted(enumerate(p_values), key=lambda item: item[1])
    adjusted = [0.0] * n
    prev = 1.0
    for rank in range(n - 1, -1, -1):
        original_index, raw_p = indexed[rank]
        candidate = raw_p * n / (rank + 1)
        prev = min(prev, candidate)
        adjusted[original_index] = min(prev, 1.0)
    rejected = [adjusted[i] <= q for i in range(n)]
    return rejected, adjusted


__all__ = [
    "benjamini_hochberg",
    "cliffs_delta",
    "mcnemar_midp",
    "paired_bootstrap_diff_ci",
    "paired_cohens_d",
    "wilcoxon_signed_rank",
]
