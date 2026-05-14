# 07 — Phase 6 visualisation implementation

- **slug:** 07-visualisation-implementation
- **status:** **COMPLETE 2026-05-14** — shipped as v0.7.0 after Wave 1 / 2 / 3.
- **owner:** Phase 6 orchestrator (claude-opus-4-7) + 3 buddy-pair teams
- **opened:** 2026-05-14 (drafted)
- **shipped:** 2026-05-14 (v0.7.0)
- **roadmap link:** Phase 6 — visualisation (v0.7.0)
- **session log:** [decision log 2026-05-14-phase-6-session.md](../docs/development/decisions/2026-05-14-phase-6-session.md)

## Context

Step 6 of the pipeline: from the clustered ensemble Zarr (Phase 5
output, with optional joins back to the Phase 2 sweep manifest and
Phase 3 ensemble), produce the **publication figures from the LCSS and
TNBC manuscripts** as programmatic functions.

Project owner's scope (2026-05-14):

> We will want to be able to create the following figures from the
> LCSS manuscript: 1, 3, 4, 6. And the following figures from the
> other TNBC manuscript: 2a-e, 6a-c.

This is **eleven data figures** plus one schematic (LCSS Fig. 1). The
schematic is **out of scope** as a Python function and ships as an
SVG asset under `docs/assets/` (the figure is hand-drawn BioRender
content with no data behind it).

Reference oracles:

- `reference/01_abm_generate_embedding.py` — UMAP fit + UMAP-coloured
  scatters (lines 158–207 fit; 279–322 time-coloured; 446–496 feature-
  coloured; 850–907 state-coloured).
- `reference/02_abm_state_space_analysis.marimo.py` — clustermaps and
  trajectory clustergrams (lines 134–305, 537–663, 1000–1156, 1176–1234).
- Methods sections of both PDFs in `docs/literature/` for the vector
  field + occupancy methodology that has no direct reference script.

## Binding invariants

The Phase-3-through-5 invariants continue to apply:

1. **Never overwrite raw data.** Phase 6 functions are *read-only* with
   respect to the cluster Zarr; they return matplotlib `Figure` /
   `Axes` objects (or save to a user-supplied path) and never write
   back to the input store.
2. **No silent science-shaping defaults.** Per [ADR 0009](../docs/adr/0009-no-hardcoded-statistics-panel.md):
   parameter axes for parameter-space figures (LCSS Fig. 6, TNBC
   Fig. 6c) must be **user-supplied**, not hardcoded to `(rexh, radh)` or
   any other literature value. The manuscript-specific values become
   tutorial defaults, not library defaults.
3. **Time-coord 2D awareness.** The Phase 3 `time` coordinate is
   `(simulation, timepoint)`-aligned, not `(timepoint,)`-aligned (see
   the STATUS "Quirks worth knowing" list). Per-window time averages
   must be computed per-`(sim, window)`, not globally.
4. **Three public surfaces** are *relaxed* for Phase 6. Visualisation
   functions are Python-API-first; we **do not** ship a CLI verb per
   figure (would be ugly), but we **do** ship one MCP tool per figure-
   producing function so agents can invoke them. Strategy-discovery
   surfaces (`tmelandscape viz-figures list`, MCP `list_viz_figures`)
   become the catalogue.
5. **No MSM / MDP / projection.** Per [ADR 0005](../docs/adr/0005-no-msm-in-v1.md):
   none of the requested figures require it. If a future figure does,
   gate it behind a new ADR.

## Phase 6 prerequisite (assigned to Stream C): sweep-manifest ↔ cluster-Zarr join

Two of Stream C's figures (LCSS-6, TNBC-6c) need a **per-simulation
view** that joins the Phase 2 sweep manifest (sampled parameters per
`simulation_id`) with the Phase 5 cluster output (per-window labels).
The `landscape/` module is the natural home — it's been an empty
placeholder since Phase 0.

**Stream C owns this prereq.** It is delivered alongside the three
dynamics figures:

- `src/tmelandscape/landscape/__init__.py` — `join_manifest_cluster(
  manifest_path: str | Path, cluster_zarr: str | Path,
  *, terminal_window_count: int = 5) -> pd.DataFrame`. Returns a
  DataFrame indexed by `simulation_id` with columns: sampled
  parameter values (one column per `parameter_<name>`), terminal
  cluster label (mode of `cluster_labels` over the last
  `terminal_window_count` windows of the sim, default 5), and
  `n_windows` (sanity).
