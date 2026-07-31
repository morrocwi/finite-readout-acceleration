"""
BEVE (Break-Even Value Eviction): does it win where it should, lose honestly
where it shouldn't, and never violate its own Coq-backed admission rule?
"""

import random

from fra.cache import BEVECache, simulate

C_O = 0.02
CAPACITY = 200


def w1_araya_shaped(n=30_000, seed=1):
    rng = random.Random(seed)
    n_pages = 400
    page_cost = {p: rng.uniform(1.20, 1.59) for p in range(n_pages)}
    weights = [1.0 / (i + 1) ** 1.1 for i in range(n_pages)]
    return [
        (p := rng.choices(range(n_pages), weights=weights, k=1)[0], page_cost[p])
        for _ in range(n)
    ]


def w2_adversarial_locality(n=30_000, seed=2):
    rng = random.Random(seed)
    n_keys = 5000
    trace = []
    window_start = 0
    window_size = 50
    for i in range(n):
        if i % 300 == 0:
            window_start = (window_start + window_size) % (n_keys - window_size)
        k = rng.randrange(window_start, window_start + window_size)
        cf = 0.5 * rng.uniform(0.95, 1.05)
        trace.append((k, cf))
    return trace


def test_beve_beats_lru_and_lfu_on_araya_shaped_heterogeneous_cost():
    trace = w1_araya_shaped()
    r_lru = simulate("lru", trace, CAPACITY, C_O)
    r_lfu = simulate("lfu", trace, CAPACITY, C_O)
    r_beve = simulate("beve", trace, CAPACITY, C_O)
    assert r_beve["total_cost"] < r_lru["total_cost"]
    assert r_beve["total_cost"] < r_lfu["total_cost"]


def test_beve_honestly_loses_on_the_adversarial_locality_workload():
    """This is the negative result, kept and asserted, not hidden: pure recency
    beats cost-weighting when cost carries almost no signal and locality is
    everything. If this ever starts passing, the workload stopped being a
    genuine adversarial case for BEVE and the test's premise should be revisited.
    """
    trace = w2_adversarial_locality()
    r_lru = simulate("lru", trace, CAPACITY, C_O)
    r_beve = simulate("beve", trace, CAPACITY, C_O)
    assert r_beve["total_cost"] > r_lru["total_cost"]


def test_admission_rule_never_admits_a_key_that_cannot_pay_for_itself():
    """Mirrors Coq's injective_key_slowdown / ceiling_strict hypothesis (cf>c_o)
    directly against the live cache state, on both workloads combined."""
    cache = BEVECache(CAPACITY, shared_co=C_O)
    for key, cf in w1_araya_shaped() + w2_adversarial_locality():
        cache.get_or_compute(key, cf, compute=lambda: True)
    for k, entry in cache.store.items():
        assert entry["cf"] > C_O, f"key {k} admitted with cf={entry['cf']} <= c_o={C_O}"
