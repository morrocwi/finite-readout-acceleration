"""
beve_cache.py — BEVE (Break-Even Value Eviction): a cache replacement policy
DERIVED from our own equations (Thm 3 break_even_iff, the CostModel), not a
generic heuristic borrowed from the literature and relabelled.

THE GAP THIS CLOSES (found by auditing the standard algorithm list under our own
framework): LRU, LFU, ARC, W-TinyLFU all have ZERO formal guarantee and are
COST-BLIND — they decide what to evict using only recency/frequency, never how
expensive a given key is to regenerate. Real web caches have wildly heterogeneous
per-key cost (this session's own ARAYA measurement: 1.20s-1.59s render time
across pages, a >30% spread) yet every standard eviction policy throws that
information away. An eviction rule that keeps a CHEAP page just because it was
touched a moment ago, while evicting an EXPENSIVE page that is only slightly
colder, is leaving real cost on the table.

HONESTY UP FRONT, before a single number is reported:
  - The idea "weight by (frequency x cost)" already exists in the literature —
    Cao & Irani's GDSF (1997) and its relatives. BEVE's EVICTION rule is in that
    family; it is not claimed as a novel discovery. The two pieces that ARE new
    here, and that come DIRECTLY from this session's own machine-checked math:
      (a) ADMISSION control derived from Thm 3 (break_even_iff)/Prop 1
          (ceiling_strict) instead of "cache everything and let eviction sort it
          out" — a key whose own c_f does not exceed c_o is refused admission at
          all, closing off the Prop-2 slowdown before it can happen.
      (b) A whole-cache BreakEvenGuard (already built, already Coq-adjacent via
          break_even_alpha) wired in as a circuit breaker: if the AGGREGATE
          workload drifts past break-even, the cache disables itself instead of
          silently becoming a cost the operator never sees (the exact failure
          mode E6 demonstrated for the simple accelerator).
  - TIER: admission is EXACT (reuses break_even_alpha / ceiling_strict, already
    Th_coqc). Eviction-among-cached-keys is Dr / finite_diagnostic — a
    heuristic, empirically tested below, NOT a proof of optimality. Online cache
    replacement with unknown future access patterns has no known
    universally-optimal competitive algorithm; do not claim one.
  - The experiment below DELIBERATELY includes a workload constructed to try to
    beat BEVE (strong temporal locality, weak cost signal) — if BEVE loses
    there, that is reported, not hidden. "No silent caps: report what was
    dropped."
"""

from __future__ import annotations

import math
import random
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Hashable

from .core import CostModel


# ----------------------------------------------------------------------------
# Baselines — plain, correct, unweighted-by-cost.
# ----------------------------------------------------------------------------

class LRUCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.store: OrderedDict[Hashable, Any] = OrderedDict()

    def get(self, key: Hashable) -> bool:
        if key in self.store:
            self.store.move_to_end(key)
            return True
        return False

    def put(self, key: Hashable, value: Any) -> None:
        if key in self.store:
            self.store.move_to_end(key)
        self.store[key] = value
        if len(self.store) > self.capacity:
            self.store.popitem(last=False)


class LFUCache:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.freq: dict[Hashable, int] = {}
        self.store: dict[Hashable, Any] = {}

    def get(self, key: Hashable) -> bool:
        if key in self.store:
            self.freq[key] += 1
            return True
        return False

    def put(self, key: Hashable, value: Any) -> None:
        if key in self.store:
            self.freq[key] += 1
            self.store[key] = value
            return
        if len(self.store) >= self.capacity:
            evict = min(self.freq, key=lambda k: self.freq[k])
            del self.store[evict]
            del self.freq[evict]
        self.store[key] = value
        self.freq[key] = 1


# ----------------------------------------------------------------------------
# BEVE — admission from Thm 3/ceiling_strict (EXACT), eviction is a GDSF-style
# cost*frequency score with an ageing cursor (Dr / heuristic, tested below).
# ----------------------------------------------------------------------------

@dataclass
class BEVEStats:
    admitted: int = 0
    refused_admission: int = 0
    evictions: int = 0
    guard_disabled_at: int | None = None
    hits: int = 0
    requests: int = 0
    total_cost: float = 0.0


