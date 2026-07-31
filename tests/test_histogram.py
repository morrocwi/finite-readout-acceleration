"""
FRAHistogram(Log): the declared bound must NEVER be violated across a range of
workloads, including a deliberately tight-memory power-law stress case. Also
records the honest limitation found while building this (a linear design lost
badly on power-law data) and its fix (log-scale bucketing).
"""

import math
import random

import pytest

from fra.histogram import FRAHistogram, FRAHistogramLog, ReservoirQuantile


def ground_truth_quantile(xs, p):
    ys = sorted(xs)
    idx = max(0, min(len(ys) - 1, int(math.ceil(p * len(ys))) - 1))
    return ys[idx]


def make_e3_shaped(n=50_000, seed=1):
    rng = random.Random(seed)
    base = [abs(rng.gauss(0.05, 0.01)) for _ in range(int(n * 0.95))]
    tail = [rng.uniform(0.3, 1.5) for _ in range(n - len(base))]
    return base + tail


def make_power_law(n=50_000, seed=2, alpha=2.5, lo=0.01, hi=20.0):
    rng = random.Random(seed)
    xs = []
    for _ in range(n):
        u = rng.random()
        x = lo * (1 - u) ** (-1 / (alpha - 1))
        xs.append(min(x, hi))
    return xs


@pytest.mark.parametrize("data_fn,lo,hi,num_buckets", [
    (make_e3_shaped, 0.0, 1.6, 64),
    (lambda: make_power_law(), 0.0, 20.0, 64),
    (lambda: make_power_law(n=100_000), 0.0, 20.0, 16),
])
def test_linear_declared_bound_never_violated(data_fn, lo, hi, num_buckets):
    data = data_fn()
    hist = FRAHistogram(lo=lo, hi=hi, num_buckets=num_buckets)
    for x in data:
        hist.update(x)
    for p in (0.5, 0.9, 0.99, 0.999):
        true_v = ground_truth_quantile(data, p)
        est, in_range = hist.query(p)
        if in_range:
            assert abs(est - true_v) <= hist.declared_max_error + 1e-9


@pytest.mark.parametrize("data_fn,lo,hi,num_buckets", [
    (lambda: make_power_law(), 0.0, 20.0, 64),
    (lambda: make_power_law(n=100_000), 0.0, 20.0, 16),
])
def test_log_scale_declared_bound_never_violated(data_fn, lo, hi, num_buckets):
    data = data_fn()
    hist = FRAHistogramLog(lo=lo, hi=hi, num_buckets=num_buckets)
    for x in data:
        hist.update(x)
    bound = hist.declared_relative_bound()
    for p in (0.5, 0.9, 0.99, 0.999):
        true_v = ground_truth_quantile(data, p)
        est, in_range = hist.query(p)
        if in_range and est > 0:
            ratio = max(true_v, 1e-12) / est
            assert 1 / bound - 1e-6 <= ratio <= bound + 1e-6


def test_log_scale_recovers_the_quantiles_linear_design_broke():
    """The honest finding from building this: the first (linear) design lost
    badly on power-law data at p50/p90 because uniform bucket width wastes
    resolution across the whole declared range while the data concentrates
    near zero -- the median falls inside one giant bucket. Log-scale buckets
    (the same fix HdrHistogram uses) fix exactly that.

    NOTE ON HONESTY: at the most extreme quantile (p999) linear can, on a
    given random draw, land closer than log-scale by chance (both comfortably
    beat reservoir sampling there) -- that comparison is noisy and is NOT
    asserted here. What IS robust, and asserted, is the dramatic fix at
    p50/p90, where linear's error is a large fraction of the true value and
    log-scale's is not.
    """
    data = make_power_law()
    lin = FRAHistogram(lo=0.0, hi=20.0, num_buckets=64)
    log = FRAHistogramLog(lo=0.0, hi=20.0, num_buckets=64)
    for x in data:
        lin.update(x)
        log.update(x)
    for p in (0.50, 0.90):
        true_v = ground_truth_quantile(data, p)
        lin_est, _ = lin.query(p)
        log_est, _ = log.query(p)
        lin_err = abs(lin_est - true_v)
        log_err = abs(log_est - true_v)
        assert log_err < lin_err, f"expected log-scale to fix p={p}, got lin={lin_err} log={log_err}"


def test_reservoir_has_no_declared_bound_to_check():
    """Documents the actual trade-off: reservoir sampling never violates a
    bound because it never declares one. That is not a strength, it is the
    absence of the property FRAHistogram provides."""
    res = ReservoirQuantile(k=64, seed=0)
    for x in make_power_law():
        res.update(x)
    assert not hasattr(res, "declared_max_error")
    assert not hasattr(res, "declared_relative_bound")
