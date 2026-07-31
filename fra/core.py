"""
fra.py — Finite Readout Acceleration, as an engineering library.

Implements the paper's criterion (Lahtee 2026, "What a Finite Readout Need Not Compute")
plus the three gaps the IDM review flagged:

  G1  Prop 1 restated as a STRICT FINITE BOUND (S_Q < c_f/c_o for every finite trace),
      no limit, no reals — see `max_speedup_ceiling`.
  G2  Error is certified by MAX, never by MEAN. `Certificate` refuses to report a
      guarantee it did not measure, and separates:
        declared  (delta from Corollary 1: L * r_Q — a real bound)
        observed  (max over the sampled trace — a finite_diagnostic, NOT a bound)
  G3  `BreakEvenGuard` monitors K_N/N online and disables the quotient when the trace
      drifts past the break-even, instead of silently getting slower.

Plus the tool the paper's Section 10.1 asks for but does not give:
  `audit_key_safety` — turns Definition 1 (ker Q subseteq ker g) into a runnable linter.
  This is what stops a cache key from merging two permission classes. As of Phase 0
  (2026-07-30) it also enforces a coverage precondition: a PASS is only `trustworthy_pass`
  when every declared (role, service, ...) cell was actually exercised by the trace —
  otherwise it is a real, reproducible FALSE PASS (confirmed by phase0_dogfood.py).

TIER DISCIPLINE (added Phase 2, after the ultracode review wf_9075b1cc-9c6 caught the
proposal re-tiering M/M/c correctly while leaving four other closures unflagged next to
it in the same document — not a one-off slip, a pattern). Every closure below is
registered in CLOSURE_TIERS with one of:
  EXACT              arithmetic identity/inequality over Q given measured inputs — no
                     model assumption anywhere in the derivation. `ceiling_strict`,
                     `break_even_iff` etc. are additionally Th_coqc — see formal/.
  DR                 exact GIVEN a declared model assumption (Poisson arrivals,
                     stationarity, column independence, ...) which MUST be surfaced
                     alongside the number, never silently assumed.
  FINITE_DIAGNOSTIC  a measurement or a trace-bounded check — certifies only what was
                     observed, never a universal absence.
`kinds()`/`describe()` mirror idm.kinds()/idm.describe() so the two tools share one
discovery shape; unlike idm, HOLD is available at describe()-time too (see webidm
proposal §"the one hard rule" — describe() must say what is missing, not just solve()).

Everything here is ordinary finite arithmetic over rationals/floats. No continuum is
injected: no limit is taken, no supremum over an infinite family is claimed.
"""

from __future__ import annotations

import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any, Callable, Hashable, Iterable, Sequence


# ----------------------------------------------------------------------------
# 0. Tier registry — the structural fix for "tiered correctly once, forgot four
#    times in the same document". A closure not registered here is a bug, not
#    an oversight: `describe()` refuses to answer for an unregistered kind.
# ----------------------------------------------------------------------------

EXACT = "exact"                    # Q-arithmetic identity/inequality, no model
DR = "Dr"                          # exact UNDER a declared, stated assumption
FINITE_DIAGNOSTIC = "finite_diagnostic"  # a measurement or trace-bounded check

CLOSURE_TIERS: dict[str, dict[str, Any]] = {}


def register_closure(name: str, tier: str, *, assumption: str | None = None,
                      theorem: str | None = None) -> None:
    """Fail-closed registry: a closure MUST declare its tier at definition time.

    assumption: for tier=DR, the model fact that must hold (Poisson arrivals,
      column independence, ...) — required, non-optional, checked below.
    theorem: cross-reference into formal/FRA_Closures.v when Th_coqc-eligible.
    """
    if tier == DR and not assumption:
        raise ValueError(f"{name}: tier=DR requires a stated `assumption`")
    CLOSURE_TIERS[name] = {"tier": tier, "assumption": assumption, "theorem": theorem}


def kinds() -> list[str]:
    return sorted(CLOSURE_TIERS)


def describe(kind: str) -> dict[str, Any]:
    if kind not in CLOSURE_TIERS:
        raise KeyError(f"unknown kind {kind!r} (see kinds()) — HOLD, not a guess")
    return {"kind": kind, **CLOSURE_TIERS[kind]}


# ----------------------------------------------------------------------------
# 1. The cost model  (paper Section 4, Eq 13-20)
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class CostModel:
    """Per-request costs, in any consistent unit (we use seconds).

    c_f  average cost of the expensive computation + readout
    c_o  per-request overhead of key construction + lookup + return
    c_m  additional per-miss insertion / materialisation cost
    """

    c_f: float
    c_o: float
    c_m: float = 0.0

    def break_even_alpha(self) -> float:
        """Max distinct-key ratio K_N/N at which the quotient still pays (Thm 3).

        Returns 0.0 when c_f <= c_o: no collapse rate can ever pay.
        """
        if self.c_f <= self.c_o:
            return 0.0
        return (self.c_f - self.c_o) / (self.c_f + self.c_m)

    def speedup(self, n: int, k: int) -> float:
        """S_Q for a trace of N requests producing K distinct keys (Eq 17)."""
        denom = n * self.c_o + k * (self.c_f + self.c_m)
        return (n * self.c_f) / denom

    def max_speedup_ceiling(self) -> float:
        """G1 — the STRICT ceiling c_f/c_o.

        The paper reaches this via `K_N/N -> 0` (a limit that lands: an injected
        infinity). It is unnecessary. For every finite trace with N >= 1, K >= 1,
        c_m >= 0 the denominator carries a strictly positive K*(c_f+c_m) term, so

            S_Q = N c_f / (N c_o + K(c_f+c_m))  <  N c_f / (N c_o)  =  c_f / c_o

        holds strictly and universally. The ceiling is a refused endpoint: approached,
        never reached. Stronger than the asymptotic statement, and provable over Q.
        """
        return self.c_f / self.c_o

    def exact_ceiling_fraction(self) -> Fraction:
        """The same ceiling over Q, for exact (rational) reasoning."""
        return Fraction(self.c_f).limit_denominator(10**9) / Fraction(
            self.c_o
        ).limit_denominator(10**9)


