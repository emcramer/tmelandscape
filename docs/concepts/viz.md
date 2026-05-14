# Concept: visualisation (step 6)

Step 6 reads the clustered ensemble Zarr from step 5 (and, for two of
the eleven figures, the sweep manifest from step 1) and produces the
publication figures from the LCSS and TNBC manuscripts. Each figure is
exposed as:

- a **Python function** under `tmelandscape.viz.{embedding,trajectories,dynamics}`
- a matching **MCP tool** under `tmelandscape.mcp.tools` (one per figure
  function; agents call these to render to disk)
- *no per-figure CLI verb* — eleven verbs in one namespace was judged
  not worth the surface area; the [`tmelandscape viz-figures list`](#discovery)
  discovery verb is provided instead

Figures reproduced (per Eric's directive, 2026-05-14):

- LCSS Figures **1, 3, 4, 6**
- TNBC Figures **2a, 2b, 2c, 2d, 2e, 6a, 6b, 6c**

All twelve figures are programmatic. **LCSS Figure 1** was originally
out of scope (slated as a static asset under `docs/assets/`), but as
of v0.7.1 it ships as a generic schematic-generator function — see
[decision log](../development/decisions/2026-05-14-lcss-1-schematic-in-scope.md).
The function takes a user-supplied model description — cell-type
names and interaction rules — and renders a coloured-node /
typed-arrow diagram. It is **generic across any ABM**: pass any
cell-type list, not just the LCSS paper's specific TME model.

## Discovery

```bash
tmelandscape viz-figures list
```

```python
from tmelandscape.mcp.tools import list_viz_figures_tool
print(list_viz_figures_tool())
```

MCP agents call `list_viz_figures`.

## Figure catalogue

| Tag | Manuscript | Function | Quick description |
| --- | --- | --- | --- |
| LCSS-1 | LCSS | `viz.model_schematic.plot_model_schematic` | Programmatic ABM schematic — coloured nodes for cell types + typed arrows for interactions (added v0.7.1) |
| LCSS-3 | LCSS | `viz.embedding.plot_state_umap_with_vector_field` | State-coloured UMAP + per-state vector field + density contours |
| LCSS-4 | LCSS | `viz.embedding.plot_feature_umap` | Multi-panel UMAP coloured by per-feature window averages |
| LCSS-6 | LCSS | `viz.dynamics.plot_attractor_basins` | 2D parameter-space scatter with kNN decision-boundary regions |
| TNBC-2a | TNBC | `viz.trajectories.plot_state_feature_clustermap` | Clustermap of Leiden cluster means × spatial features |
| TNBC-2b | TNBC | `viz.embedding.plot_state_umap` | State-coloured UMAP scatter |
| TNBC-2c | TNBC | `viz.embedding.plot_time_umap` | UMAP coloured by per-window mean time |
| TNBC-2d | TNBC | `viz.embedding.plot_trajectory_umap` | UMAP with named sim trajectories overlaid |
| TNBC-2e | TNBC | `viz.embedding.plot_feature_umap` | Multi-panel UMAP coloured by per-feature averages (same function as LCSS-4) |
| TNBC-6a | TNBC | `viz.trajectories.plot_trajectory_clustergram` | (sim × window) state-label heatmap with row dendrogram |
| TNBC-6b | TNBC | `viz.dynamics.plot_phase_space_vector_field` | Per-state vector field in (x_feature, y_feature) phase space |
| TNBC-6c | TNBC | `viz.dynamics.plot_parameter_by_state` | Violin of a sweep parameter by terminal state, MW + BH-FDR |

## Module layout

- **`tmelandscape.viz.embedding`** — UMAP-projection family. Owns
  `fit_umap` + five `plot_*` functions sharing a single 2D projection.
  The first positional parameter is named `umap_result: UMAPResult` to
  avoid shadowing the `umap` library import. See
  [decision log](../development/decisions/2026-05-14-viz-umap-result-param-rename.md).
- **`tmelandscape.viz.trajectories`** — heatmap-style figures.
  `plot_state_feature_clustermap` (TNBC-2a) and
  `plot_trajectory_clustergram` (TNBC-6a). Ragged trajectories raise
  rather than NaN-pad; `leiden_labels` is optional with graceful
  degradation. See
  [decision log](../development/decisions/2026-05-14-viz-trajectories-deviations.md).
- **`tmelandscape.viz.dynamics`** — phase-space and parameter-state
  plots. `plot_phase_space_vector_field` (TNBC-6b),
  `plot_parameter_by_state` (TNBC-6c, BH-FDR hand-rolled — see
  [decision log](../development/decisions/2026-05-14-bh-fdr-hand-rolled.md)),
  and `plot_attractor_basins` (LCSS-6). Parameter / feature names are
  always user-supplied per [ADR 0009](../adr/0009-no-hardcoded-statistics-panel.md);
  the manuscript-specific values (`(epithelial, T_eff)`,
  `CD8_Teff→CD8_Tex`-rate, `(rexh, radh)`) become tutorial defaults.
- **`tmelandscape.viz.model_schematic`** *(added v0.7.1)* — programmatic
  schematic generator for any ABM. Owns `CellType`, `Interaction`, and
  `plot_model_schematic` (LCSS-1). Renders coloured-circle nodes with
  text labels and typed arrows (`promotes` / `inhibits` /
  `transitions_to` / `secretes`). Output supports PNG (raster) and SVG
  (vector) via matplotlib's extension dispatch. See [decision log](../development/decisions/2026-05-14-lcss-1-schematic-in-scope.md).
- **`tmelandscape.landscape.join_manifest_cluster`** — Stream-C
  prerequisite. Joins the Phase 2 sweep manifest with the Phase 5
  cluster Zarr; returns a DataFrame indexed by `simulation_id` with one
  column per parameter plus `terminal_cluster_label` (mode of the last
  `terminal_window_count` windows; see
  [decision log](../development/decisions/2026-05-14-terminal-cluster-label-mode.md))
  and `n_windows`.

## Inputs

Every figure reads from a Phase 5 cluster Zarr. Two figures
(`plot_parameter_by_state`, `plot_attractor_basins`) additionally need
a Phase 2 sweep manifest.

Each figure function returns a `matplotlib.figure.Figure`. When called
with `save_path=...`, it also writes a PNG via `fig.savefig(...,
bbox_inches="tight", dpi=150)`. MCP tools **require** `save_path` (MCP
can't return Figure objects).

## Algorithms

The Leiden + Ward + UMAP core algorithms come from
`reference/01_abm_generate_embedding.py` and
`reference/02_abm_state_space_analysis.marimo.py`. Three figures have
no direct reference script (LCSS-6, TNBC-6b, TNBC-6c) — they are
composed from manuscript-Methods prose plus `tmelandscape`'s existing
joined-data surface. See `tasks/07-visualisation-implementation.md`
(repo root, not on the docs site) for the per-figure oracle pointers.

## Worked example

```python
from pathlib import Path

from tmelandscape.viz.embedding import fit_umap, plot_state_umap, plot_feature_umap
from tmelandscape.viz.trajectories import plot_state_feature_clustermap
from tmelandscape.viz.dynamics import plot_attractor_basins

cluster_zarr = "ensemble_clustered.zarr"
manifest = "sweep_manifest.json"

# UMAP family — fit once, reuse the projection across figures.
umap_result = fit_umap(cluster_zarr, n_neighbors=15, min_dist=0.1, random_state=42)
plot_state_umap(umap_result, cluster_zarr, save_path="state_umap.png")        # TNBC-2b
plot_feature_umap(
    umap_result,
    cluster_zarr,
    features=["malignant_epithelial_cell_count", "effector_T_cell_count"],
    save_path="feature_umap.png",                                              # LCSS-4
)

# Heatmap.
plot_state_feature_clustermap(cluster_zarr, save_path="clustermap.png")        # TNBC-2a

# Parameter-space basins (needs the manifest).
plot_attractor_basins(
    cluster_zarr,
    manifest,
    x_parameter="parameter_rexh",
    y_parameter="parameter_radh",
    save_path="basins.png",                                                    # LCSS-6
)
```

## MCP usage

Agents access every figure as an MCP tool returning the resolved save
path:

```python
# Equivalent to the Python API above, via MCP.
from tmelandscape.mcp.tools import plot_state_umap_tool

result = plot_state_umap_tool(
    cluster_zarr="ensemble_clustered.zarr",
    save_path="/tmp/state_umap.png",
)
# result = {
#   "save_path": "/tmp/state_umap.png",
#   "figure_tag": "tnbc-2b",
#   "manuscript": "TNBC",
#   "description": "state-coloured UMAP scatter",
# }
```

Use `list_viz_figures` to discover what's available, then call the
named tool.

## What's *not* in step 6

- **Per-figure CLI verbs.** Eleven figure-tool verbs in a single
  namespace would overwhelm `--help`. Use the Python API or the MCP
  tools.
- **Pixel-baseline tests.** v0.7.0 ships smoke + determinism +
  data-correctness + save-path-roundtrip tests. Baseline-image diffing
  (e.g. `pytest-mpl`) is deferred to v0.7.x once the API stabilises.
- **Animated trajectories.** Reference
  `02_abm_state_space_analysis.marimo.py:1176-1234` animates the
  state-coloured UMAP trajectories; `plot_trajectory_umap` produces a
  static frame. Animation is a v0.7.x option if needed.
- **MSM / transition modelling.** Per
  [ADR 0005](../adr/0005-no-msm-in-v1.md), out of scope for v1.