- Unit tests in `tests/unit/test_landscape_join.py` covering: presence
  of all sim ids, terminal-label correctness, missing-sim handling,
  `terminal_window_count` boundary behaviour.

Streams A and B do **not** depend on this helper; they read the
cluster Zarr directly.

## Figure catalogue (the eleven data figures)

| Tag | Manuscript | Brief | Stream | Complexity | Reference oracle |
| --- | --- | --- | --- | --- | --- |
| LCSS-3 | LCSS | UMAP scatter + per-state vector field + per-state density contours | A | medium | `01_abm_generate_embedding.py:158-207, 850-907` + Methods prose for vector field |
| LCSS-4 | LCSS | Multi-panel UMAP coloured by `ctum`, `cTeff`, `cTexh` populations | A | small | `01_abm_generate_embedding.py:446-496` |
| LCSS-6 | LCSS | Parameter-space attractor basins via 2-NN decision boundary | C | medium | **no reference** — Methods prose only |
| TNBC-2a | TNBC | Clustermap of Leiden cluster means × spatial features, state-coloured row bar | B | small-medium | `02_abm_state_space_analysis.marimo.py:134-305, 537-663` |
| TNBC-2b | TNBC | State-coloured UMAP scatter | A | small | `01_abm_generate_embedding.py:850-907` |
| TNBC-2c | TNBC | UMAP coloured by per-window mean time | A | small | `01_abm_generate_embedding.py:279-322` |
| TNBC-2d | TNBC | Example trajectory overlays on the state-coloured UMAP | A | small | `02_abm_state_space_analysis.marimo.py:1176-1234` (animated reference) |
| TNBC-2e | TNBC | Multi-panel UMAP coloured by 4 features (overlaps LCSS-4 + a 4th panel) | A | small | `01_abm_generate_embedding.py:446-496` |
| TNBC-6a | TNBC | Trajectory clustergram: `(sim × window)` heatmap of state labels with row dendrogram | B | small | `02_abm_state_space_analysis.marimo.py:1000-1156` |
| TNBC-6b | TNBC | Vector field in `(epithelial_count, T_eff_count)` phase space, per-state, dual occupancy histogram | C | medium | **no reference** — TNBC Methods 880-896 |
| TNBC-6c | TNBC | Violin plot of `CD8_Teff→CD8_Tex` rate by terminal state, pairwise sig annotations | C | medium | **no reference** — composed from sweep manifest + cluster output |

LCSS-1 ships as an SVG asset (`docs/assets/lcss-figure-1-schematic.svg`)
delivered by Eric or BioRender export; not a programmatic function. The
v0.7.0 ship documents the path; the asset itself can land later.

## Library dependencies to add to the `viz` extra

Already present: `matplotlib>=3.9`, `umap-learn>=0.5`, `plotly>=5.22`.

To add in `pyproject.toml[project.optional-dependencies].viz`:

- `seaborn>=0.13` — `clustermap` (TNBC-2a), `kdeplot` (LCSS-3 contours),
  `violinplot` (TNBC-6c). Required.
- `statsmodels>=0.14` — optional, only needed for BH-FDR multiple-
  testing correction in TNBC-6c. Could be hand-rolled (~10 LOC); the
  orchestrator picks during integration.

## Public API (frozen — Implementers must match these signatures)

All figure functions live under `tmelandscape.viz.*`, return a
`matplotlib.figure.Figure`, and accept an optional `ax` /
`fig`-kwarg for caller-controlled composition. Each one also takes a
`save_path: str | Path | None = None` so a CLI / MCP caller can dump
straight to disk.

### Stream A — UMAP-centric (`tmelandscape.viz.embedding`)

