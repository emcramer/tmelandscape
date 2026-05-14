# Decision: don't plan for tissue_simulator / spatialtissuepy on PyPI

- **Date:** 2026-05-14 (UTC)
- **Status:** Accepted
- **Owner / decider:** Eric

## Context

ADR 0008 (dependency pin policy) was written assuming an eventual
migration of the two single-author upstreams (`tissue_simulator`,
`spatialtissuepy`) to PyPI before tmelandscape v1.0 ships. The ADR
included language like "Target: both packages on PyPI before
tmelandscape v1.0 ships" and a "Once upstreams ship to PyPI, this ADR is
largely retired in favour of the standard semver dependency style"
clause.

At the v0.6.0 handoff (2026-05-14), the project owner clarified that
**this is not a goal**:

> We might never move those packages to pypi. Don't plan for it. If it
> happens, I will update you and we can re-pin to pypi.

## Options considered

### Option A — Leave ADR 0008 as-is

- Pros: zero churn; the goal language is aspirational and harmless.
- Cons: misleading to a new reader; sets an expectation that doesn't
  match the owner's intent; future agents may try to "make progress"
  toward the PyPI goal unnecessarily.

### Option B — Edit ADR 0008 to drop the PyPI-target language

- Pros: ADR matches the owner's actual position; no agent will be
  surprised by the indefinite-git-pin plan; the pin policy itself
  (tag-based git pins) is unchanged.
- Cons: editing an accepted ADR rather than superseding it. We do not
  yet have a "supersede" convention in `docs/adr/` for cases this small.

## Decision

**Option B, with a "Status: Accepted (revised 2026-05-14)" annotation.**
The ADR's core decision (tag-based git pins) remains the same; only the
PyPI-as-eventual-target language is removed. We also add a short
"Long-term plan" section noting that PyPI is *not* a goal and would be
revisited only on explicit owner direction.

## Consequences

- **ADR 0008** updated in this commit.
- **No code change.** Git+tag pinning is already the active state
  (`tissue_simulator@v0.1.4`, `spatialtissuepy@v0.0.1`).
- **Reversibility:** trivial — if the upstreams ship to PyPI, the
  policy can be revised in a follow-up ADR (call it 0008-amend or a new
  number).

## References

- [ADR 0008 — Dependency pin policy](../../adr/0008-dependency-pin-policy.md)
- Owner directive: 2026-05-14 transcript ("We might never move those
  packages to pypi. Don't plan for it.")
