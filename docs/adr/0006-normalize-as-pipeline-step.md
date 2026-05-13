# 0006 — Normalization is a discrete pipeline step (`tmelandscape.normalize`)

- **Status:** Accepted
- **Date:** 2026-05-12
- **Deciders:** Eric, Claude

## Context

Phase 1 reference audit (see `tasks/00-reference-audit.md`) surfaced that the upstream landscape-generation pipeline includes a **normalization step between summarization (step 3) and embedding (step 4)** that the original development plan omitted. The reference oracle (`reference/00_abm_normalization.py`) does:

1. Drop six cell-density feature columns. *(Application-specific; not a property of the algorithm. See "Update 2026-05-13" below.)*
2. Group rows by `time_step`; compute per-step feature means.
3. Apply `sklearn.preprocessing.PowerTransformer` per time step.
4. Z-score normalize the result.
5. **Re-add the original per-time-step mean** to preserve the temporal trend (so that embedding sees a normalized-around-the-trend signal, not a flat zero-mean signal).

This is non-trivial: it intentionally violates the usual "normalize then forget the mean" practice in order to keep the temporal structure that the time-delay embedding will exploit. Folding this into `summarize` or `embedding` would hide an architecturally important decision inside an unrelated module.

## Decision

Add a top-level `tmelandscape.normalize` submodule positioned between `summarize` (step 3) and `embedding` (step 4). Layout:

```
src/tmelandscape/normalize/
├── __init__.py
├── within_timestep.py    # default reference algorithm
├── feature_filter.py     # configurable column drop (6 density cols by default)
└── alternatives.py       # global / local-time / feature-distribution variants
```

Surface it as a discrete CLI verb (`tmelandscape normalize`) and MCP tool (`tmelandscape.normalize_ensemble`). Update the ROADMAP to insert a Phase 3.5 between Phases 3 and 4.

## Consequences

- Normalization is independently testable, swappable (multiple strategies), and visible in pipeline logs / provenance.
- The Zarr ensemble store grows a `normalized` variant alongside the raw `summary` variant — both are kept so users can re-run normalization without re-running summarization.
- Re-adding the mean is unusual and will surprise readers; the algorithm is documented in `docs/concepts/normalize.md` with a citation to the reference oracle.
- Optional dependencies stay minimal: `scikit-learn` is already a core dep for `PowerTransformer` / `StandardScaler`.

## Alternatives considered

- **Fold into `summarize`:** would couple two concerns and hide normalization from the public surface; rejected.
- **Fold into `embedding`:** worst separation; the embedding step should consume already-prepared inputs.
- **Apply per-feature globally (not per-time-step):** simpler but loses the per-timestep mean-preservation that the reference uses to keep temporal trend information available to the delay embedding.

## Update 2026-05-13 (project owner direction)

Two binding invariants for the Phase 3.5 implementation, recorded here so they survive the gap between this ADR and the eventual `normalize_ensemble` code:

1. **Never overwrite the raw ensemble.** Normalisation always writes to a new variable in the existing Zarr store, or to a new Zarr file. The raw output of step 3 is immutable. This lets users re-run normalisation with different strategies without re-running step 3. Decision is the project owner's (Eric, 2026-05-13).
2. **Drop no features by default.** The reference's "drop the six cell-density columns" step was specific to the LCSS-paper application, not a property of the algorithm. The default `normalize_ensemble` behaviour is to operate on every column the user supplies; column dropping is an explicit opt-in (`drop_columns: list[str] = []`). See [ADR 0009](0009-no-hardcoded-statistics-panel.md) for the parallel decision on the summarisation panel.