register_closure("break_even_alpha", EXACT, theorem="break_even_iff")
register_closure("speedup", EXACT, theorem="break_even_iff")
register_closure("max_speedup_ceiling", EXACT, theorem="ceiling_strict")


# ----------------------------------------------------------------------------
# 2. Key-safety audit  (paper Definition 1, Section 10.1) -- the missing linter
#
# TIER: finite_diagnostic, not "decidable". The ultracode review (2026-07-30) and
# the Phase 0 dogfood test (phase0_dogfood.py) confirmed this concretely: a PASS
# (exact_safe=True) certifies only that no violation was OBSERVED in this trace --
# never that none exists. A leak on a code path the trace never exercised (a page
# shipped after the trace was captured, in the dogfood test) produces a real,
# reproducible FALSE PASS. This is not a hypothetical edge case; it was measured.
#
# The fix is not "trust it a little less" -- it is the coverage precondition below,
# shipped as PART of this function, not as an optional separate step. An UNSAFE
# verdict needs no such precondition: a caught violation is trustworthy on its own.
# Only a PASS needs coverage evidence before anyone may rely on it.
# ----------------------------------------------------------------------------

@dataclass
class SafetyReport:
    n_samples: int
    n_keys: int
    exact_safe: bool
    max_observed_gap: float
    violating_keys: list[tuple[Any, Any, Any]] = field(default_factory=list)
    coverage_gaps: list[Hashable] | None = None
    tier: str = "finite_diagnostic"

    @property
    def trustworthy_pass(self) -> bool:
        """Whether a PASS (exact_safe=True) may be relied on as a release gate.

        An UNSAFE verdict is always trustworthy -- a violation was actually
        observed. A PASS is trustworthy ONLY when coverage was declared and is
        complete; a PASS with coverage never declared, or declared and gappy,
        certifies nothing about the cells it never saw.
        """
        if not self.exact_safe:
            return True
        if self.coverage_gaps is None:
            return False
        return len(self.coverage_gaps) == 0

    def __str__(self) -> str:
        if not self.exact_safe:
            head = "*** UNSAFE ***"
        elif self.trustworthy_pass:
            head = "OK (coverage complete)"
        elif self.coverage_gaps is None:
            head = "PASS-BUT-UNCERTIFIED (no coverage declared -- do not trust)"
        else:
            head = f"PASS-BUT-UNCERTIFIED ({len(self.coverage_gaps)} cell(s) untested -- do not trust)"
        return (
            f"[{self.tier}] {head}  samples={self.n_samples} keys={self.n_keys} "
            f"max_gap={self.max_observed_gap:.6g} violations={len(self.violating_keys)}"
        )


def audit_key_safety(
    samples: Iterable[Any],
    key_fn: Callable[[Any], Hashable],
    readout_fn: Callable[[Any], Any],
    distance: Callable[[Any, Any], float] | None = None,
    max_report: int = 5,
    coverage_key: Callable[[Any], Hashable] | None = None,
    declared_cells: Iterable[Hashable] | None = None,
) -> SafetyReport:
    """Definition 1 turned into a trace-bounded check: does Q ever merge inputs
    whose readout differs, ON THE TRACE GIVEN?

    ker(Q) subseteq ker(g) is the safety condition. It is decidable ON A FINITE
    SAMPLE that a violation occurred -- but the ABSENCE of a violation in one
    sample is not a proof there is none elsewhere. Confusing the two was the
    exact failure the Phase 0 dogfood test reproduced.

    A production cache key that fails this is not "slightly approximate" -- it is
    a correctness/authorisation bug (Section 10.1: no key may merge requests whose
    observable permissions or protected content differ).

    coverage_key / declared_cells (recommended, fail-closed if only one is given):
    map each sample to the coverage cell it exercises (e.g. (service, role_class))
    and declare the full set of cells the system is supposed to have. A PASS is
    then reported as UNCERTIFIED, not OK, whenever cells remain untested -- see
    `SafetyReport.trustworthy_pass`.
    """
    if (coverage_key is None) != (declared_cells is None):
        raise ValueError(
            "coverage_key and declared_cells must both be given, or neither -- "
            "a half-declared coverage check would silently certify an "
            "unmeasured PASS, which is the exact bug this function exists to catch."
        )

    classes: dict[Hashable, list[Any]] = defaultdict(list)
    seen_cells: set[Hashable] = set()
    n = 0
    for s in samples:
        classes[key_fn(s)].append(s)
        if coverage_key is not None:
            seen_cells.add(coverage_key(s))
        n += 1

    violations: list[tuple[Any, Any, Any]] = []
    max_gap = 0.0
    for k, members in classes.items():
        readouts = [readout_fn(m) for m in members]
        first = readouts[0]
        for r in readouts[1:]:
            if distance is None:
                if r != first:
                    max_gap = max(max_gap, 1.0)
                    if len(violations) < max_report:
                        violations.append((k, first, r))
                    break
            else:
                d = distance(first, r)
                if d > max_gap:
                    max_gap = d
                if d > 0 and len(violations) < max_report:
                    violations.append((k, first, r))

    gaps = None
    if declared_cells is not None:
        gaps = sorted(set(declared_cells) - seen_cells, key=repr)

    return SafetyReport(
        n_samples=n,
        n_keys=len(classes),
        exact_safe=not violations,
        max_observed_gap=max_gap,
        violating_keys=violations,
        coverage_gaps=gaps,
    )


