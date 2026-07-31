# Design notes: what was extracted from an external "Semantic Number" synthesis

An external note proposed a "Semantic Number" type system for web APIs — a
tagged union (`observed | below_resolution | missing | undefined | failed |
imputed`) to stop a bare `0` from silently absorbing several different real
states, plus a "propagation algebra" for how these tags combine under
arithmetic, plus a compiler/linter that forbids silent collapse (`?? 0`,
`|| 0`, `COALESCE(x, 0)`) without a declared policy.

## What was audited, and the verdict

Most of the proposal restates existing, well-established work rather than
contributing something new:

- The core idea (nulls need explicit semantics, not silent defaults) goes back
  to Imieliński & Lipski (1984) on incomplete information in relational
  databases.
- "Where did this value come from and why" is exactly data provenance
  (Buneman, Khanna & Tan 2001; Green, Karvounarakis & Tannen 2007 on
  provenance semirings; Cheney, Chiticariu & Tan 2009).
- "A value below a detection limit is not zero" is standard practice in
  measurement statistics (censored/truncated distributions).
- Refinement types enforcing this in a real type system already exist
  (Vekris, Cosman & Jhala 2016, refinement types for TypeScript).

None of this was independently re-derived or newly proven here — it was read,
checked against known literature, and NOT declared novel. The instruction to
avoid claiming false originality (see the project's standing rule against
proposing external validation as a legitimacy lever, and against overclaiming
generally) applies directly: a full "Semantic Number" algebra is a much larger
claim than this session verified, and is not implemented in this repository.

## What WAS extracted and actually built

One piece of the proposal is concretely actionable inside this repository's
own existing pattern (a source-level, regex-decidable audit, same shape as
`require_guard_audit` and `frozen_data_audit`):

**`fra.silent_zero_collapse_audit(source)`** — flags `?? 0`, `|| 0`,
`COALESCE(x, 0)`, and PHP's `isset(...) ? ... : 0` when no `collapse-ok: `
comment declares the default as intentional. Tier `finite_diagnostic`, tested
against real bug shapes and a correctly-annotated exception in
`tests/test_layer_b_audits.py`.

## Convergence worth noting (not claiming as new)

Two structures already in this codebase, built **before** the external note
was read, independently implement its central idea for this project's own
booleans:

- **`AuditFinding.status`** is a four-state tag (`PASS | FAIL | HOLD |
  UNDECIDABLE`), never collapsed to a boolean. `HOLD` specifically exists for
  "the check could not be performed" (e.g. `php_parse_gate` when no `php`
  binary is available) — the exact "don't silently pick a default when the
  real state is unknown" principle the proposal argues for, applied to a
  audit outcome rather than a number.
- **`SafetyReport.trustworthy_pass`** distinguishes "no violation was
  observed" (`exact_safe`) from "this PASS may actually be trusted"
  (`trustworthy_pass`, which additionally requires complete coverage). A bare
  `True` was itself ambiguous between "verified safe" and "never tested" —
  the same collapse-to-primitive failure the proposal describes, just for a
  boolean instead of a number.

This is presented as evidence the *pattern* (tag the state, don't collapse it)
generalises usefully — not as evidence either instance was inspired by or
needs the external proposal's specific type system to exist.

## What was deliberately NOT adopted

- The full tagged-union `SemanticNumber` type and its arithmetic propagation
  algebra. This is a much larger design commitment (touching every arithmetic
  operation across a whole system) than a single audit function, unproven at
  the scale claimed, and out of scope for an engineering library about
  caching and readout quotients specifically.
- The "dual-plane database" storage architecture proposal. Plausible, but a
  storage-layer redesign is a different project with different stakeholders,
  not something to bolt onto a caching library.
- Any claim that this synthesis is "world-first" or globally novel — the
  proposal's own citation list already shows it is not, and this project's
  own tier discipline forbids asserting a tier the evidence has not earned.
