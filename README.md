# Finite Readout Acceleration (FRA) — engineering library

[![CI](https://github.com/morrocwi/finite-readout-acceleration/actions/workflows/ci.yml/badge.svg)](https://github.com/morrocwi/finite-readout-acceleration/actions/workflows/ci.yml)
[![Coq](https://img.shields.io/badge/Coq-8.20%20·%205%20theorems%20axiom--free-blue?logo=coq&logoColor=white)](formal/)
[![tests](https://img.shields.io/badge/tests-30%20passing-brightgreen)](tests/)
[![release](https://img.shields.io/badge/release-v0.1.0-brightgreen)](https://github.com/morrocwi/finite-readout-acceleration/releases/tag/v0.1.0)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

An implementation and engineering companion to Yaoharee Lahtee (2026),
*"What a Finite Readout Need Not Compute: A Quotient Framework for Immediate
Acceleration in Web, Cache, Database, and Vector Systems."*

The paper's rule, in one line:

> **Do not compute a distinction more precisely or more often than the
> declared readout can retain.**

This repository turns that rule into code: a cost model, a break-even guard,
a coverage-audited cache-safety linter, five production deploy-safety audits,
and two algorithms derived directly from the paper's own theorems (a
cost-aware cache eviction policy, and a streaming quantile sketch with an
exact — not estimated — error bound).

**Status: alpha.** Built and tested against synthetic workloads plus one real
site measurement (below). Not yet used in a production deploy pipeline.

## Install

```bash
pip install -e .
pytest
```

## Quick start

```python
import fra

model = fra.CostModel(c_f=1.34, c_o=0.137)   # measured, not guessed — see below
model.break_even_alpha()      # 0.898 -- caching pays below 89.8% distinct-key ratio
model.max_speedup_ceiling()   # 9.8x  -- strict, for every finite trace, no limit taken

fra.kinds()                   # every registered closure/audit + its tier
fra.describe("break_even_alpha")
```

## Why this exists — the tier discipline

Every function in this library is registered with a tier, and a Dr-tier
closure cannot be registered without a stated assumption (`register_closure`
raises otherwise — see `tests/test_closures.py`):

| Tier | Means | Example |
|---|---|---|
| `EXACT` | arithmetic identity/inequality over ℚ given measured inputs, no model | `break_even_alpha`, `bottleneck_ceiling` |
| `Dr` | exact **under a declared assumption**, which must be surfaced with the number | `littles_law_L` (stationarity), `mmc_wait_time` (Poisson arrivals) |
| `finite_diagnostic` | a measurement or a trace-bounded check | `audit_key_safety`, `latency_percentiles` |

This exists because the project caught itself violating it: an early draft
tiered one closure (M/M/c) correctly and left four others unflagged next to
it in the same document. The registry makes that mistake structurally
impossible to repeat by omission — `fra.describe()` refuses to answer for an
unregistered kind.

## What's in here

### `fra.core` — the cost model, the certificate, the audits

- **`CostModel`** — `break_even_alpha()`, `speedup()`, `max_speedup_ceiling()`.
  The ceiling is a **strict finite bound** (`S_Q < c_f/c_o` for every trace
  with `N≥1, K≥1, c_m≥0`), not the paper's asymptotic `K_N/N → 0` statement —
  proved in Coq with no induction needed (see `formal/`).
- **`audit_key_safety()`** — turns the paper's Definition 1
  (`ker(Q) ⊆ ker(g)`, a cache key must never merge two responses that differ)
  into a runnable check, **with a mandatory coverage precondition**: a PASS
  only counts as `trustworthy_pass` when every declared (role × service × …)
  combination was actually exercised by the trace. Without this, a key bug on
  an untested code path produces a real, reproducible false PASS — verified
  directly in `tests/test_key_safety_coverage.py`.
- **`Certificate`** — separates a *declared* error bound (Corollary 1:
  `δ = L·r_Q`) from the *observed* max/mean over a sample. A mean is never
  presented as a certificate.
- **`BreakEvenGuard`** — monitors the observed distinct-key ratio online and
  disables a quotient when the trace drifts past break-even, instead of
  silently turning a win into a loss.
- **Five Layer-B deploy audits** (`require_guard_audit`, `atomic_deploy_audit`,
  `frozen_data_audit`, `php_parse_gate`, `route_smoke_test`) plus
  `metric_staleness_check` and `silent_zero_collapse_audit` — each tested
  against the *specific* incident shape it is named after, with a check that
  it does **not** false-positive on the fixed version of the same code
  (`tests/test_layer_b_audits.py`).
- 15 further closures: percentile statistics, SLO/error-budget arithmetic,
  staleness/payload bounds, Little's Law, M/M/c waiting time, index
  selectivity (post-hoc vs. predictive) — each tiered honestly, several
  deliberately marked `Dr` because the paper's original proposal listed them
  as exact without saying so.

### `fra.cache` — BEVE (Break-Even Value Eviction)

A cache eviction policy whose **admission rule reuses `ceiling_strict`
directly** (Coq-backed): a key is never admitted unless `c_f > c_o`, closing
off a guaranteed slowdown before it can happen. Eviction-among-cached-keys is
a GDSF-style cost×frequency score — a known technique (Cao & Irani, 1997),
not claimed as novel; only the admission rule and the whole-cache
`BreakEvenGuard` wiring are this project's own contribution.

Tested both ways, honestly:

- **Wins** on a workload with real heterogeneous per-key cost (the ARAYA
  measurement below): 19% lower total cost than LRU, 4% lower than LFU.
- **Loses** on a workload built specifically to break it (strong temporal
  locality, near-flat cost signal): 7% *worse* than plain LRU. This negative
  result is asserted in `tests/test_beve_cache.py`, not hidden — if it ever
  starts passing, the test's premise needs revisiting, not celebrating.

### `fra.histogram` — FRAHistogram / FRAHistogramLog

A fixed-memory streaming quantile sketch with an **exact worst-case error
bound that needs no estimated constant** — sidestepping the failure mode that
hit `lipschitz_delta` when fed an estimated Lipschitz constant (a declared
bound the data itself violated at 3 of 4 tested resolutions).

Building it surfaced a real design mistake, kept in the repo rather than
hidden: the first (linear-bucket) design lost badly at the median/p90 on
power-law data, because uniform bucket width wastes resolution across the
whole declared range while the data concentrates near one end (the median
fell inside a single giant bucket). Switching to **log-scale buckets** (the
same fix HdrHistogram uses in production) fixed exactly that — see
`tests/test_histogram.py::test_log_scale_recovers_the_quantiles_linear_design_broke`.
At the single most extreme quantile (p999) the two designs can trade places
by chance on a given draw; that specific comparison is noisy and is not
asserted as a general win either way.

Honest trade-off: needs a declared value range up front (t-digest and
reservoir sampling do not), and at very tight memory on a low quantile,
reservoir sampling's density-adaptive sampling still wins — this is not
claimed to universally beat either alternative.

### `formal/` — Coq, axiom-free over ℚ

Five theorems, each checked with `Print Assumptions` → *"Closed under the
global context"*: `break_even_iff` (the break-even condition as a genuine
iff), `ceiling_strict` (the strengthened Prop 1), `injective_key_slowdown`
(an injective key is a strict slowdown, not just a wash), `hit_rate_bounds`
(0 ≤ H ≤ 1), `bottleneck_ceiling`. None of them need induction over N or K —
they are chains of ordered-field inequalities over ℚ.

```bash
cd formal && ./verify.sh
```

### `examples/`

- `benchmarks.py` — the original E1–E6 experiments: does the framework
  actually pay off, is the win about cost or about "continuum-heaviness"
  (it's cost), does mean error hide a 20–28× worse max, does RAG quotient
  need an exact rerank stage (yes — answer-reuse by embedding quotient
  fails; IVF-candidates-plus-rerank gets 18× at 0.92 recall), does an
  unmonitored quotient silently become a loss under drift (yes, 0.90×,
  unreported without a guard).
- `araya-readout-cache.php` — a WordPress cache implementation sketch.
  **Illustrative only. Not deployed. Not `php -l`-checked** (no PHP binary
  was available in the environment that wrote it) — do not use as-is.

## One real measurement (not a benchmark)

Read-only `?zz=<random>` probes against a live WordPress site
(2026-07-30), forcing a full render bypass with no cache write:

```
c_f (full render)     = 1.34s
c_o (cache hit)        = 0.137s
break-even K/N         = 0.898
theoretical ceiling     = 9.8x
achieved (page cache)   = 9.9x   -- already at the ceiling
WordPress bootstrap     = 1.13s = 83% of every uncached request
ceiling on any further page-level optimisation = 1.20x
```

Reading: the existing page cache is already at its theoretical limit. The
only lever with more than 1.2× of headroom left is the WordPress bootstrap
itself (autoloaded options, object-cache coverage, hook count before
`init`) — not anything this library's cache layer can address.

## What this is not

- Not a claim that quotienting is always faster — `max_speedup_ceiling()`
  returns a **ceiling of 0** (refuses) whenever `c_f ≤ c_o`, and one of the
  six original benchmark cases (`examples/benchmarks.py`) is a deliberate
  negative result: a cheap computation slowed to 0.68–0.71× under the same
  quotient pipeline.
- Not a claim that BEVE or FRAHistogram are universally better than the
  established alternatives they are compared against (GDSF/LRU/LFU,
  reservoir sampling/t-digest) — see the honest losses documented above and
  in their respective test files.
- Not independently peer-reviewed. The tier discipline exists so a reader can
  check the claim at the level it was actually earned, rather than trust the
  library's own framing.

## Contributing

See `CONTRIBUTING.md` — the short version: pick a tier honestly, back every
claim with a test in the same PR, no direct pushes to `main` (branch
protection enforces this, including for maintainers).

## Provenance of this repository

Developed by Yaoharee Lahtee with AI-assisted engineering (design, code,
adversarial review, and testing). The founder is responsible for the core
ideas, the claims made, and their limits; see `LICENSE` (MIT).
