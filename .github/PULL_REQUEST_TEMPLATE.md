## What changed and why

<!-- One or two sentences. Link an issue if there is one. -->

## Tier checklist (delete if this PR touches no closure/audit)

- [ ] New/changed closure is registered with `register_closure(name, tier, ...)`
- [ ] If tier is `Dr`, the `assumption=` string is present and matches the docstring
- [ ] If it's an audit, it is tested against a named, concrete failure shape
      (not just a synthetic "bad input" case)
- [ ] The audit test also checks it does NOT false-positive on the fixed version
      of the same code

## Claim checklist (delete if this PR adds no claim to README/DESIGN_NOTES)

- [ ] Every number/comparison stated in prose has a test backing it in this PR
- [ ] If the change compares against an alternative (LRU, reservoir sampling, ...),
      the comparison is under an equal, stated resource budget
- [ ] If there's a case where this loses, that case is reported, not omitted

## Verification

- [ ] `pytest -q` passes locally
- [ ] `cd formal && ./verify.sh` passes locally (skip if this PR doesn't touch `formal/`)
