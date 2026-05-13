# Concept: spatial-statistic summarisation (step 3)

Step 3 takes the manifest produced by step 1 plus a directory of PhysiCell outputs and emits a single chunked Zarr ensemble store. Each cell of the store carries the value of one spatial statistic at one timepoint of one simulation; downstream steps (3.5 normalize, 4 embedding, 5 clustering) read from this store.

## Inputs

- A [`SweepManifest`](sampling.md) (the artefact from `tmelandscape sample`).
- A `physicell_root` directory containing one PhysiCell output subdirectory per manifest row. The subdirectory name must match `row.simulation_id` exactly.
- A `SummarizeConfig` (Pydantic) selecting which statistics to compute. Defaults to the LCSS-paper panel.

## What gets computed

The default panel mirrors the LCSS paper. Each statistic is computed per timepoint per simulation, then aggregated.

| Statistic name (input) | Output keys | Notes |
| --- | --- | --- |
| `cell_counts` | `n_cells`, `n_<type>` | Population-level. |
| `cell_type_fractions` | `fraction_<type>` | Rekeyed from upstream's `prop_<type>`. |
| `mean_degree_centrality_by_type` | `degree_centrality_<type>` | Built on the prebuilt `CellGraph`. |
| `mean_closeness_centrality_by_type` | `closeness_centrality_<type>` | Same. |
| `mean_betweenness_centrality_by_type` | `betweenness_centrality_<type>` | Same. |
| `interaction_strength_matrix` | `interaction_<src>\|<dst>` | KDTree-based coords metric — ignores the graph; uses `graph_radius_um` as the interaction radius. The `\|` delimiter is used because cell-type names contain underscores (`M0_macrophage`, `effector_T_cell`) and a plain `_` separator would be ambiguous. |

Unknown statistic names are rejected at config-construction time by a Pydantic validator over `KNOWN_STATISTICS`.

!!! note "Empty-timepoint contract"
    On a timepoint with zero live cells, only `cell_counts` emits a row (`n_cells = 0`). Centrality / fraction / interaction stats emit *no rows* — the aggregator NaN-fills missing entries from the union schema across simulations. This avoids polluting the `statistic` coordinate with a placeholder key that disagrees with the non-empty rows' `fraction_<type>` / `interaction_<src>|<dst>` schemas.

## `SummarizeConfig` fields

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `statistics` | `list[str]` | LCSS panel (6 names) | Names from `KNOWN_STATISTICS`. |
| `graph_method` | `"proximity" \| "knn" \| "delaunay" \| "gabriel"` | `"proximity"` | Method passed to `CellGraph.from_spatial_data`. |
| `graph_radius_um` | `float > 0` | `30.0` | Radius in μm for the proximity graph AND for `interaction_strength_matrix` (always, regardless of `graph_method`). |
| `n_workers` | `int >= 1` | `1` | Dask workers for ensemble aggregation. |
| `include_dead_cells` | `bool` | `False` | Whether dead cells participate in stats. |

## The ensemble Zarr

Dimensions: `(simulation, timepoint, statistic)`. Coordinates:

- `simulation` carries the per-sim `parameter_<name>` arrays (one per sweep parameter), plus `ic_id` and `parameter_combination_id`.
- `timepoint` is an int array of step indices.
- `time` is a 2D `(simulation, timepoint)` float coord because different sims may emit different wall-clock times for the same step index.
- Missing entries are NaN (ragged simulations or schema gaps).

Provenance `.zattrs` include `tmelandscape_version`, `manifest_hash` (sha256 of `manifest.model_dump_json()`), `created_at_utc`, and the serialised `SummarizeConfig`. See [ADR 0003](../adr/0003-zarr-as-ensemble-store.md) for the format rationale and the Zarr v3 status note.

## Code example

```python
from pathlib import Path
import xarray as xr

from tmelandscape.config.summarize import SummarizeConfig
from tmelandscape.sampling.manifest import SweepManifest
from tmelandscape.summarize import summarize_ensemble

manifest = SweepManifest.load("sweep_manifest.json")
summarize_ensemble(
    manifest,
    physicell_root=Path("/scratch/sims/"),
    output_zarr="ensemble.zarr",
    config=SummarizeConfig(graph_radius_um=25.0),
)

ds = xr.open_zarr("ensemble.zarr", consolidated=False)
# Slice: degree centrality of tumour cells across the ensemble.
tumour_degree = ds["value"].sel(statistic="degree_centrality_tumor")
# Slice by parameter value: simulations with the highest r_exh.
high_exh = ds.where(ds["parameter_r_exh"] > 1e-3, drop=True)
```

## CLI

```bash
tmelandscape summarize sweep_manifest.json \
    --physicell-root /scratch/sims/ \
    --output-zarr ensemble.zarr
```

A JSON summary (Zarr path, simulation count, applied statistics list) is printed to stdout. Progress from `spatialtissuepy` is routed to stderr so the JSON stays parseable.

## What's *not* in step 3

Step 3 stops at the Zarr ensemble.

- **Running the PhysiCell simulations** is the external step 2 (out of scope for tmelandscape).
- **Within-time-step normalisation** of the spatial statistics is the upcoming step 3.5; see [ADR 0006](../adr/0006-normalize-as-pipeline-step.md).
- **Time-delay embedding** (step 4) and **two-stage clustering** (step 5) consume the normalized ensemble; see the [roadmap](../development/ROADMAP.md).
