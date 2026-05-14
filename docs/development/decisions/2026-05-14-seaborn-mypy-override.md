# Decision: centralise the `seaborn.*` mypy override; remove per-import ignores

- **Date:** 2026-05-14 (UTC)
- **Status:** Accepted
- **Owner / decider:** Phase 6 orchestrator (Wave 3)

## Context

All three Phase 6 implementers (A1, B1, C1) hit the same mypy-strict
hurdle: `seaborn` ships no type stubs, so `import seaborn as sns`
triggers an `[import-untyped]` error under the project's strict mypy
configuration. Each implementer was instructed not to modify
`pyproject.toml`, so each one local-suppressed the warning with a
per-import `# type: ignore[import-untyped]`. All three reviewers (A2,
B2, C2) flagged this as a cross-stream SMELL recommending Wave-3
centralisation.

The pattern is exactly what the existing `[[tool.mypy.overrides]]`
block in `pyproject.toml` is for. The block already lists the other
stub-less library imports (`scipy`, `sklearn`, `kneed`, `igraph`,
`leidenalg`, etc.) per the v0.5.0 / v0.6.x decisions captured in the
[Phase 5 session log](./2026-05-14-phase-5-session.md#d7-centralise-mypy-overrides-in-pyprojecttoml).

## Options considered

### Option A — Centralise: add `seaborn.*` to `[[tool.mypy.overrides]]`; strip the per-import ignores

- Pros: single source of truth; consistent with how every other
  stub-less library is handled in this project; survives the
  `warn_unused_ignores=true` flag if seaborn ever ships stubs upstream.
- Cons: requires touching `pyproject.toml` (forbidden during Wave-1
  implementation but explicitly the orchestrator's job in Wave-3).

### Option B — Vendored stubs (`typeshed`-style local `seaborn-stubs/`)

- Pros: structurally cleanest; doesn't widen mypy's "missing stubs"
  blind spot.
- Cons: substantial maintenance burden (the project would have to keep
  hand-written stubs aligned with seaborn versions); overkill for a
  small handful of call sites; nothing in the project uses this pattern
  yet so the precedent would be new.

### Option C — Single shim module (`viz/_seaborn_compat.py`)

- Pros: contains the suppression in one file; downstream call sites
  import from the shim, not seaborn directly.
- Cons: adds an indirection layer for no gain over Option A; doesn't
  follow the existing pattern.

## Decision

**Option A.** `seaborn.*` is added to the existing `[[tool.mypy.overrides]]`
block. The three per-import `# type: ignore[import-untyped]` comments
in `viz/embedding.py`, `viz/trajectories.py`, and `viz/dynamics.py` are
removed. mypy strict mode verifies that the unused ignores would
trigger `warn_unused_ignores` if they were left in.

## Consequences

- **`pyproject.toml`** gains one line in the `[[tool.mypy.overrides]]`
  module list: `"seaborn.*"`. The existing comment block in that
  section already explains the policy.
- **Three source files** each drop a trailing `  # type: ignore[import-untyped]`
  on the `import seaborn as sns` line.
- **Reversibility:** trivial — re-add the ignores and drop the
  override line. Would only happen if seaborn ships stubs and the
  project decides to consume them.
- **Future Phase 7+ implementers**: when adding a new stub-less
  dependency, prefer Option A (extend the override list) over per-import
  ignores. This decision is the precedent.

## References

- Reviewer A2 SMELL S2, Reviewer B2 SMELL (cross-stream), Reviewer C2
  SMELL S1 — all three identified the same pattern.
- [Phase 5 session log decision D7](./2026-05-14-phase-5-session.md) —
  the original centralisation move; this entry extends it.
- `pyproject.toml` `[[tool.mypy.overrides]]` block — single source of
  truth for stub-less imports.
