# AGENTS.md - finite-readout-acceleration

## What this repository is

An implementation and engineering companion to Yaoharee Lahtee (2026), *"What a Finite Readout Need
Not Compute: A Quotient Framework for Immediate Acceleration in Web, Cache, Database, and Vector
Systems."* It turns the paper's rule into code: a cost model, a break-even guard, a coverage-audited
cache-safety linter, five production deploy-safety audits, and two algorithms derived from the
paper's theorems (a cost-aware cache eviction policy and a streaming quantile sketch).
Status: alpha. Built and tested against synthetic workloads plus one real site measurement; not yet
used in a production deploy pipeline. The README states that this is not a claim that quotienting is
always faster, not a claim that BEVE or FRAHistogram are universally better than the established
alternatives they are compared against, and that the work is not independently peer-reviewed.

## Read first

1. `README.md` - scope, the tier discipline, the "What this is not" section.
2. `DESIGN_NOTES.md` - design notes: what was extracted from an external "Semantic Number" synthesis.
3. `CONTRIBUTING.md` - the tier discipline and workflow in full.

## Rules

These are the rules `CONTRIBUTING.md` already states; this file adds none of its own.

- Do not overclaim.
- A new or changed closure or audit is registered with `register_closure(name, tier, ...)`, tier
  one of `EXACT`, `Dr`, `finite_diagnostic`. Ordinary helpers (`kinds`, `describe`, `timed`, and
  similar) are not closures and need no tier. Pick the tier honestly; a `Dr`-tier closure needs its
  assumption written in the docstring and passed to `assumption=` (both).
- A claim in `README.md` (a number, a "wins/loses" statement, a comparison) must be backed by a
  test in the same PR.
- Branch, PR, merge. No direct pushes to `main`. One logical change per PR.
- No new dependency: the library is stdlib-only by design (Coq is used only for `formal/`).

## Programme map

This repository is one node of the Human-AI Readout Programme. Which repository answers which kind of
question, what to read first and which gate applies is kept in one place, the routing hub:
<https://github.com/morrocwi/main.hub> (start at its `AGENTS.md`, then `ROUTES.md`).
The hub holds pointers and pinned links only. It is a readout of one moment: when the hub and this
repository disagree, this repository wins.