register_closure("audit_key_safety", FINITE_DIAGNOSTIC)


# ----------------------------------------------------------------------------
# 3. Error certificate  (paper Theorem 2 / Corollary 1) -- max, never mean
# ----------------------------------------------------------------------------

@dataclass
class Certificate:
    """G2 — keeps 'what was proved' and 'what was measured' in separate columns.

    declared_delta : a real bound (Cor 1: L * r_Q). None when no L was established.
    observed_max   : max |g(x) - ghat(x)| over the sampled trace. A finite_diagnostic.
    observed_mean  : reported for context ONLY. A mean is not a certificate.
    """

    declared_delta: float | None
    observed_max: float
    observed_mean: float
    n: int
    scale: float = 1.0

    @property
    def holds(self) -> bool | None:
        """Did the sample respect the declared bound? None = nothing was declared."""
        if self.declared_delta is None:
            return None
        return self.observed_max <= self.declared_delta

    def __str__(self) -> str:
        rel_max = self.observed_max / self.scale if self.scale else float("nan")
        rel_mean = self.observed_mean / self.scale if self.scale else float("nan")
        if self.declared_delta is None:
            return (
                f"NO DECLARED BOUND (finite_diagnostic only): "
                f"max={rel_max:.3%} mean={rel_mean:.3%} over n={self.n}"
            )
        verdict = "respected" if self.holds else "*** VIOLATED ***"
        return (
            f"declared delta={self.declared_delta:.6g} ({verdict}) | "
            f"observed max={rel_max:.3%} mean={rel_mean:.3%} over n={self.n}"
        )


def lipschitz_delta(lipschitz_L: float, key_radius: float) -> float:
    """Corollary 1: a geometric quantisation radius becomes an output guarantee.

    TIER: the multiplication itself is EXACT. But the certificate this produces is
    only as good as `lipschitz_L` — if L was ESTIMATED (e.g. via `empirical_lipschitz`,
    which is a LOWER bound only) rather than exactly known, the resulting delta is
    NOT a certified bound; fra.py's own E3 experiment measured a declared bound built
    this way being VIOLATED at 3 of 4 tested resolutions. Callers MUST NOT pass an
    estimated L to this function and then present the result as Th-tier — re-tier the
    resulting Certificate to Dr/finite_diagnostic whenever L was not given exactly.
    """
    return lipschitz_L * key_radius


def empirical_lipschitz(
    points: Sequence[Any],
    f: Callable[[Any], float],
    d_input: Callable[[Any, Any], float],
    pairs: int = 20000,
    rng=None,
) -> float:
    """Largest observed |f(x)-f(y)| / d(x,y). A LOWER bound on L, never an upper one.

    Stated honestly: this measures a finite sample of difference quotients. It cannot
    certify L. It is used to check whether a *declared* L is plausible, and to expose
    a declared L that the data already contradicts.
    """
    import random

    rng = rng or random.Random(0)
    n = len(points)
    worst = 0.0
    for _ in range(pairs):
        i, j = rng.randrange(n), rng.randrange(n)
        if i == j:
            continue
        dx = d_input(points[i], points[j])
        if dx <= 0:
            continue
        q = abs(f(points[i]) - f(points[j])) / dx
        if q > worst:
            worst = q
    return worst


register_closure("lipschitz_delta", EXACT, theorem="(mirrors Cor 1's arithmetic; the "
                  "resulting certificate's tier depends on how L was obtained — see docstring)")
register_closure("empirical_lipschitz", FINITE_DIAGNOSTIC)


# ----------------------------------------------------------------------------
# 4. The accelerator + the online break-even guard
# ----------------------------------------------------------------------------

@dataclass
class GuardStats:
    n: int = 0
    hits: int = 0
    keys: int = 0
    disabled_at: int | None = None
    reason: str = ""

    @property
    def alpha(self) -> float:
        return self.keys / self.n if self.n else 1.0

    @property
    def hit_rate(self) -> float:
        return self.hits / self.n if self.n else 0.0