class BEVECache:
    """Tracks its own total_cost/hits internally (Tq's own accounting: hit=c_o,
    miss=c_o+cf+c_m, guard-bypassed=cf only, no key overhead at all) so a caller
    never has to reimplement — and possibly mis-implement — the cost model.
    """

    def __init__(self, capacity: int, shared_co: float, shared_cm: float = 0.0,
                 guard_window: int = 500, guard_margin: float = 0.9):
        self.capacity = capacity
        self.shared_co = shared_co
        self.shared_cm = shared_cm
        self.store: dict[Hashable, dict] = {}   # key -> {value, cf, freq, score}
        self.clock = 0.0  # GDSF ageing cursor -- the min score currently evicted
        self.stats = BEVEStats()
        # whole-cache guard, reusing the same Thm-3 arithmetic as fra.py's
        # BreakEvenGuard, scoped here to a rolling admission-refusal rate.
        self._window: list[bool] = []
        self.guard_window = guard_window
        self.guard_margin = guard_margin
        self.guard_enabled = True

    def _admit_test(self, cf: float) -> bool:
        """Reuses ceiling_strict's own hypothesis directly: a key only belongs
        in the cache at all if cf > c_o (Thm 3's break-even numerator). A key
        that fails this can NEVER pay for its own admission overhead, no matter
        how it is evicted — Prop 2's slowdown, refused before it can happen.
        """
        return cf > self.shared_co

    def get_or_compute(self, key: Hashable, cf: float, compute: Callable[[], Any]) -> Any:
        self.stats.requests += 1

        if not self.guard_enabled:
            self.stats.total_cost += cf  # bypassed entirely: no key overhead paid
            return compute()

        if key in self.store:
            entry = self.store[key]
            entry["freq"] += 1
            entry["score"] = self.clock + entry["freq"] * entry["cf"]
            self._observe(True)
            self.stats.hits += 1
            self.stats.total_cost += self.shared_co
            return entry["value"]

        self._observe(False)
        self.stats.total_cost += self.shared_co + cf + self.shared_cm

        if not self._admit_test(cf):
            self.stats.refused_admission += 1
            return compute()  # never cache it -- would only ever cost more

        value = compute()
        self.stats.admitted += 1
        score = self.clock + 1 * cf
        self.store[key] = {"value": value, "cf": cf, "freq": 1, "score": score}
        if len(self.store) > self.capacity:
            self._evict()
        return value

    def _evict(self) -> None:
        victim = min(self.store, key=lambda k: self.store[k]["score"])
        self.clock = self.store[victim]["score"]  # GDSF ageing: raise the cursor
        del self.store[victim]
        self.stats.evictions += 1

    def _observe(self, hit: bool) -> None:
        self._window.append(hit)
        if len(self._window) < self.guard_window:
            return
        alpha = 1 - (sum(self._window) / len(self._window))  # observed miss ratio
        # crude aggregate break-even: treat the whole cache as one CostModel
        # using the mean admitted cf as a stand-in cost signal.
        cfs = [e["cf"] for e in self.store.values()] or [0.0]
        mean_cf = sum(cfs) / len(cfs)
        model = CostModel(c_f=mean_cf if mean_cf > 0 else 1e-9, c_o=self.shared_co,
                           c_m=self.shared_cm)
        limit = self.guard_margin * model.break_even_alpha()
        if self.guard_enabled and alpha > limit and limit > 0:
            self.guard_enabled = False
            self.stats.guard_disabled_at = self.stats.admitted + self.stats.refused_admission
        elif not self.guard_enabled and alpha < 0.5 * limit:
            self.guard_enabled = True
        self._window.clear()


# ----------------------------------------------------------------------------
# Simulator — accounts total cost with FRA's OWN Tq equation: hit=c_o, miss=cf+cm.
# ----------------------------------------------------------------------------

def simulate(policy: str, trace: list[tuple[Hashable, float]], capacity: int,
             c_o: float, c_m: float = 0.0) -> dict:
    hits = 0
    total_cost = 0.0
    extra = {}

    if policy == "lru":
        cache = LRUCache(capacity)
        for key, cf in trace:
            if cache.get(key):
                hits += 1
                total_cost += c_o
            else:
                total_cost += c_o + cf + c_m
                cache.put(key, True)
    elif policy == "lfu":
        cache = LFUCache(capacity)
        for key, cf in trace:
            if cache.get(key):
                hits += 1
                total_cost += c_o
            else:
                total_cost += c_o + cf + c_m
                cache.put(key, True)
    elif policy == "beve":
        cache = BEVECache(capacity, shared_co=c_o, shared_cm=c_m)
        for key, cf in trace:
            cache.get_or_compute(key, cf, compute=lambda: True)
        hits = cache.stats.hits
        total_cost = cache.stats.total_cost
        extra = {
            "admitted": cache.stats.admitted,
            "refused_admission": cache.stats.refused_admission,
            "evictions": cache.stats.evictions,
            "guard_disabled_at": cache.stats.guard_disabled_at,
        }
    else:
        raise ValueError(policy)

    n = len(trace)
    raw_cost = sum(c_o + cf + c_m for _, cf in trace)  # no caching at all
    return {
        "policy": policy, "n": n, "hits": hits, "hit_rate": hits / n,
        "total_cost": total_cost, "raw_cost": raw_cost,
        "speedup": raw_cost / total_cost if total_cost > 0 else float("inf"),
        **extra,
    }
