# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Tiers
referenced below (`EXACT`/`Dr`/`finite_diagnostic`) are defined in
`README.md` and enforced by `fra.core.register_closure`.

## [Unreleased]

### Added
- Governance: `CONTRIBUTING.md`, PR/issue templates, branch protection on
  `main` (required status checks: `pytest`, `install`, `coq`; no direct
  pushes), Dependabot for GitHub Actions.

## [0.1.0] - 2026-07-31

Initial release.

### Added
- `fra.core.CostModel` — `break_even_alpha`, `speedup`,
  `max_speedup_ceiling` (a strict finite bound, no limit taken).
- `fra.core.audit_key_safety` — cache-key safety linter with a mandatory
  coverage precondition (`trustworthy_pass`); a PASS without full coverage
  is explicitly flagged as uncertified rather than trusted.
- `fra.core.Certificate` — separates a declared error bound from an
  observed max/mean; a mean is never presented as a certificate.
- `fra.core.BreakEvenGuard` — online monitor that disables a quotient when
  the observed distinct-key ratio drifts past break-even.
- Six Layer-B audits, each tested against a named real incident shape:
  `require_guard_audit`, `atomic_deploy_audit`, `frozen_data_audit`,
  `php_parse_gate`, `route_smoke_test`, `metric_staleness_check`, plus
  `silent_zero_collapse_audit` (extracted from an external synthesis note —
  see `DESIGN_NOTES.md`).
- 15 further closures (percentiles, SLO/error-budget arithmetic,
  staleness/payload bounds, Little's Law, M/M/c, index selectivity in both
  post-hoc and predictive form) — each tiered honestly; several marked
  `Dr` on purpose.
- `fra.cache.BEVECache` — cache eviction whose admission rule reuses
  `ceiling_strict` directly (Coq-backed); tested to both win (heterogeneous
  per-key cost) and honestly lose (adversarial locality) against LRU/LFU.
- `fra.histogram.FRAHistogram` / `FRAHistogramLog` — streaming quantile
  sketch with an exact, non-estimated worst-case bound; includes the
  linear-bucket design mistake found while building it and the log-scale
  fix, both kept in the test suite.
- `formal/FRA_Closures.v` — 5 Coq theorems, axiom-free over Q:
  `break_even_iff`, `ceiling_strict`, `injective_key_slowdown`,
  `hit_rate_bounds`, `bottleneck_ceiling`.
- CI: `pytest`, `install` (wheel build + import from outside the source
  tree), `coq` (pinned to Coq 8.20).
- One real measurement: read-only probes against a live WordPress site
  (2026-07-30) establishing `c_f=1.34s`, `c_o=0.137s`, and that the site's
  existing page cache is already at its theoretical ceiling (9.9x measured
  vs 9.8x ceiling).
