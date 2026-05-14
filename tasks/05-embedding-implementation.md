# 05 — Phase 4 embedding implementation

- **slug:** 05-embedding-implementation
- **status:** done (2026-05-13)
- **owner:** Claude Code orchestrator + 3 buddy-pair (Implementer / Reviewer) teams
- **opened:** 2026-05-13
- **closed:** 2026-05-13
- **roadmap link:** Phase 4 — Step 4 embedding (v0.5.0)

## Context

Step 4 of the pipeline: read the normalised ensemble Zarr from Phase 3.5
and build a time-delay (sliding-window) embedding. Each simulation
contributes one row of length `window_size * n_statistic` per window
position; rows are stacked across all simulations. The output is a new
Zarr at a user-supplied path containing the flattened embedding array
plus per-window metadata.

Reference oracle: `reference/utils.py::window_trajectory_data`
(lines 87-140). The reference processes a long-form DataFrame; this
implementation adapts the same algorithm to the package's 3D
`(simulation, timepoint, statistic)` Zarr shape.

## Binding invariants (from prior ADRs)

1. **Never overwrite raw data** (ADR 0006). Input Zarr is read-only;
   output path must not pre-exist. Tests verify byte-equality of input
   files before and after every call.
2. **No hardcoded defaults that the user can't see** (ADR 0009). The
   window size is required in the config (no silent default). The
   source variable defaults to `"value_normalized"` (the Phase 3.5
   output) since that is the natural input, but is overridable.
3. **No silent feature dropping**. If a sim has fewer timepoints than
   `window_size`, it contributes zero windows; the orchestrator emits
   a structured warning naming the affected sim ids.

## Algorithm summary (from the reference)

For each simulation `s` independently:

1. Take its `(n_timepoint, n_statistic)` slab.
2. Slide a window of length `W = config.window_size` along the
   timepoint axis with step `1`.
3. For each window position `i`:
   - Flatten the `(W, n_statistic)` submatrix to a length-`W * n_statistic`
     vector (row-major).
   - Compute the per-statistic mean across the window's `W` timesteps
     (the `avg_<stat>` companion array).
4. Skip the simulation if `n_timepoint < W`.

Concatenate the per-sim flattened windows across all simulations.

## Public API (frozen — every Implementer must match these signatures)

### Config — `tmelandscape.config.embedding`

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class EmbeddingConfig(BaseModel):
    """User-supplied configuration for `embed_ensemble`."""

    model_config = ConfigDict(extra="forbid")

    strategy: Literal["sliding_window"] = "sliding_window"
    window_size: int = Field(..., ge=1)            # REQUIRED, no default
    step_size: int = Field(default=1, ge=1)
    source_variable: str = Field(default="value_normalized", min_length=1)
    output_variable: str = Field(default="embedding", min_length=1)
    averages_variable: str = Field(default="window_averages", min_length=1)
    drop_statistics: list[str] = Field(default_factory=list)
```

- `window_size`: **required**, no default — the user picks W explicitly. The reference uses 50; the LCSS paper says "W ∈ {30, 50, 80}". No package default.
- `step_size`: how many timepoints to slide between windows. Default 1 matches the reference.
- `source_variable`: which data variable in the input Zarr carries the time series. Defaults to `"value_normalized"` (the Phase 3.5 output) but accepts any name.
- `output_variable`: name of the flattened embedding array in the output Zarr.
- `averages_variable`: name of the per-window per-stat means array in the output Zarr.
- `drop_statistics`: explicit list of statistic-coord values to drop before windowing. Default `[]` (no drops) per ADR 0009.

Validators:

- `output_variable`, `averages_variable` must not equal `source_variable` (would shadow it on dataset write).
- `output_variable` must differ from `averages_variable`.

### Algorithm — `tmelandscape.embedding.sliding_window`

```python
from dataclasses import dataclass
import numpy as np

@dataclass
class WindowedEnsemble:
    """Result of running sliding-window embedding over all simulations.

    Attributes
    ----------
    embedding
        ``(n_total_windows, window_size * n_statistic)`` float64 array.
        Each row is one flattened window.
    averages
        ``(n_total_windows, n_statistic)`` float64 array. Per-window
        per-statistic mean over the window's ``window_size`` timesteps.
    simulation_index
        ``(n_total_windows,)`` int array mapping each window back to its
        source simulation's position in the input's ``simulation`` dim.
    window_index_in_sim
        ``(n_total_windows,)`` int array of each window's offset within
        its source simulation (0, 1, 2, ...).
    start_timepoint
        ``(n_total_windows,)`` int array — first timepoint covered.
    end_timepoint
        ``(n_total_windows,)`` int array — last timepoint covered
        (inclusive).
    skipped_simulations
        Simulation indices that contributed zero windows because they
        had fewer than ``window_size`` timepoints.
    """

    embedding: np.ndarray
    averages: np.ndarray
    simulation_index: np.ndarray
    window_index_in_sim: np.ndarray
    start_timepoint: np.ndarray
    end_timepoint: np.ndarray
    skipped_simulations: list[int]


