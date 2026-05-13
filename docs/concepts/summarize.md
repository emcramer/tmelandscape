# Concept: spatial-statistic summarisation (step 3)

Step 3 takes the manifest produced by step 1 plus a directory of PhysiCell
outputs and emits a single chunked Zarr ensemble store. Each cell of the
store carries the value of one spatial statistic at one timepoint of one
simulation; downstream steps (3.5 normalize, 4 embedding, 5 clustering)
read from this store.

## Inputs

- A [`SweepManifest`](sampling.md) (the artefact from `tmelandscape sample`).
- A `physicell_root` directory containing one PhysiCell output subdirectory per manifest row. The subdirectory name must match `row.simulation_id` exactly.
- A **`SummarizeConfig`** that the user supplies. There is no default panel — see [ADR 0009](../adr/0009-no-hardcoded-statistics-panel.md). Use the discovery surfaces below to pick a panel.

## Discovering available statistics

`spatialtissuepy` ships ~68 registered metrics (population counts,
graph-based centralities, colocalisation, morphology, topology, etc.).
`tmelandscape` does not curate or restrict this list; the user picks from
the live registry.

```bash
# Print the whole catalogue (one JSON dict per metric)
tmelandscape statistics list

# Filter by category
tmelandscape statistics list --category population

# Inspect one metric in detail (parameter schema, description)
tmelandscape statistics describe cell_type_ratio
```

```python
from tmelandscape.summarize.registry import (
    list_available_statistics, describe_metric, available_metric_names,
)

names = available_metric_names()              # frozenset of metric names
catalogue = list_available_statistics()        # list of {name, category, description, parameters}
detail = describe_metric("cell_type_ratio")    # one metric's full description
```

MCP agents call the same catalogue via the `list_available_statistics`
and `describe_statistic` tools.

## Composing a panel

`SummarizeConfig.statistics` is a list. Each entry is either a plain
string (metric name) or a `StatisticSpec` (name + per-metric parameters).
Both forms accept arbitrary parameters that the chosen metric supports:

```python
from tmelandscape.config.summarize import StatisticSpec, SummarizeConfig

config = SummarizeConfig(
    statistics=[
        "cell_counts",
        "cell_proportions",
        StatisticSpec(name="interaction_strength_matrix", parameters={"radius": 30.0}),
        StatisticSpec(name="average_clustering", parameters={"method": "knn", "k": 8}),
        StatisticSpec(
            name="cell_type_ratio",
            parameters={"numerator": "tumor", "denominator": "M0_macrophage"},
        ),
    ],
)
```

Construction-time validation rejects unknown metric names against
`spatialtissuepy`'s live registry; you cannot ship a misspelled metric
into an ensemble run.

## Empty-timepoint contract

A timepoint with zero live cells emits only `cell_counts` rows (when
that metric is in the panel) and otherwise emits nothing. The aggregator
NaN-fills missing entries against the union schema across simulations.

## `SummarizeConfig` fields

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `statistics` | `list[StatisticSpec \| str]` | **required, no default** | The panel to compute. |
| `n_workers` | `int >= 1` | `1` | Dask workers for ensemble aggregation. |
| `include_dead_cells` | `bool` | `False` | Whether dead cells participate in metrics. |
| `rewrite_interaction_keys` | `bool` | `True` | Rewrite `interaction_<src>_<dst>` keys to `interaction_<src>\|<dst>` so pair keys disambiguate when cell-type names contain underscores. Off for byte-for-byte spatialtissuepy parity. |

## The ensemble Zarr

Dimensions: `(simulation, timepoint, statistic)`. Coordinates:

- `simulation` carries the per-sim `parameter_<name>` arrays (one per sweep parameter), plus `ic_id` and `parameter_combination_id`.
- `timepoint` is an int array of step indices.
- `time` is a 2D `(simulation, timepoint)` float coord because different sims may emit different wall-clock times for the same step index.
- Missing entries are NaN (ragged simulations or schema gaps).

Provenance `.zattrs` include `tmelandscape_version`, `manifest_hash`
(sha256 of `manifest.model_dump_json()`), `created_at_utc`, and the
serialised `SummarizeConfig` (panel + parameters). See
[ADR 0003](../adr/0003-zarr-as-ensemble-store.md) for the Zarr v3
caveat.

## Code example

```python
from pathlib import Path
import xarray as xr

from tmelandscape.config.summarize import StatisticSpec, SummarizeConfig
from tmelandscape.sampling.manifest import SweepManifest
from tmelandscape.summarize import summarize_ensemble

manifest = SweepManifest.load("sweep_manifest.json")
config = SummarizeConfig(
    statistics=[
        "cell_counts",
        StatisticSpec(name="interaction_strength_matrix", parameters={"radius": 25.0}),
    ],
)

summarize_ensemble(
    manifest,
    physicell_root=Path("/scratch/sims/"),
    output_zarr="ensemble.zarr",
    config=config,
)

ds = xr.open_zarr("ensemble.zarr", consolidated=False)
n_cells = ds["value"].sel(statistic="n_cells")
high_exh = ds.where(ds["parameter_r_exh"] > 1e-3, drop=True)
```

## CLI

```bash
tmelandscape statistics list                  # discover available metrics
tmelandscape summarize \
    sweep_manifest.json \
    summarize_config.json \
    --physicell-root /scratch/sims/ \
    --output-zarr ensemble.zarr
```

The summarise CLI requires both a sweep manifest *and* a JSON file
holding a `SummarizeConfig`. A JSON summary (Zarr path, simulation
count, applied statistics list) is printed to stdout. Progress from
`spatialtissuepy` is routed to stderr so the JSON stays parseable.

## What's *not* in step 3

Step 3 stops at the Zarr ensemble.

- **Running the PhysiCell simulations** is the external step 2 (out of scope for tmelandscape).
- **Within-time-step normalisation** of the spatial statistics is the upcoming step 3.5; see [ADR 0006](../adr/0006-normalize-as-pipeline-step.md). Normalisation always writes to a *new* variable / store — never overwrites the raw ensemble.
- **No feature dropping by default.** If you want to exclude features before normalisation or embedding, supply an explicit list at that step. tmelandscape ships no `DEFAULT_DROP_COLUMNS`.
- **Time-delay embedding** (step 4) and **two-stage clustering** (step 5) consume the normalised ensemble; see the [roadmap](../development/ROADMAP.md).