class BreakEvenGuard:
    """G3 — the paper's Eq (21) optimises using K_N as if it were known.

    K_N/N is a readout of an observed finite prefix; it does not bound the future
    trace. A deployment tuned at alpha=0.08 that drifts to alpha=0.9 crosses the
    break-even and gets SLOWER with nothing to announce it.

    This guard watches alpha over a sliding window and falls back to exact execution
    when the window's alpha exceeds the model's break-even, with hysteresis so a
    single burst does not flap the cache.
    """

    def __init__(
        self,
        cost: CostModel,
        window: int = 2000,
        margin: float = 0.9,
        recheck_every: int = 2000,
    ):
        self.cost = cost
        self.window = window
        self.margin = margin  # require alpha < margin * break_even to stay on
        self.recheck_every = recheck_every
        self.enabled = True
        self.stats = GuardStats()
        self._window_keys: Counter = Counter()
        self._window_n = 0
        self._since_check = 0

    def observe(self, key: Hashable, was_hit: bool) -> None:
        self.stats.n += 1
        self.stats.hits += int(was_hit)
        self._window_keys[key] += 1
        self._window_n += 1
        self._since_check += 1
        if self._window_n > self.window:
            self._window_keys.clear()
            self._window_n = 0
        if self._since_check >= self.recheck_every:
            self._since_check = 0
            self._evaluate()

    def _evaluate(self) -> None:
        if self._window_n == 0:
            return
        alpha = len(self._window_keys) / self._window_n
        limit = self.margin * self.cost.break_even_alpha()
        if self.enabled and alpha > limit:
            self.enabled = False
            self.stats.disabled_at = self.stats.n
            self.stats.reason = (
                f"alpha={alpha:.3f} exceeded {limit:.3f} "
                f"(break-even {self.cost.break_even_alpha():.3f})"
            )
        elif not self.enabled and alpha < 0.5 * limit:
            self.enabled = True
            self.stats.reason = f"re-enabled at alpha={alpha:.3f}"


class FiniteReadoutAccelerator:
    """The Listing-1 execution pattern, with the guard and the safety audit wired in."""

    def __init__(
        self,
        key_fn: Callable[[Any], Hashable],
        representative_fn: Callable[[Any, Hashable], Any],
        expensive_fn: Callable[[Any], Any],
        cost: CostModel | None = None,
        guard: BreakEvenGuard | None = None,
    ):
        self.key_fn = key_fn
        self.representative_fn = representative_fn
        self.expensive_fn = expensive_fn
        self.cache: dict[Hashable, Any] = {}
        self.guard = guard or (BreakEvenGuard(cost) if cost else None)
        self.n = 0
        self.misses = 0

    def __call__(self, x: Any) -> Any:
        self.n += 1
        if self.guard is not None and not self.guard.enabled:
            return self.expensive_fn(x)
        k = self.key_fn(x)
        hit = k in self.cache
        if not hit:
            self.misses += 1
            self.cache[k] = self.expensive_fn(self.representative_fn(x, k))
        if self.guard is not None:
            self.guard.observe(k, hit)
        return self.cache[k]

    @property
    def alpha(self) -> float:
        return self.misses / self.n if self.n else 1.0


def injective_key_guard(n: int, k: int) -> bool:
    """Prop 2, made actionable: True iff the key is injective on this trace (K == N),
    which means NO acceleration is possible — Coq's `injective_key_slowdown` proves
    this is a strict SLOWDOWN whenever c_o > 0, not merely a wash. Call this before
    deploying a quotient; a True result means stop, the key design is wrong.
    """
    return k >= n


register_closure("injective_key_guard", EXACT, theorem="injective_key_slowdown")


# ----------------------------------------------------------------------------
# 5. Phase 2 closures — added after the ultracode review's corrected taxonomy.
#    EXACT closures here are new, real, motivated by E3/E4/the ARAYA measurement.
#    DR closures (Little's Law, M/M/c) are the ones the review said the ORIGINAL
#    proposal listed unflagged next to exact ones — added here WITH the required
#    assumption declared at registration time (register_closure enforces this).
# ----------------------------------------------------------------------------

def latency_percentiles(samples_seconds: Sequence[float],
                         ps: Sequence[float] = (0.50, 0.90, 0.95, 0.99)) -> dict[float, float]:
    """p50/p90/p95/p99 over a FINITE measured latency multiset. Sort-and-index —
    an exact statistic of the sample given, no model assumption anywhere.

    Motivated directly by experiment E3: max/mean error ran 20-28x on the same
    workload where a mean looked fine. A cache/SLO gate that reports only the mean
    inherits that blind spot; report percentiles, always, alongside any mean.
    """
    if not samples_seconds:
        raise ValueError("latency_percentiles: empty sample — HOLD, not a guess")
    xs = sorted(samples_seconds)
    n = len(xs)
    out = {}
    for p in ps:
        idx = min(n - 1, int(math.ceil(p * n)) - 1)
        idx = max(0, idx)
        out[p] = xs[idx]
    return out


register_closure("latency_percentiles", EXACT)


def error_budget_minutes(slo_fraction: float, window_days: int = 30) -> float:
    """SLO% -> allowed downtime, in minutes, over `window_days`. Exact arithmetic."""
    if not (0.0 < slo_fraction < 1.0):
        raise ValueError("slo_fraction must be in (0,1) — e.g. 0.999 for 99.9%")
    total_minutes = window_days * 24 * 60
    return total_minutes * (1.0 - slo_fraction)