def window_trajectory_ensemble(
    value: np.ndarray,
    *,
    window_size: int,
    step_size: int = 1,
) -> WindowedEnsemble:
    """Build a sliding-window embedding from a 3D ensemble array.

    Parameters
    ----------
    value
        ``(n_sim, n_timepoint, n_statistic)`` float array. The 3D Zarr
        ``value`` cube. NaN entries (ragged sims, missing stats) are
        tolerated: NaN positions propagate into the flattened windows
        and into ``averages`` (via ``np.nanmean``).
    window_size
        Length of the sliding window in timepoints. Must be >= 1.
    step_size
        Number of timepoints between consecutive window starts. Must be
        >= 1. The reference uses 1.

    Returns
    -------
    WindowedEnsemble
        See dataclass docstring.
    """
```

Pure function: no I/O, no global RNG, deterministic.

### Zarr orchestrator — `tmelandscape.embedding.__init__`

```python
from pathlib import Path
from tmelandscape.config.embedding import EmbeddingConfig

def embed_ensemble(
    input_zarr: str | Path,
    output_zarr: str | Path,
    *,
    config: EmbeddingConfig,
) -> Path:
    """Read a normalised ensemble Zarr, build the sliding-window
    embedding, and write a NEW Zarr at ``output_zarr``.

    Refuses to overwrite an existing ``output_zarr``. Input is read-only.

    Output Zarr layout
    ------------------
    Dimensions:
        window
        embedding_feature  (= window_size * n_statistic)
        statistic          (= n_statistic, for the averages variable)
    Data variables:
        <output_variable>      shape (window, embedding_feature), float64
        <averages_variable>    shape (window, statistic),         float64
    Coordinates along `window`:
        simulation_id           string
        window_index_in_sim     int
        start_timepoint         int
        end_timepoint           int
        parameter_combination_id  int  (broadcast from input's `simulation` coord)
        ic_id                     int  (broadcast from input)
        parameter_<name>          float (broadcast from input)
    Coord along `statistic`:
        statistic (the original stat names, post-drop-filter)
    Provenance .zattrs:
        embedding_config, source_input_zarr, source_variable, window_size,
        n_skipped_simulations, created_at_utc, tmelandscape_version,
        source_normalize_config (forwarded if present), source_manifest_hash
        (forwarded if present).
    """
```

## Stream allocation (3 buddy pairs)

### Pair A — algorithm

**Implementer A1** writes:

- `src/tmelandscape/embedding/sliding_window.py` —
  `window_trajectory_ensemble` per the contract. Pure function.
- `tests/unit/test_embedding_sliding_window.py` — covers:
  - Deterministic: same input → same output.
  - Shape: for `(n_sim=3, n_timepoint=10, n_statistic=4)` and `window_size=5`,
    each sim contributes `(10 - 5) // 1 + 1 = 6` windows, total
    `n_total_windows = 18`. `embedding.shape == (18, 5*4)`,
    `averages.shape == (18, 4)`.
  - Step-size: `window_size=5, step_size=2` on a 10-timepoint sim
    yields `(10 - 5) // 2 + 1 = 3` windows per sim.
  - `skipped_simulations`: a sim with `n_timepoint=3` and
    `window_size=5` contributes zero windows; its index lands in
    `skipped_simulations`.
  - NaN handling: a window containing NaN flattens NaN; the matching
    `averages` row uses `np.nanmean`, so NaN stat-columns produce NaN
    averages but finite columns survive.
  - Empty ensemble: `n_sim=0` returns a `WindowedEnsemble` with
    zero-length arrays (no crash).
  - Flatten ordering: round-trip a known small matrix through
    `window_trajectory_ensemble` and confirm row-major flattening
    matches `np.ravel(order="C")` on a manually-constructed reference.
  - Pure-function: no mutation of the input array.

**Reviewer A2** audits A1's work:

- Reference fidelity: flatten order, step semantics, end-time-step
  indexing (`end_timepoint = start + window_size - 1`).
- NaN handling: does `np.nanmean` emit a `RuntimeWarning` when an
  entire stat column is NaN within a window? Is it silenced or
  acknowledged?
- Performance: the reference uses a Python double loop; that's fine
  for v0.5.0 but quantify roughly (e.g. ~5 ms per 1000 windows of
  W=50 × n_stats=30).
- mypy strict; ruff clean.
- Coverage of edge cases (empty ensemble, sim shorter than window,
  all-NaN slice).

### Pair B — Zarr orchestrator

**Implementer B1** writes:

- `src/tmelandscape/embedding/__init__.py` — `embed_ensemble` per
  the contract.
