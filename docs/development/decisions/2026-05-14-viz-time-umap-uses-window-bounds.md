# Decision: `plot_time_umap` colours by `0.5 * (start_timepoint + end_timepoint)`

- **Date:** 2026-05-14 (UTC)
- **Status:** Accepted
- **Owner / decider:** Implementer A1 + Phase 6 orchestrator

## Context

TNBC Figure 2c colours the UMAP scatter by the **per-window average
wall-clock time** of each window. The reference implementation
(`reference/01_abm_generate_embedding.py:279-322`) computes this by
indexing into a 2D `time(simulation, timepoint)` coord and averaging the
`window_size` timestamps inside each window.

That 2D `time` coord exists in the Phase 3 (summarise) output but is
*not* propagated through Phase 4 (embedding) to the cluster Zarr that
Stream A reads:

> `src/tmelandscape/embedding/__init__.py:240` skips multi-dim coords
> when broadcasting per-simulation metadata onto the per-window axis.

A1's options for `plot_time_umap`:

1. Walk back to the upstream Phase 3 ensemble, re-load its 2D `time`
   coord, and join on `(simulation_id, start_timepoint..end_timepoint)`.
2. Compute the per-window mean directly from the per-window
   `start_timepoint` / `end_timepoint` coords that Phase 4 *does*
   propagate: `0.5 * (start + end)`.

## Options considered

### Option A — Round-trip through the Phase 3 ensemble to recover wall-clock time

- Pros: exact reproduction of the reference figure including
  wall-clock-minute units; tolerant of irregular timestep cadence (sims
  that emit at non-uniform intervals).
- Cons: introduces a Phase-3 dependency on a Phase-6 viz function; the
  function signature would need to take *two* paths (cluster Zarr +
  Phase-3 ensemble) or implicitly resolve one from the other via a
  provenance attr; not all cluster Zarrs will live next to the
  originating Phase-3 store on disk.

### Option B — Compute the per-window midpoint from the propagated bounds

- Pros: function signature stays at one input path (the cluster Zarr);
  every cluster Zarr produced by the pipeline carries `start_timepoint`
  and `end_timepoint` per-window coords (Phase 4 invariant); the result
  is monotonic in physical time when timesteps are uniform.
- Cons: units are *timepoint index*, not minutes; on irregular-cadence
  sims, the midpoint of indices is not the midpoint of wall-clock time
  (information lost by Phase 4's coord-skip).

### Option C — Add a `mean_time_per_window` coord to Phase 4's output

- Pros: removes the trade-off; downstream viz reads a single canonical
  scalar per window.
- Cons: cross-phase scope creep — would re-open Phase 4 (v0.5.0 already
  shipped) to add a new coord, exercise its provenance forwarding,
  re-validate against the reference. Disproportionate cost for a
  visual-only consumer.

## Decision

**Option B** for v0.7.0. The function docstring explicitly states that
the colour axis is in *timepoint-index units*, not minutes. If a future
need arises for true wall-clock minutes (e.g. for a TNBC-2c reproduction
where the figure's axis carries minute units), Option C can be revisited
as a Phase 4 amendment in v0.7.x.

## Consequences

- **No code change needed** beyond what A1 shipped.
- **`plot_time_umap` docstring** clearly names the unit ambiguity (verified
  in Stream A — line ~250-280 of `viz/embedding.py`).
- **Forward-compatibility hook:** if Phase 4 later adds a
  `mean_time_per_window` coord, `plot_time_umap` can check for it and
  prefer it when present, falling back to `0.5 * (start + end)` for
  legacy stores.
- **Test:** A1's `test_plot_time_umap_colour_values_match_mean_time`
  pins the current formula. If Option C is ever adopted, this test
  updates accordingly.
- **Reversibility:** trivial — one expression change inside the function
  body if Option A or C is preferred later.

## References

- Implementer A1 Wave-1 report (Phase 6 Stream A).
- Reviewer A2 Wave-2 findings (SMELL S4).
- `src/tmelandscape/embedding/__init__.py:240` — the
  multi-dim-coord-skip in Phase 4 that motivated this decision.
- `reference/01_abm_generate_embedding.py:279-322` — the reference
  implementation that uses the 2D `time` coord directly.