register_closure("error_budget_minutes", EXACT)


def staleness_bound_seconds(ttl_seconds: float, purge_lag_seconds: float) -> float:
    """Section 10.3: a cached value's worst-case staleness. Exact given TTL and the
    measured purge propagation lag; this is an upper bound by definition, not an
    estimate — the arithmetic is trivial, the value is in stating it at all
    (Section 10.3's freshness contract has no home in the original proposal's
    closure list despite being one of its own stated safety requirements).
    """
    return ttl_seconds + purge_lag_seconds


register_closure("staleness_bound_seconds", EXACT)


def payload_budget_seconds(bytes_: float, bandwidth_bps: float,
                            rtt_seconds: float, round_trips: int) -> float:
    """T = bytes/bw + RTT * round_trips. Exact given bandwidth/RTT as measured inputs
    (they are not universal constants — measure them on the path in question)."""
    return bytes_ / bandwidth_bps + rtt_seconds * round_trips


register_closure("payload_budget_seconds", EXACT)


def bottleneck_ceiling(total_seconds: float, fixed_seconds: float) -> float:
    """The review's finding #7 correction, mirrored from Coq's `bottleneck_ceiling`:
    if `total` splits into a FIXED cost plus a variable rest, the best any amount of
    work on the variable part can ever achieve is total/fixed — always >= 1, an upper
    bound on the payoff of optimising anything except the fixed cost.

    On the ARAYA measurement (fixed=bootstrap=1.130s, total=1.356s) this gives
    1.20x — the number that replaced the retracted claim "tuning any page is
    pointless". >=1 always; the discipline is stating a NUMBER, not a verdict.
    """
    if fixed_seconds <= 0:
        raise ValueError("fixed_seconds must be > 0")
    return total_seconds / fixed_seconds


register_closure("bottleneck_ceiling", EXACT, theorem="bottleneck_ceiling")


def littles_law_L(lambda_rate: float, w_seconds: float) -> float:
    """Little's Law: L = lambda * W (mean number in system = arrival rate * mean
    time in system).

    TIER: Dr, not exact-unconditionally. It is a long-run TIME-AVERAGE identity; on
    a finite measurement window with nonzero work-in-progress at the boundaries
    (ramp-up/ramp-down), there is a real boundary-error term this formula does not
    account for. Use it for capacity PLANNING over a long steady window, not as an
    exact statement about a short or bursty one.
    """
    return lambda_rate * w_seconds


register_closure(
    "littles_law_L", DR,
    assumption="steady-state / stationary arrivals over the measurement window; "
               "boundary WIP at window start/end is assumed negligible",
)


def mmc_wait_time(lambda_rate: float, mu_rate: float, c_servers: int) -> float:
    """M/M/c mean queueing wait time E[Wq], via the Erlang-C formula.

    TIER: Dr. Requires Poisson arrivals, exponential i.i.d. service times, and
    independence between them — real request traffic is frequently NEITHER
    (bursty, autocorrelated). The number returned is E[Wq], a MEAN — it says
    nothing about the tail, and it diverges as utilisation rho -> 1. Pair with
    `latency_percentiles` on real traffic before trusting this for a capacity
    decision; never present it as a per-request bound.
    """
    rho = lambda_rate / (c_servers * mu_rate)
    if rho >= 1:
        raise ValueError(f"unstable queue: rho={rho:.3f} >= 1 (Wq -> infinity)")
    a = lambda_rate / mu_rate  # offered load, Erlangs
    # Erlang-C probability of queueing, via the standard recursive sum.
    s = sum((a ** k) / math.factorial(k) for k in range(c_servers))
    top = (a ** c_servers) / (math.factorial(c_servers) * (1 - rho))
    p_wait = top / (s + top)
    return p_wait / (c_servers * mu_rate - lambda_rate)


register_closure(
    "mmc_wait_time", DR,
    assumption="Poisson arrivals, i.i.d. exponential service times, independence "
               "between arrival and service processes; number is E[Wq], a MEAN, "
               "not a per-request bound, and blows up as rho -> 1",
)


def index_selectivity_posthoc(rows_scanned: int, rows_matched: int) -> float:
    """Selectivity computed AFTER the fact from EXPLAIN ANALYZE: rows_matched/rows_scanned.
    Exact arithmetic — but tautological. It describes a query that already ran; it
    has zero predictive value for a query about to run. Do not confuse with the
    predictive form below.
    """
    if rows_scanned <= 0:
        raise ValueError("rows_scanned must be > 0")
    return rows_matched / rows_scanned


register_closure("index_selectivity_posthoc", EXACT)


def index_selectivity_predictive(distinct_values: int, table_rows: int) -> float:
    """Selectivity ESTIMATED from planner statistics: 1/distinct_values, applied to
    table_rows to predict rows scanned for an equality lookup.

    TIER: Dr. Assumes uniform value distribution AND independence from any other
    predicate in the same query — breaks on skewed columns and on correlated
    columns (e.g. province + service correlated through which packages a province
    actually offers). Verify against index_selectivity_posthoc on real queries
    before trusting this for a plan decision.
    """
    if distinct_values <= 0:
        raise ValueError("distinct_values must be > 0")
    return table_rows / distinct_values