```python
# src/tmelandscape/viz/embedding.py
from dataclasses import dataclass
import numpy as np
import matplotlib.figure as mfig
from typing import Sequence

@dataclass
class UMAPResult:
    """Cached UMAP projection of a windowed-embedding Zarr.

    Persistable; the same UMAPResult is reused across every figure
    that overlays on the 2D projection (LCSS-3/4, TNBC-2b/2c/2d/2e).
    """
    coordinates: np.ndarray   # (n_window, 2) float64
    n_neighbors: int
    min_dist: float
    random_state: int
    source_input_zarr: str    # absolute path

def fit_umap(
    cluster_zarr: str | Path,
    *,
    n_neighbors: int = 15,
    min_dist: float = 0.1,
    random_state: int = 42,
) -> UMAPResult: ...

def plot_state_umap(
    umap_result: UMAPResult,
    cluster_zarr: str | Path,
    *,
    state_palette: dict[int, str] | None = None,
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """TNBC-2b — state-coloured UMAP scatter. `state_palette=None` ⇒
    matplotlib's `tab10` for ≤10 states; raise if more than tab10."""

def plot_time_umap(
    umap_result: UMAPResult,
    cluster_zarr: str | Path,
    *,
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """TNBC-2c — UMAP coloured by per-window mean time. Respects the 2D
    time-coord quirk."""

def plot_feature_umap(
    umap_result: UMAPResult,
    cluster_zarr: str | Path,
    *,
    features: Sequence[str],
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """LCSS-4 / TNBC-2e — multi-panel UMAP coloured by per-window
    averages of named statistics. `features` lists statistic names that
    appear in the input Zarr's `window_averages.statistic` coord."""

def plot_trajectory_umap(
    umap_result: UMAPResult,
    cluster_zarr: str | Path,
    *,
    sim_ids: Sequence[str],
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """TNBC-2d — state-coloured UMAP background with named sim
    trajectories overlaid as polylines."""

def plot_state_umap_with_vector_field(
    umap_result: UMAPResult,
    cluster_zarr: str | Path,
    *,
    grid_size: int = 20,
    show_density_contours: bool = True,
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """LCSS-3 — state-coloured UMAP scatter + per-state mean-displacement
    quiver + per-state KDE contours."""
```

### Stream B — Heatmaps and trajectory clustergrams (`tmelandscape.viz.trajectories`)

```python
# src/tmelandscape/viz/trajectories.py
import matplotlib.figure as mfig
from pathlib import Path

def plot_state_feature_clustermap(
    cluster_zarr: str | Path,
    *,
    z_score: int | None = 1,
    cmap: str = "viridis",
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """TNBC-2a — seaborn clustermap of Leiden cluster means × spatial
    features. Rows annotated by Ward-cluster colour bar; row dendrogram
    from the cluster Zarr's `linkage_matrix`."""

def plot_trajectory_clustergram(
    cluster_zarr: str | Path,
    *,
    metric: str = "euclidean",
    linkage_method: str = "average",
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """TNBC-6a — `(sim × window)` heatmap of state labels with row
    dendrogram (Ward on the trajectory vectors)."""
```

### Stream C — Phase-space dynamics + parameter-state plots (`tmelandscape.viz.dynamics`)

```python
# src/tmelandscape/viz/dynamics.py
import matplotlib.figure as mfig
from pathlib import Path
from typing import Sequence

def plot_phase_space_vector_field(
    cluster_zarr: str | Path,
    *,
    x_feature: str,
    y_feature: str,
    states: Sequence[int],
    grid_size: int = 20,
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """TNBC-6b — vector field in (x_feature, y_feature) phase space, one
    quiver overlay per state in `states`, plus per-state 2D occupancy
    histogram. `x_feature`/`y_feature` are statistic names; no
    hardcoded `(epithelial, T_eff)` — manuscript-specific values are
    tutorial defaults."""

def plot_parameter_by_state(
    cluster_zarr: str | Path,
    manifest_path: str | Path,
    *,
    parameter: str,
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """TNBC-6c — violin plot of one named sweep parameter by terminal
    state, with pairwise Mann-Whitney + BH-FDR significance
    annotations. `parameter` is a column name from the joined
    manifest, e.g. `parameter_t_exhaustion_rate`. Owner-directive:
    parameter must be user-supplied, not hardcoded."""

def plot_attractor_basins(
    cluster_zarr: str | Path,
    manifest_path: str | Path,
    *,
    x_parameter: str,
    y_parameter: str,
    states: Sequence[int] | None = None,
    knn_neighbors: int = 2,
    grid_size: int = 200,
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """LCSS-6 — 2D parameter-space scatter of sims coloured by
    terminal cluster; 2-NN decision-boundary regions painted as
    shaded background. `x_parameter`/`y_parameter` are column names
    from the joined manifest."""
```

## Stream allocation (3 buddy pairs — mirrors Phases 3.5 / 4 / 5)

### Pair A — UMAP scatter family

**Stream A** owns `src/tmelandscape/viz/embedding.py` (`fit_umap`,
`plot_state_umap`, `plot_time_umap`, `plot_feature_umap`,
`plot_trajectory_umap`, `plot_state_umap_with_vector_field`) plus the
matching test files. Six figures total: LCSS-3, LCSS-4, TNBC-2b, 2c,
2d, 2e. Implementer A1 + Reviewer A2.

### Pair B — Heatmaps and trajectory clustergrams

