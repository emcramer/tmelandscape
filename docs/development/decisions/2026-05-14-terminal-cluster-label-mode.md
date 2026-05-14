# Decision: terminal cluster label is the mode of the last N windows

- **Date:** 2026-05-14 (UTC)
- **Status:** Accepted
- **Owner / decider:** Stream C Implementer (Claude Code) for the Phase 6 orchestrator

## Context

`tmelandscape.landscape.join_manifest_cluster` is the Phase 6
prerequisite that joins the Phase 2 sweep manifest (per-simulation
sampled parameters) with the Phase 5 cluster Zarr (per-window labels).
The two parameter-state figures (LCSS-6 attractor basins, TNBC-6c
parameter-by-state violins) need exactly one *terminal* cluster label
per simulation.

The frozen contract (in the implementer brief) names the helper but is
non-committal on **how** to collapse the trajectory of window labels
down to a single terminal label. The implementer note recommends "the
mode of `cluster_labels` over the last `terminal_window_count` windows
of the sim" — the implementer brief writes:

> Group `cluster_labels` by `simulation_id`, sort by
> `window_index_in_sim` within each group, take the **mode** of the
> last `terminal_window_count` labels. Use `scipy.stats.mode` or
> `pandas.Series.mode().iloc[0]`.

But that recommendation itself was a hint, not the contract; the brief
explicitly flagged the choice as a decision-log candidate:

> **Strong recommendation:** write a decision-log entry when you pick
> the BH-FDR implementation (statsmodels vs. hand-rolled), and when you
> pick the join strategy for terminal cluster labels (mode vs. argmax
> over last N windows).

This entry captures the strategy choice.

## Options considered

### Option A — Mode of the last N window labels (the recommended path)

- Pros:
  - **Robust to single-window noise.** If a single window flickers into
    a transient state at the very last timepoint, the mode of the
    trailing window slab ignores it.
  - **Cheap.** One `pandas.Series.mode()` per sim.
  - **Matches the LCSS/TNBC manuscripts' implicit definition of an
    "attractor"**: a state the trajectory dwells in for the final
    portion of the trajectory.
  - **Tunable.** `terminal_window_count` defaults to 5, but a user with
    a longer simulation horizon or noisier labels can dial it up.
- Cons:
  - The mode is technically discrete; on a perfect tie it returns the
    smallest-valued label (pandas convention). For two-way ties this is
    deterministic but arbitrary.
  - Loses information about the *dwell fraction* — a trajectory that
    spends 3 of the last 5 windows in state 7 and 2 in state 3 is
    labelled identically to one that spends 5 in state 7.

### Option B — Argmax over the last N windows (dwell-weighted)

- Pros:
  - Could weight windows by elapsed-time-in-state rather than raw count
    if a future version adds per-window durations.
- Cons:
  - For uniform-width windows (which Phase 4 guarantees), argmax and
    mode are mathematically identical. The "argmax over windows" framing
    in the brief refers to counting occurrences of each label in the
    slab and picking the most-common — which is exactly the mode.
  - More verbose to implement; no semantic gain.

### Option C — Last window's label only

- Pros:
  - Trivial.
- Cons:
  - Fragile under last-window noise. A trajectory that converged to
    state 7 across windows 6-19 but flickered to state 3 at window 20
    would be mislabelled.
  - Equivalent to Option A with `terminal_window_count=1`, which
    callers can opt into anyway.

### Option D — Stationary-distribution-based terminal labelling

- Pros:
  - Information-theoretically principled.
- Cons:
  - Requires running an MSM, which is explicitly out of v1 scope per
    [ADR 0005](../../adr/0005-no-msm-in-v1.md).

## Decision

**Option A — mode of the last `terminal_window_count` windows, default 5.**

Implementation: in `join_manifest_cluster`, after sorting windows
within each sim by `window_index_in_sim`, take the trailing slab and
call `pandas.Series.mode().iloc[0]`. The 0-th element picks the
smallest-valued tied label, which is deterministic.

`terminal_window_count=1` is a supported boundary case (returns the
last window's label, equivalent to Option C); `< 1` raises
`ValueError` to prevent the silently-empty-slab pathology.

Reasoning:

- Matches the implementer brief and the contract on which the figure
  layer was built.
- Robust to single-window flicker, the canonical concern when reading
  trajectories at the trajectory tail.
- Cheap, one-pass per sim.
- Argmax-over-uniform-width-windows is mathematically identical to
  the mode, so picking "mode" loses no semantic ground.

## Consequences

- **Code change applied:** `join_manifest_cluster` in
  `src/tmelandscape/landscape/__init__.py`. The terminal label
  computation is six lines inside the per-sim group-by loop.
- **Downstream impact:** every Phase 6 figure that consumes the joined
  DataFrame (TNBC-6c, LCSS-6) inherits this strategy. Tests in
  `tests/unit/test_landscape_join.py` cover:
  - mode is taken (not the last label) — `test_terminal_label_is_mode_of_last_n_windows`,
  - `terminal_window_count=1` falls back to the last label —
    `test_terminal_window_count_one_returns_last_label`,
  - the join is robust to shuffled physical Zarr row order —
    `test_join_is_robust_to_shuffled_window_order`.
- **New work this implies:** if a future figure needs the per-state
  dwell fraction rather than the bare mode, add a second helper
  function (e.g. `join_manifest_cluster_with_dwell`) rather than
  changing this one's contract.
- **Reversibility:** the helper is the only consumer of the strategy.
  Switching strategies later is a localised edit.

## References

- Task file: `tasks/07-visualisation-implementation.md` (Phase 6
  prerequisite — Stream C)
- ADR 0005: `docs/adr/0005-no-msm-in-v1.md`
- Code: `src/tmelandscape/landscape/__init__.py::join_manifest_cluster`
- Tests: `tests/unit/test_landscape_join.py`
