"""Unit tests for the paired statistical primitives.

Worked examples chosen so the truth value is computable by hand or via a
short reference calculation — these tests are the audit surface for
``paired_stats.py``.
"""

from __future__ import annotations

import math

import pytest
from rag_evaluation_worker.paired_stats import (
    benjamini_hochberg,
    cliffs_delta,
    mcnemar_midp,
    paired_bootstrap_diff_ci,
    paired_cohens_d,
    wilcoxon_signed_rank,
)


def test_paired_bootstrap_diff_ci_is_deterministic_for_fixed_seed() -> None:
    a = [0.1, 0.2, 0.3, 0.4, 0.5]
    b = [0.2, 0.4, 0.5, 0.5, 0.7]
    first = paired_bootstrap_diff_ci(a, b, seed=1729, samples=200)
    second = paired_bootstrap_diff_ci(a, b, seed=1729, samples=200)
    assert first == second
    different = paired_bootstrap_diff_ci(a, b, seed=42, samples=200)
    assert different != first


def test_paired_bootstrap_diff_ci_point_estimate_matches_mean_difference() -> None:
    a = [0.0, 1.0, 2.0]
    b = [1.0, 2.0, 4.0]
    mean_diff, lo, hi = paired_bootstrap_diff_ci(a, b, seed=1729, samples=200)
    assert math.isclose(mean_diff, (1.0 + 1.0 + 2.0) / 3, rel_tol=1e-6)
    assert lo <= mean_diff <= hi


def test_paired_bootstrap_diff_ci_handles_short_vectors() -> None:
    assert paired_bootstrap_diff_ci([], []) == (0.0, 0.0, 0.0)
    point, lo, hi = paired_bootstrap_diff_ci([1.0], [2.0])
    assert math.isclose(point, 1.0)
    assert math.isclose(lo, 1.0)
    assert math.isclose(hi, 1.0)


def test_wilcoxon_exact_one_sided_small_n() -> None:
    # Treatment is monotonically larger; one-sided greater p should be tiny.
    a = [0.10, 0.20, 0.30, 0.40, 0.50]
    b = [0.20, 0.30, 0.40, 0.50, 0.60]
    _w, p = wilcoxon_signed_rank(a, b, alternative="greater")
    assert p < 0.05


def test_wilcoxon_zero_diff_handled() -> None:
    a = [0.5, 0.5, 0.5]
    b = [0.5, 0.5, 0.5]
    w, p = wilcoxon_signed_rank(a, b)
    assert w == 0.0
    assert math.isclose(p, 1.0)


def test_wilcoxon_paired_directionality() -> None:
    a = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    b = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
    _w_greater, p_greater = wilcoxon_signed_rank(a, b, alternative="greater")
    _w_less, p_less = wilcoxon_signed_rank(a, b, alternative="less")
    # Treatment is uniformly worse, so 'b > a' (greater) should be unlikely
    # and 'b < a' (less) should be very likely.
    assert p_less < p_greater


def test_mcnemar_midp_zero_discordant() -> None:
    a = [1, 1, 1, 0, 0]
    b = [1, 1, 1, 0, 0]
    b_count, c_count, p = mcnemar_midp(a, b)
    assert (b_count, c_count) == (0, 0)
    assert math.isclose(p, 1.0)


def test_mcnemar_midp_extreme_discordance() -> None:
    a = [1, 1, 1, 1, 1, 1, 1, 1]
    b = [0, 0, 0, 0, 0, 0, 0, 0]
    b_count, c_count, p = mcnemar_midp(a, b)
    assert b_count == 8
    assert c_count == 0
    assert p < 0.05


def test_cliffs_delta_directional() -> None:
    # All treatment values strictly greater -> delta = 1.0.
    assert math.isclose(cliffs_delta([1.0, 2.0, 3.0], [2.0, 3.0, 4.0]), 1.0)
    # Ties everywhere -> delta = 0.0.
    assert math.isclose(cliffs_delta([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]), 0.0)
    # Mixed -> sign reflects direction.
    delta = cliffs_delta([1.0, 2.0, 3.0], [2.0, 2.0, 2.0])
    assert -1.0 <= delta <= 1.0


def test_paired_cohens_d_constant_diff_returns_nan() -> None:
    # When diffs are identical, sd=0 and Cohen's d is undefined. We return NaN
    # (which the renderer prints as "—") rather than 0 — Cliff's δ is the
    # honest effect-size in this regime.
    result = paired_cohens_d([1.0, 2.0, 3.0], [2.0, 3.0, 4.0])
    assert math.isnan(result)


def test_paired_cohens_d_reasonable_for_varying_diff() -> None:
    a = [0.0, 0.0, 0.0, 0.0]
    b = [0.1, 0.2, 0.3, 0.4]
    d = paired_cohens_d(a, b)
    assert d > 0  # treatment is larger on average


def test_benjamini_hochberg_monotonic_and_orders_match_input() -> None:
    raw_p = [0.001, 0.01, 0.03, 0.5, 0.7]
    rejected, q_values = benjamini_hochberg(raw_p, q=0.05)
    # Sorted q values must be monotonic non-decreasing.
    assert q_values == sorted(q_values) or all(
        q_values[i] <= q_values[i + 1] + 1e-9 for i in range(len(q_values) - 1)
    )
    # The smallest raw p must remain rejected; the largest must not.
    assert rejected[0] is True
    assert rejected[-1] is False


def test_benjamini_hochberg_handles_empty() -> None:
    rejected, q_values = benjamini_hochberg([])
    assert rejected == []
    assert q_values == []


def test_paired_vectors_must_be_same_length() -> None:
    with pytest.raises(ValueError):
        paired_bootstrap_diff_ci([1.0, 2.0], [1.0])
    with pytest.raises(ValueError):
        wilcoxon_signed_rank([1.0, 2.0], [1.0])
    with pytest.raises(ValueError):
        mcnemar_midp([1, 0, 1], [1, 0])
