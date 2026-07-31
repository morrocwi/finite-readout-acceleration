"""
Tier registry enforcement + closures exercised against real numbers from this
project's own engineering log (the ARAYA site measurement, the E3-shaped
latency tail, the E4 key-cardinality trace).
"""

import random

import pytest

import fra


def test_registry_refuses_dr_without_assumption():
    with pytest.raises(ValueError):
        fra.register_closure("bad_closure_no_assumption", fra.DR)


def test_describe_refuses_unregistered_kind():
    with pytest.raises(KeyError):
        fra.describe("not_a_real_kind")


def test_every_registered_closure_has_a_valid_tier():
    for k in fra.kinds():
        d = fra.describe(k)
        assert d["tier"] in (fra.EXACT, fra.DR, fra.FINITE_DIAGNOSTIC)
        if d["tier"] == fra.DR:
            assert d["assumption"], f"{k} is Dr-tier but has no stated assumption"


def test_bottleneck_ceiling_matches_araya_measurement():
    # measured 2026-07-30, read-only ?zz= probe against arayaweddingplanner.com
    total, bootstrap = 1.356, 1.130
    ceiling = fra.bottleneck_ceiling(total, bootstrap)
    assert ceiling == pytest.approx(1.20, abs=0.005)


def test_latency_percentiles_exposes_the_tail_a_mean_hides():
    rng = random.Random(1)
    base = [abs(rng.gauss(0.05, 0.01)) for _ in range(950)]
    tail = [rng.uniform(0.3, 1.5) for _ in range(50)]
    sample = base + tail
    mean = sum(sample) / len(sample)
    pct = fra.latency_percentiles(sample)
    assert pct[0.99] > 3 * mean


def test_injective_key_guard_matches_e4_cardinalities():
    assert fra.injective_key_guard(n=30_000, k=30_000) is True   # Q0/Q1: no accel possible
    assert fra.injective_key_guard(n=30_000, k=13_125) is False  # Q2: accel is possible


def test_error_budget_minutes():
    assert fra.error_budget_minutes(0.999) == pytest.approx(43.2, abs=0.01)


def test_staleness_bound_is_ttl_plus_purge_lag():
    assert fra.staleness_bound_seconds(600, 5) == 605


def test_mmc_wait_time_raises_on_unstable_queue():
    with pytest.raises(ValueError):
        fra.mmc_wait_time(lambda_rate=100, mu_rate=50, c_servers=1)  # rho > 1
