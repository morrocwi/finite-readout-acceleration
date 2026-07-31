"""
fra — Finite Readout Acceleration, an engineering library and companion to
Lahtee (2026), "What a Finite Readout Need Not Compute".

See README.md for the full picture (what this is, what it is not, and the
tier discipline every closure/audit declares). Quick orientation:

    import fra
    fra.kinds()                 # every registered closure/audit + its tier
    fra.describe("break_even_alpha")

    model = fra.CostModel(c_f=1.34, c_o=0.137)
    model.break_even_alpha()    # 0.898 -- see README's ARAYA measurement

    from fra.cache import BEVECache, simulate
    from fra.histogram import FRAHistogram, FRAHistogramLog
"""

from .core import (
    # tier registry
    EXACT,
    DR,
    FINITE_DIAGNOSTIC,
    CLOSURE_TIERS,
    register_closure,
    kinds,
    describe,
    # cost model / closures
    CostModel,
    injective_key_guard,
    latency_percentiles,
    error_budget_minutes,
    staleness_bound_seconds,
    payload_budget_seconds,
    bottleneck_ceiling,
    littles_law_L,
    mmc_wait_time,
    index_selectivity_posthoc,
    index_selectivity_predictive,
    # key safety
    SafetyReport,
    audit_key_safety,
    # certificate
    Certificate,
    lipschitz_delta,
    empirical_lipschitz,
    # guard + accelerator
    GuardStats,
    BreakEvenGuard,
    FiniteReadoutAccelerator,
    # Layer B audits
    AuditFinding,
    php_parse_gate,
    route_smoke_test,
    require_guard_audit,
    atomic_deploy_audit,
    frozen_data_audit,
    MeasuredValue,
    metric_staleness_check,
    silent_zero_collapse_audit,
    # helper
    timed,
)

__version__ = "0.1.0"

__all__ = [
    "EXACT", "DR", "FINITE_DIAGNOSTIC", "CLOSURE_TIERS",
    "register_closure", "kinds", "describe",
    "CostModel", "injective_key_guard", "latency_percentiles",
    "error_budget_minutes", "staleness_bound_seconds", "payload_budget_seconds",
    "bottleneck_ceiling", "littles_law_L", "mmc_wait_time",
    "index_selectivity_posthoc", "index_selectivity_predictive",
    "SafetyReport", "audit_key_safety",
    "Certificate", "lipschitz_delta", "empirical_lipschitz",
    "GuardStats", "BreakEvenGuard", "FiniteReadoutAccelerator",
    "AuditFinding", "php_parse_gate", "route_smoke_test", "require_guard_audit",
    "atomic_deploy_audit", "frozen_data_audit", "MeasuredValue",
    "metric_staleness_check", "silent_zero_collapse_audit",
    "timed",
]