register_closure(
    "index_selectivity_predictive", DR,
    assumption="uniform value distribution across rows AND independence from any "
               "other predicate in the query — breaks under skew or column correlation",
)


# ----------------------------------------------------------------------------
# 6. Layer B audits (Phase 3) — the ultracode review's CORRECTED list.
#
# The proposal originally claimed 7 "decidable" audits as "the real IP". The
# review found: 2 of the 7 are not separate audits at all (folded below), 2 are
# generic boilerplate wrongly counted as differentiating IP (kept, re-scoped),
# and the claim "the real IP" itself is retracted — these are the team's own
# captured regression tests wired into deploy gates, not a moat.
#
#   key_safety        KEPT — see audit_key_safety above (Phase 0 added the
#                      mandatory coverage precondition; cache_correctness and
#                      cookie_bypass are folded in below as PROBE STRATEGIES
#                      that generate the samples audit_key_safety consumes,
#                      not separate audits).
#   php_parse_gate     KEPT as a baseline CI gate, dropped from the IP claim.
#                      Paired with route_smoke_test for what a parse check
#                      structurally cannot catch (a missing class/function
#                      after a dependency change — still valid PHP syntax).
#   require_guard_audit KEPT, SCOPED explicitly: decides literal-path
#                      require()/include() only. Dynamic-path requires
#                      (autoloaders, theme loaders) are reported as
#                      UNDECIDABLE, not silently passed.
#   atomic_deploy_audit KEPT unchanged — the review found no surviving
#                      objection; genuinely decidable given a deploy plan.
#   frozen_data_audit  KEPT, ships together with:
#   metric_staleness   NEW (the review's required addition) — the symmetric
#                      failure to frozen_data: a measured input silently going
#                      STALE rather than being silently regenerated. Every
#                      measured value must carry measured_at + a max_age, or
#                      solve()/audit() must refuse to use it.
#
# All of these are TIER finite_diagnostic: each is decidable ON THE ARTIFACT
# GIVEN (a trace, a source string, a deploy plan) — never a proof that no
# violation exists beyond what was checked. Phase 0 measured this distinction
# concretely for key_safety; the same discipline applies to every audit here.
# ----------------------------------------------------------------------------

import re
import shutil
import subprocess


@dataclass
class AuditFinding:
    check: str
    status: str          # "PASS" | "FAIL" | "UNDECIDABLE" | "HOLD"
    detail: str
    example: str | None = None

    def __str__(self) -> str:
        head = f"[{self.check}] {self.status}"
        return f"{head}: {self.detail}" + (f"\n    example: {self.example}" if self.example else "")


# --- php_parse_gate ---------------------------------------------------------

def php_parse_gate(php_files: dict[str, str]) -> list[AuditFinding]:
    """Law G10: a PHP parse error on ANY file is a site-wide 500. `php -l` every
    file before it goes near live. Baseline CI gate — not differentiating IP,
    two decades old, kept because Law G10 makes it mandatory, not because it is
    novel.

    Honest about its own tooling dependency: if no `php` binary is available,
    this returns HOLD (not a fabricated PASS) — the exact discipline the
    proposal's "refuse to guess" rule demands, extended to tool availability,
    not just measured numbers.
    """
    php_bin = shutil.which("php")
    if php_bin is None:
        return [AuditFinding(
            "php_parse_gate", "HOLD",
            "no `php` binary found on this host — cannot lint, refusing to fabricate a PASS",
            example="install php-cli, or run this gate on the deploy host/CI runner",
        )]

    findings = []
    for path, source in php_files.items():
        r = subprocess.run(
            [php_bin, "-l"], input=source, capture_output=True, text=True, timeout=10
        )
        if r.returncode == 0:
            findings.append(AuditFinding("php_parse_gate", "PASS", path))
        else:
            findings.append(AuditFinding(
                "php_parse_gate", "FAIL", path, example=r.stdout.strip() or r.stderr.strip()
            ))
    return findings


def route_smoke_test(routes: dict[str, Callable[[], Any]]) -> list[AuditFinding]:
    """What php_parse_gate structurally CANNOT catch: valid syntax that calls an
    undefined function/class (e.g. after removing a dependency the code still
    references). Hit each declared route/entry point once and record whether it
    raises. Requires a live or staging target — this is NOT a replacement for
    php_parse_gate, it is the pair the review said the claim needed.
    """
    findings = []
    for name, call in routes.items():
        try:
            call()
            findings.append(AuditFinding("route_smoke_test", "PASS", name))
        except Exception as e:  # noqa: BLE001 — deliberately broad, this IS the check
            findings.append(AuditFinding(
                "route_smoke_test", "FAIL", name, example=f"{type(e).__name__}: {e}"
            ))
    return findings


register_closure("php_parse_gate", FINITE_DIAGNOSTIC)
register_closure("route_smoke_test", FINITE_DIAGNOSTIC)


# --- require_guard_audit -----------------------------------------------------

_REQUIRE_LITERAL = re.compile(
    r"""\b(require|require_once|include|include_once)\s*(?:\()?\s*['"]([^'"]+)['"]"""
)
_REQUIRE_DYNAMIC = re.compile(
    r"""\b(require|require_once|include|include_once)\s*(?:\()?\s*(?!['"])([^;]+);"""
)


