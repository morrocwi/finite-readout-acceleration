# Contributing

Thanks for considering a contribution. This repo has one rule that overrides
normal open-source instincts: **do not overclaim.** Everything below exists to
make that checkable rather than a matter of trust.

## The tier discipline (read this before adding a closure or audit)

Every function in `fra.core` is registered with `register_closure(name, tier,
...)`. There are three tiers:

- `fra.EXACT` — a rational-arithmetic identity or inequality, given measured
  inputs, with no model assumption anywhere in the derivation.
- `fra.DR` — exact **under a stated assumption** (e.g. Poisson arrivals,
  stationarity, column independence). `register_closure` raises `ValueError`
  if you try to register a `DR`-tier closure without an `assumption=` string —
  this is enforced, not a style guideline.
- `fra.FINITE_DIAGNOSTIC` — a measurement or a trace-bounded check. It
  certifies what was observed, never a universal absence.

If you add a new closure or audit:

1. Pick the tier honestly. If you are not sure whether it needs a model
   assumption, it probably belongs in `DR`, not `EXACT`.
2. Write the assumption down in the docstring AND pass it to `assumption=` if
   the tier is `DR` — both, not just one.
3. If it's an audit (returns `AuditFinding`), test it against a **named,
   concrete failure shape** — not just "should return FAIL on bad input" but
   the actual incident/bug pattern it is meant to catch, plus a check that it
   does **not** false-positive on the fixed version of the same code. See
   `tests/test_layer_b_audits.py` for the pattern every existing audit
   follows.
4. If your change touches a claim in `README.md` (a number, a "wins/loses"
   statement, a comparison), the claim must be backed by a test in the same
   PR. A README claim with no test behind it is treated as a bug.

## Local setup

```bash
pip install -e . pytest
pytest -q                    # should be fast; no network, no GPU
cd formal && ./verify.sh     # needs Coq 8.20 (coqc, coq_makefile on PATH)
```

CI runs three jobs on every PR: `pytest`, `install` (wheel build + import
from outside the source tree), and `coq` (pinned to 8.20 via
`coq-community/docker-coq-action`, since that is the version
`formal/FRA_Closures.v` is verified against). All three must be green before
merge — this is enforced by branch protection on `main`, not just requested.

## Workflow

- Branch, PR, merge. No direct pushes to `main` (including from maintainers —
  branch protection applies to everyone).
- One logical change per PR. If a PR touches both a closure's math and an
  unrelated audit's regex, split it.
- If you disagree with an existing tier assignment (e.g. you think something
  marked `DR` is actually `EXACT`), open an issue with the argument — a tier
  downgrade needs no justification, a tier upgrade needs a proof or a
  citation.

## What NOT to send a PR for

- A claim that this library is faster/better than an alternative without a
  test that measures it, under the SAME memory/cost budget, with the losing
  case reported too if there is one (see how `tests/test_beve_cache.py` and
  `tests/test_histogram.py` handle this — both algorithms have a documented
  loss condition, on purpose).
- A new dependency. This library is stdlib-only by design (the Coq core is
  the only external tool required, and only for `formal/`).