- `tests/unit/test_embedding_ensemble.py` — covers:
  - Build a tiny `(n_sim=3, n_tp=8, n_stat=2)` ensemble Zarr in
    `tmp_path` (with a `value_normalized` array and per-sim
    `parameter_*` coords). Call `embed_ensemble` with `window_size=4`;
    confirm output Zarr exists, has expected dims/coords/values.
  - **Input immutability**: sha256-hash every file in the input store
    before/after; assert byte equality.
  - Pre-existence: refuses to overwrite an existing `output_zarr`.
  - Per-window coord propagation: each window's `parameter_alpha`,
    `ic_id`, `parameter_combination_id` matches the source sim's value.
  - `drop_statistics` removes the named stats before windowing;
    `embedding_feature` is `window_size * (n_statistic - n_dropped)`.
  - Unknown stat in `drop_statistics` raises `ValueError`.
  - `source_variable` switch: building from raw `value` instead of
    `value_normalized` produces a comparable shape.
  - Provenance `.zattrs` present: `embedding_config`,
    `source_input_zarr`, `source_variable`, `window_size`,
    `n_skipped_simulations`, `created_at_utc`, `tmelandscape_version`.
  - Skipped-sim warning surfaces (via `warnings.warn` or structured
    log) when a sim is too short.
  - `output_variable == source_variable` raises (defence in depth even
    if the config validator catches it).

**Reviewer B2** audits B1's work:

- Input immutability hash strategy correctness.
- `output_path.exists()` race-free pattern (mirror the Phase 3.5
  orchestrator).
- Coord broadcasting: are per-sim coords actually replicated along the
  window dimension correctly when sims contribute different numbers of
  windows?
- Resource handling: input opened as context manager; partial output
  cleaned on `to_zarr` failure (matching the Phase 3.5 pattern).
- Provenance forwarding (`source_normalize_config`,
  `source_manifest_hash`) — present when input has them, absent
  otherwise.

### Pair C — config + alternatives

**Implementer C1** writes:

- `src/tmelandscape/config/embedding.py` — `EmbeddingConfig` Pydantic
  per the contract.
- `src/tmelandscape/embedding/alternatives.py` — anchor for future
  strategies (v0.5.x). Ship one passthrough/identity stub matching the
  pattern used in `tmelandscape.normalize.alternatives`.
- `tests/unit/test_embedding_config.py` — covers:
  - Default construction fails (no `window_size` default).
  - `window_size=1` accepted; `window_size=0` rejected.
  - `step_size=0` rejected; `step_size=1` (default) accepted.
  - `output_variable == source_variable` rejected with a clear message.
  - `averages_variable == output_variable` rejected.
  - `drop_statistics` defaults to `[]`.
  - JSON round-trip via `model_dump_json` / `model_validate_json`.
  - `extra="forbid"` rejects unknown kwargs.

**Reviewer C2** audits C1's work:

- Validator placement and error messages.
- Style match against `NormalizeConfig` / `SummarizeConfig`.
- `output_variable` collision with both `source_variable` AND
  `averages_variable`.
- Pydantic v2 quirks (`Literal` with one member, JSON round-trip,
  `default_factory=list`).

## Integration (orchestrator, after all three pairs return)

After Wave 2 reviews complete:

1. Apply review findings (SMELLs directly; BUGs/RISKs by editing or
   `SendMessage`-ing the Implementer).
2. Write CLI: `src/tmelandscape/cli/embed.py` (verb `tmelandscape embed`).
3. Write strategy-discovery CLI: `tmelandscape embed-strategies list`
   (mirrors `normalize-strategies`).
4. Write MCP tools: `embed_ensemble_tool` and
   `list_embed_strategies_tool`. Register on the MCP server.
5. Write `tests/integration/test_embedding_end_to_end.py` — Python
   API + CLI + MCP all produce equivalent output Zarrs.
6. Fill out `docs/concepts/embedding.md`; add to `mkdocs.yml` nav.
7. Update STATUS.md + ROADMAP.md.
8. Bump version to 0.5.0; verify all checks green; commit; tag; push.

## House-style invariants (binding on every Implementer)

- Pydantic configs for public surfaces.
- mypy strict-clean on every new file.
- No global numpy random; no I/O in pure functions.
- Tests run in <2s each (mark `@pytest.mark.slow` otherwise).
- Existing 168 tests must remain green.
- No modifications to `pyproject.toml` (orchestrator only).

## Buddy-pair workflow

Same as Phase 3.5:

- Round 1 (parallel): Implementers A1/B1/C1 each produce a report.
- Round 2 (parallel): Reviewers A2/B2/C2 audit their partner read-only.
- Round 3 (orchestrator): apply fixes, integrate, release.

## Session log

- 2026-05-13 (Claude Code orchestrator): Task file frozen with API
  contracts; reference algorithm re-confirmed against
  `reference/utils.py::window_trajectory_data`; ready to spawn Round 1
  Implementers.