def require_guard_audit(php_source: str) -> list[AuditFinding]:
    """Every literal-path require()/include() of a file that might not exist yet
    at deploy time (a genuine incident: a new file `require`d before its own
    upload landed caused a 3-minute live outage) must be preceded by a
    file_exists() guard on the SAME line (the ternary/if-guard pattern this
    codebase actually uses) or the line immediately before it.

    SCOPE, stated up front per the review: this decides LITERAL string paths
    only. A dynamic path (a variable, a concatenation, an autoloader) is
    reported UNDECIDABLE — never silently treated as safe. Autoloaders and
    theme loaders in the real ARAYA codebase fall here and need a manual,
    Dr-tier check; this function does not pretend otherwise.
    """
    findings = []
    lines = php_source.splitlines()
    for i, line in enumerate(lines):
        m = _REQUIRE_LITERAL.search(line)
        if m:
            path = m.group(2)
            window = " ".join(lines[max(0, i - 1):i + 1])
            if "file_exists" in window:
                findings.append(AuditFinding(
                    "require_guard_audit", "PASS", f"line {i+1}: require({path!r}) guarded"
                ))
            else:
                findings.append(AuditFinding(
                    "require_guard_audit", "FAIL",
                    f"line {i+1}: require({path!r}) has no file_exists() guard",
                    example=line.strip(),
                ))
            continue
        m2 = _REQUIRE_DYNAMIC.search(line)
        if m2 and not _REQUIRE_LITERAL.search(line):
            findings.append(AuditFinding(
                "require_guard_audit", "UNDECIDABLE",
                f"line {i+1}: dynamic-path require — needs a manual (Dr-tier) check",
                example=line.strip(),
            ))
    return findings


register_closure("require_guard_audit", FINITE_DIAGNOSTIC)


# --- atomic_deploy_audit ------------------------------------------------------

def atomic_deploy_audit(file_count: int, method: str) -> AuditFinding:
    """G12: deploying a plugin/theme with more than one file via a live mirror
    (rsync/lftp mirror onto the serving path) produces a real half-old/half-new
    state under real traffic — measured incident: a 26-minute wpforms-lite
    mirror produced a live fatal-error window. `method` must be
    'atomic_rename' (upload to a new dir, then one rename) whenever more than
    one file is touched; a single small file may still use G8's one-connection
    direct write.
    """
    if file_count <= 1:
        return AuditFinding("atomic_deploy_audit", "PASS",
                             f"{file_count} file(s) — single-file direct write is safe (G8)")
    if method == "atomic_rename":
        return AuditFinding("atomic_deploy_audit", "PASS",
                             f"{file_count} files via atomic_rename")
    return AuditFinding(
        "atomic_deploy_audit", "FAIL",
        f"{file_count} files via {method!r} — must be atomic_rename, not a live mirror",
        example="upload to <slug>-new/, verify, then rename() once (see G12)",
    )


register_closure("atomic_deploy_audit", FINITE_DIAGNOSTIC)


# --- frozen_data_audit ---------------------------------------------------------

_LIVE_CLOCK_CALL = re.compile(r"\b(date\s*\(|time\s*\(|new\s+DateTime\s*\(\s*\)|strtotime\s*\(\s*['\"]now['\"])")


def frozen_data_audit(php_source: str, frozen_fields: Sequence[str]) -> list[AuditFinding]:
    """Data that must be frozen at creation (a certificate's issue date, a
    contract's signed-at timestamp) must never be regenerated at render time —
    the exact bug that made a certificate show today's date on every view.

    Decidable AS A LINT on the source given: a live-clock call (`date()`,
    `time()`, `new DateTime()` with no args, `strtotime('now')`) that is NOT
    assigned to one of the declared `frozen_fields`, and not reading a stored
    value (`$this->field`, `get_post_meta(..., 'field', ...)`), is flagged.
    This is a syntactic check, not a data-flow proof — it can miss an
    obfuscated case, which is exactly why its tier is finite_diagnostic.
    """
    findings = []
    for i, line in enumerate(php_source.splitlines()):
        if _LIVE_CLOCK_CALL.search(line):
            reads_stored = any(
                (f"->{f}" in line) or (f"'{f}'" in line and "get_post_meta" in line)
                for f in frozen_fields
            )
            assigns_frozen = any(
                re.search(rf"\b{re.escape(f)}\s*=", line) for f in frozen_fields
            )
            if reads_stored and not _LIVE_CLOCK_CALL.search(line.split("=")[0] if "=" in line else line):
                continue
            if assigns_frozen:
                findings.append(AuditFinding(
                    "frozen_data_audit", "PASS",
                    f"line {i+1}: live clock call assigned to a frozen field at creation",
                ))
            else:
                findings.append(AuditFinding(
                    "frozen_data_audit", "FAIL",
                    f"line {i+1}: live clock call not tied to a frozen field — "
                    "likely regenerated on every render",
                    example=line.strip(),
                ))
    return findings


register_closure("frozen_data_audit", FINITE_DIAGNOSTIC)


# --- metric_staleness --------------------------------------------------------

@dataclass
class MeasuredValue:
    """The schema gap the review required as a mandatory addition: every
    measured input (c_f, c_o, K_N, lambda, ...) must carry WHEN it was measured
    and where from, so solve()/audit() can refuse a value that has gone stale —
    the mirror-image failure to frozen_data (unwanted regeneration): unwanted
    SILENT STALENESS, which E6 already showed happens in practice.
    """

    value: float
    measured_at: float       # unix timestamp, caller-supplied (no clock access here)
    source: str
    max_age_seconds: float


