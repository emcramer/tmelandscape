# Decision: rename `viz.embedding.plot_*` first parameter from `umap` to `umap_result`

- **Date:** 2026-05-14 (UTC)
- **Status:** Accepted
- **Owner / decider:** Implementer A1 + Reviewer A2 + Phase 6 orchestrator

## Context

The Phase 6 task file froze the API for Stream A's plot functions with the
first positional parameter typed as `umap: UMAPResult`. Implementer A1 hit
a name collision: `viz/embedding.py` also does `import umap` (the UMAP
library), so a parameter named `umap` shadows the module-level import
inside the function body, making `umap.UMAP(...)` lookups inside
`fit_umap` problematic. A1 renamed the parameter to `umap_result` and
documented the deviation in their Wave-1 report.

Reviewer A2 flagged this as SMELL S1 with the note: either revert to honour
the frozen contract or acknowledge with a decision-log entry.

## Options considered

### Option A — Revert to `umap: UMAPResult`; alias the library import as `umap as umap_lib`

- Pros: contract drift avoided; first positional name matches the task
  file verbatim; future implementer prompts can quote the contract
  unchanged.
- Cons: aliasing a widely-recognised library import (`umap`) inside the
  one module that lives closest to UMAP makes the implementation file
  harder to navigate for someone scanning for canonical `umap.UMAP`
  usage; `umap_lib` is non-standard in the broader Python community.

### Option B — Accept `umap_result` as the new contract; update the task file

- Pros: parameter name is clearer for the caller (it's *what* gets passed,
  not *the library it came from*); library import stays canonical; no
  in-function shadowing risk; the typed-dataclass parameter conveys
  intent better than the library-namespace name.
- Cons: contract drift from the original task file; the frozen-API spec
  needs to be updated to match.

## Decision

**Option B.** The rename is preserved; the task file's frozen API is
updated to match (`umap_result: UMAPResult` as the first positional
parameter on all five `plot_*` functions in `viz.embedding`). Future
contract-quote material (reviewer prompts, integration code, docs) uses
the new name.

## Consequences

- **No code change needed** beyond what A1 already shipped.
- **Task file update:** `tasks/07-visualisation-implementation.md` — the
  Stream A Public API block is amended to read `umap_result: UMAPResult`
  rather than `umap: UMAPResult` for the five `plot_*` functions.
- **Reviewer prompts updated** in future phases that reference the same
  contract.
- **Downstream consumers** (integration tests, CLI/MCP tool wrappers in
  Wave 3) match `umap_result`.
- **Reversibility:** trivial — one find/replace if a future maintainer
  prefers the bare `umap` name (with the library aliased).

## References

- Implementer A1 Wave-1 report (Phase 6 Stream A).
- Reviewer A2 Wave-2 findings (SMELL S1).
- [`tasks/07-visualisation-implementation.md`](../../../tasks/07-visualisation-implementation.md)