**Stream B** owns `src/tmelandscape/viz/trajectories.py`
(`plot_state_feature_clustermap`, `plot_trajectory_clustergram`) plus
tests. Two figures: TNBC-2a, TNBC-6a. Smallest in LOC; assign to
whoever wants a focused, correctness-heavy stream. Implementer B1 +
Reviewer B2.

### Pair C — Phase-space dynamics + parameter-state plots

**Stream C** owns `src/tmelandscape/viz/dynamics.py`
(`plot_phase_space_vector_field`, `plot_parameter_by_state`,
`plot_attractor_basins`) plus tests. Three figures: LCSS-6, TNBC-6b,
TNBC-6c. Largest stream in genuinely new logic (none of these have a
direct reference script). Implementer C1 + Reviewer C2.

## Testing strategy

Figure tests are notoriously sensitive to platform / matplotlib
version differences. Strategy:

- **Smoke tests** (every figure): call the function on a synthetic
  fixture; assert the returned `Figure` has the expected number of
  Axes, the expected axis labels, the expected number of artists per
  Axes (lines, paths, etc.). No pixel comparison.
- **Determinism tests**: same inputs ⇒ same `Figure.bbox.bounds`,
  `Axes.get_xlim()`, scatter `offsets`, etc. (Caller-controlled
  `random_state` for UMAP.)
- **Data-correctness tests** (where applicable): for figures that bin
  data into the plot (vector field grids, clustermap z-scores), assert
  the underlying binning is correct by reaching into the artist data
  arrays.
- **`save_path` round-trip**: every function called with
  `save_path=tmp_path/'out.png'` writes a non-empty file; PNG header
  bytes verified.
- **NO** pixel-by-pixel comparison or `pytest-mpl` baseline images for
  v0.7.0. Defer to v0.7.x once the API stabilises.

Synthetic fixture: a small cluster Zarr (5 sims × 10 windows × 6 final
states, deterministic seed) built once via a `conftest.py` fixture
function. Real-data integration tests stay gated behind `pytest -m
real` per existing pattern.

## MCP surface (Phase 6's variation on three-surfaces)

- **One MCP tool per figure function**: `plot_state_umap_tool`,
  `plot_feature_umap_tool`, etc. Each takes the same kwargs as the
  Python function (paths as strings) and returns a dict with the saved
  figure's absolute path (`save_path` is *required* for the MCP tool,
  since MCP can't return Figure objects).
- **Discovery tool**: `list_viz_figures` returns a catalogue of all
  figure-producing tools with their docstring summaries and which
  manuscript figure each reproduces.
- **CLI**: a single discovery verb `tmelandscape viz-figures list` and
  per-figure verbs `tmelandscape viz <figure-tag>` (e.g.
  `tmelandscape viz lcss-3`). Pretty optional; orchestrator can defer
  if the implementation gets long.

## Out-of-scope concerns (flagged for owner if hit)

1. **LCSS Figure 1 schematic**: shipping as SVG asset, not Python
   function. Source assets TBD — please drop an SVG into `docs/assets/`
   or signal "I'll do this later" so we can leave a TODO.
2. **TNBC-6b methodology with no reference script**: Methods prose
   is sufficient to implement, but numerical agreement with the
   manuscript's exact figure will be approximate (we're reconstructing
   from prose, not bit-exact reproducing).
3. **Hardcoded parameter axes (LCSS-6, TNBC-6c)**: per ADR 0009 these
   are user-supplied. The manuscript's specific values
   (`(rexh, radh)`, `CD8_Teff→CD8_Tex` rate) become tutorial defaults
   in `docs/concepts/viz.md`, not library defaults.
4. **WSS-elbow algorithm choice** (pending owner pick — see
   [decision log](../docs/development/decisions/2026-05-14-wss-elbow-algorithm-options.md))
   is unrelated to Phase 6 but the test fixtures share infrastructure;
   if the WSS-elbow decision lands in v0.7.x it slots in cleanly.

## House-style invariants (binding on every Implementer)

Same as Phases 3.5 / 4 / 5. See `AGENTS.md` and prior task files. Plus
the new decision-log process: every Wave-2 reviewer finding that gets
applied or deferred during integration is captured in the Phase 6
session log under `docs/development/decisions/YYYY-MM-DD-phase-6-session.md`.

## Session log

- 2026-05-14 (Claude Code orchestrator, drafting): task file drafted
  off the back of the parallel scope-research agent. Frozen API
  contracts pasted above; stream allocation set; pre-wave prerequisite
  (`landscape.join_manifest_cluster`) identified. Ready for the
  orchestrator to handle the pre-wave prerequisite and then spawn
  Wave 1.