def metric_staleness_check(mv: MeasuredValue, now: float) -> AuditFinding:
    """Refuse (FAIL, not a silent pass-through) a measured value older than its
    declared max_age. `now` is caller-supplied deliberately — this module takes
    no wall-clock reads, matching the rest of fra.py's determinism discipline.
    """
    age = now - mv.measured_at
    if age < 0:
        return AuditFinding("metric_staleness_check", "FAIL",
                             f"{mv.source}: measured_at is in the future ({age:.0f}s) — clock skew?")
    if age > mv.max_age_seconds:
        return AuditFinding(
            "metric_staleness_check", "FAIL",
            f"{mv.source}: {age:.0f}s old, exceeds max_age={mv.max_age_seconds:.0f}s — "
            "re-measure before using this value",
        )
    return AuditFinding("metric_staleness_check", "PASS",
                         f"{mv.source}: {age:.0f}s old, within max_age={mv.max_age_seconds:.0f}s")


register_closure("metric_staleness_check", FINITE_DIAGNOSTIC)


# --- silent_zero_collapse_audit -----------------------------------------------
#
# Added after auditing an external synthesis note on "Semantic Number" types
# (missing/below-resolution/failed/imputed values silently collapsed to a bare
# 0). Most of that proposal restates existing database-null / provenance /
# refinement-type literature (Imielinski & Lipski 1984; Buneman/Cheney/Green on
# provenance) rather than contributing something new -- but ONE piece of it is
# directly, concretely actionable inside THIS repo's own audit pattern: the
# "Explicit Collapse Boundary" idea (never let `?? 0` / `|| 0` / `COALESCE(x,0)`
# silently pick a value in place of missing/failed/below-resolution). That is a
# decidable, source-level check of exactly the same shape as require_guard_audit
# and frozen_data_audit already in this file -- so it is added HERE as a sixth
# audit, not as a new type system (a full "Semantic Number" algebra is a much
# larger, unproven claim this session has not attempted to verify).
#
# Convergence worth noting, not claiming as novel: `AuditFinding.status` (four
# states: PASS/FAIL/HOLD/UNDECIDABLE, never collapsed to a boolean) and
# `SafetyReport.trustworthy_pass` (True is NOT the same as "verified" -- a PASS
# with no coverage is distinguished from a PASS with full coverage) already
# independently implement the proposal's core idea for THIS codebase's own
# booleans, before that proposal was ever read. That is evidence the pattern
# generalises, not evidence it is new.

_SILENT_ZERO_PATTERNS = [
    re.compile(r"\?\?\s*0\b"),                              # JS/TS/PHP8 `?? 0`
    re.compile(r"\|\|\s*0\b"),                               # JS/PHP `|| 0`
    re.compile(r"COALESCE\s*\([^,)]+,\s*0\s*\)", re.IGNORECASE),  # SQL
    re.compile(r"\bisset\([^)]+\)\s*\?[^:]+:\s*0\b"),        # PHP ternary-to-zero
]
_COLLAPSE_OK_MARKER = re.compile(r"collapse-ok\s*:", re.IGNORECASE)


def silent_zero_collapse_audit(source: str) -> list[AuditFinding]:
    """Flags a value silently collapsed to 0 in place of missing/failed/
    below-resolution, per the "Explicit Collapse Boundary" idea: a null-safe
    default is legitimate ONLY when declared as a deliberate policy, not left
    implicit at every call site.

    Decidable AS A LINT on the source given (a regex match is a fact about the
    text, not an inference about behaviour) -- same tier and same honesty
    limits as require_guard_audit/frozen_data_audit: a line rewritten to dodge
    the pattern (e.g. via a helper function) will not be caught; this is a
    surface-syntax check, not a data-flow proof.

    A line is NOT flagged when it carries an explicit `collapse-ok: <reason>`
    comment on the same line -- the escape hatch the proposal itself asks for
    (a declared policy beats a silent default; it does not forbid defaults).
    """
    findings = []
    lines = source.splitlines()
    for i, line in enumerate(lines):
        window = " ".join(lines[max(0, i - 1):i + 1])
        if _COLLAPSE_OK_MARKER.search(window):
            continue
        for pat in _SILENT_ZERO_PATTERNS:
            if pat.search(line):
                findings.append(AuditFinding(
                    "silent_zero_collapse_audit", "FAIL",
                    f"line {i+1}: value silently collapsed to 0 with no declared policy",
                    example=line.strip(),
                ))
                break
    return findings


register_closure("silent_zero_collapse_audit", FINITE_DIAGNOSTIC)


# ----------------------------------------------------------------------------
# 7. Measurement helper
# ----------------------------------------------------------------------------

def timed(fn: Callable[[], Any], repeat: int = 3) -> tuple[float, Any]:
    """Median wall-clock of `repeat` runs. Returns (median_seconds, last_result)."""
    times, out = [], None
    for _ in range(repeat):
        t0 = time.perf_counter()
        out = fn()
        times.append(time.perf_counter() - t0)
    times.sort()
    return times[len(times) // 2], out
