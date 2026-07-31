"""
Phase 0 kill-or-confirm test (2026-07-30): does audit_key_safety's coverage
precondition actually catch an E4-shaped permission leak on a trace that never
exercised it, and does it correctly stop trusting a PASS that hasn't earned it?
"""

import random

import fra

SEED = 20260731
SERVICES_AT_TRACE_CAPTURE = ["nikah", "venue", "package", "academy", "certificate"]
ROLES = ["guest", "member"]
DECLARED_CELLS = [(s, r) for s in SERVICES_AT_TRACE_CAPTURE + ["vip-consult"] for r in ROLES]


def readout(r):
    return (r["province"], r["lang"], r["service"], r["day"], r["role"] == "guest")


def leaky_key(r):
    if r["service"] == "vip-consult":
        return (r["province"], r["lang"], r["service"], r["day"])  # bug: no role
    return (r["province"], r["lang"], r["service"], r["day"], r["role"])


def coverage_key(r):
    return (r["service"], r["role"])


def make_trace(n, services, roles=ROLES, seed=0):
    g = random.Random(seed)
    provinces = [f"p{i:02d}" for i in range(20)]
    return [
        {
            "province": g.choice(provinces),
            "lang": g.choice(["th", "en"]),
            "service": g.choice(services),
            "day": g.randrange(1, 30),
            "role": g.choice(roles),
        }
        for _ in range(n)
    ]


def test_old_trace_produces_false_pass_but_is_flagged_uncertified():
    old_trace = make_trace(20_000, SERVICES_AT_TRACE_CAPTURE, seed=1)
    sr = fra.audit_key_safety(
        old_trace, leaky_key, readout,
        coverage_key=coverage_key, declared_cells=DECLARED_CELLS,
    )
    assert sr.exact_safe is True          # no violation OBSERVED (the leak was never hit)
    assert sr.coverage_gaps               # but coverage is incomplete
    assert sr.trustworthy_pass is False   # so the report REFUSES to certify the PASS


def test_production_trace_catches_the_leak_with_a_concrete_example():
    old_trace = make_trace(20_000, SERVICES_AT_TRACE_CAPTURE, seed=1)
    new_traffic = make_trace(3_000, ["vip-consult"], seed=2)
    prod_trace = old_trace + new_traffic
    sr = fra.audit_key_safety(
        prod_trace, leaky_key, readout,
        coverage_key=coverage_key, declared_cells=DECLARED_CELLS,
    )
    assert sr.exact_safe is False
    assert sr.trustworthy_pass is True  # an UNSAFE verdict needs no coverage argument
    assert sr.violating_keys
    assert not sr.coverage_gaps  # vip-consult x guest/member now exercised


def test_safe_key_with_full_coverage_is_trustworthy():
    trace = make_trace(20_000, SERVICES_AT_TRACE_CAPTURE + ["vip-consult"], seed=3)

    def safe_key(r):
        return (r["province"], r["lang"], r["service"], r["day"], r["role"])

    sr = fra.audit_key_safety(
        trace, safe_key, readout,
        coverage_key=coverage_key, declared_cells=DECLARED_CELLS,
    )
    assert sr.exact_safe is True
    assert not sr.coverage_gaps
    assert sr.trustworthy_pass is True


def test_coverage_key_and_declared_cells_must_both_be_given_or_neither():
    trace = make_trace(100, SERVICES_AT_TRACE_CAPTURE, seed=4)
    try:
        fra.audit_key_safety(trace, leaky_key, readout, coverage_key=coverage_key)
        assert False, "should have raised ValueError for a half-declared coverage check"
    except ValueError:
        pass
