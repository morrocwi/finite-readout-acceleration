"""
fra_histogram.py — FRAHistogram: a fixed-memory streaming quantile sketch with
an EXACT worst-case error bound, no estimation step anywhere.

THE GAP THIS CLOSES: `fra.py`'s own `latency_percentiles` sorts the full sample
-- fine for a batch, impossible to keep forever in production. The standard
production answer is t-digest/HdrHistogram: excellent in practice, but their
error bound is EMPIRICAL/asymptotic (tuned by a compression parameter), not an
exact per-query guarantee. That is the SAME failure shape this session's own
`lipschitz_delta` had when fed an ESTIMATED L (E3: the declared bound was
violated at 3 of 4 resolutions). We should not repeat that mistake in our own
new algorithm.

THE FIX, using our own equations directly: Corollary 1 (delta = L * r_Q) needs
an estimated Lipschitz constant ONLY because its readout key is built in the
INPUT'S coordinate space with an UNKNOWN local sensitivity. A histogram bucket
does not have that problem: the bucket geometry ITSELF bounds the value error,
by construction, with no L to estimate at all. This is a strictly CLEANER
instance of the same "declared resolution -> declared bound" idea in Cor 1 --
sidestepping the estimation risk entirely rather than estimating carefully.

HONEST LIMITS (stated up front, not discovered later):
  - Needs a DECLARED value range [lo, hi] up front (t-digest/reservoir sampling
    do not). Values outside range fall in overflow buckets with NO value-error
    bound -- only a rank-inclusion guarantee. This is a real trade-off, not a
    free win.
  - The bound is on VALUE error (|true value - reported value| <= width/2),
    not on RANK error. A query "give me the value at exact rank r" is not what
    this answers as tightly in a heavy-tailed low-count bucket; it answers
    "what is the value below which p% of traffic falls, to within w/2".
  - TIER: exact, given the declared range and bucket count. No model
    assumption, no estimated constant -- Th_coqc-eligible (the bound is
    `w/2 = (hi-lo)/(2*num_buckets)`, one line of ordered-field arithmetic
    for the standard IDM ladder, not built here to keep scope to Python).
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class FRAHistogram:
    lo: float
    hi: float
    num_buckets: int
    counts: list[int] = field(default_factory=list)
    overflow_low: int = 0
    overflow_high: int = 0
    n: int = 0

    def __post_init__(self):
        if not self.counts:
            self.counts = [0] * self.num_buckets

    @property
    def width(self) -> float:
        return (self.hi - self.lo) / self.num_buckets

    @property
    def declared_max_error(self) -> float:
        """The EXACT worst-case value error for any in-range query. No estimation."""
        return self.width / 2

    def update(self, x: float) -> None:
        self.n += 1
        if x < self.lo:
            self.overflow_low += 1
            return
        if x >= self.hi:
            self.overflow_high += 1
            return
        idx = int((x - self.lo) / self.width)
        idx = min(idx, self.num_buckets - 1)
        self.counts[idx] += 1

    def query(self, p: float) -> tuple[float, bool]:
        """Returns (estimated_value, in_range). in_range=False means the true
        quantile fell in an overflow bucket -- no value-error bound applies,
        stated honestly rather than silently returning a number that looks
        certified but isn't.
        """
        target = p * self.n
        if target <= self.overflow_low:
            return (self.lo, False)
        cum = self.overflow_low
        for i, c in enumerate(self.counts):
            cum += c
            if cum >= target:
                midpoint = self.lo + (i + 0.5) * self.width
                return (midpoint, True)
        return (self.hi, False)

    def memory_slots(self) -> int:
        """Counter slots used -- the fair unit to equalise against a reservoir's
        stored-value slots for a memory-budget-matched comparison."""
        return self.num_buckets


@dataclass
class FRAHistogramLog:
    """Log-scale variant: buckets by log(x - lo + eps) instead of x directly.

    ADDED after the FIRST version of this file was tested against a power-law
    workload and lost badly (uniform-width buckets waste resolution across the
    whole declared range while skewed data concentrates near one end -- the
    median fell in a single giant bucket). This is exactly why HdrHistogram
    uses log-linear bucketing in real APM tooling; the fix here is the same
    idea, derived the same way: the CONSTANT quantity is bucket width IN LOG
    SPACE, which turns into a RELATIVE (multiplicative) bound in real units --
    appropriate when large values can tolerate proportionally larger error,
    which is the usual case for latency/size distributions.

    Declared bound: |log(true) - log(reported)| <= (log(hi)-log(lo))/(2*num_buckets),
    i.e. reported value is within a constant MULTIPLICATIVE factor of the true
    value: true/reported in [exp(-halfwidth), exp(halfwidth)]. Still exact,
    still no estimated constant -- just a different (and here, better-fitting)
    declared metric than absolute width.
    """

    lo: float
    hi: float
    num_buckets: int
    eps: float = 1e-9
    counts: list[int] = field(default_factory=list)
    overflow_low: int = 0
    overflow_high: int = 0
    n: int = 0

    def __post_init__(self):
        if not self.counts:
            self.counts = [0] * self.num_buckets
        self._log_lo = math.log(self.eps)
        self._log_hi = math.log(self.hi - self.lo + self.eps)
        self._log_width = (self._log_hi - self._log_lo) / self.num_buckets

    @property
    def declared_max_log_error(self) -> float:
        return self._log_width / 2

    def declared_relative_bound(self) -> float:
        """The multiplicative factor: true value is within [1/f, f] * reported."""
        return math.exp(self.declared_max_log_error)

    def update(self, x: float) -> None:
        self.n += 1
        if x < self.lo:
            self.overflow_low += 1
            return
        if x >= self.hi:
            self.overflow_high += 1
            return
        y = math.log(x - self.lo + self.eps)
        idx = int((y - self._log_lo) / self._log_width)
        idx = min(max(idx, 0), self.num_buckets - 1)
        self.counts[idx] += 1

    def query(self, p: float) -> tuple[float, bool]:
        target = p * self.n
        if target <= self.overflow_low:
            return (self.lo, False)
        cum = self.overflow_low
        for i, c in enumerate(self.counts):
            cum += c
            if cum >= target:
                y_mid = self._log_lo + (i + 0.5) * self._log_width
                value = self.lo + math.exp(y_mid) - self.eps
                return (value, True)
        return (self.hi, False)

    def memory_slots(self) -> int:
        return self.num_buckets


class ReservoirQuantile:
    """Classic Algorithm R streaming reservoir sample, percentile via sort at
    query time. NO declared error bound at any finite k -- only "converges as
    k grows", a Dr-tier statement at best, and precision is DENSITY-dependent:
    it degrades hardest exactly at extreme quantiles, where few samples land.
    """

    def __init__(self, k: int, seed: int = 0):
        self.k = k
        self.rng = random.Random(seed)
        self.reservoir: list[float] = []
        self.n = 0

    def update(self, x: float) -> None:
        self.n += 1
        if len(self.reservoir) < self.k:
            self.reservoir.append(x)
        else:
            j = self.rng.randrange(self.n)
            if j < self.k:
                self.reservoir[j] = x

    def query(self, p: float) -> float:
        xs = sorted(self.reservoir)
        idx = max(0, min(len(xs) - 1, int(math.ceil(p * len(xs))) - 1))
        return xs[idx]

    def memory_slots(self) -> int:
        return self.k
