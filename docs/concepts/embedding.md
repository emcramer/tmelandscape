# Concept: time-delay embedding (step 4)

Step 4 takes the normalised ensemble Zarr from step 3.5 and converts each
simulation's `(timepoint, statistic)` matrix into a stack of overlapping
sliding-window vectors. The output is a new Zarr where each row is one
window position from one simulation, flattened to a length-`window_size *
n_statistic` embedding vector. Clustering (step 5) operates on these
vectors.

The reference oracle is `reference/utils.py::window_trajectory_data`; the
implementation matches the reference exactly (row-major flatten, step
size 1 by default, per-window per-statistic means kept as a companion
array).

## Inputs

- The normalised ensemble Zarr from `tmelandscape normalize`. By default
  the embedding reads `value_normalized`; pass a different
  `source_variable` to embed the raw `value` array or any other data
  variable.
- An `EmbeddingConfig` (Pydantic) carrying the required `window_size`
  and the optional `step_size` / `drop_statistics` / variable names.

## Algorithm — `sliding_window` (default)

For each simulation `s` along the input's `simulation` axis:

1. Take its `(n_timepoint, n_statistic)` slab.
2. Slide a window of length `W = config.window_size` along the
   timepoint axis with step `config.step_size` (default 1).
3. For each window position `i`:
   - Flatten the `(W, n_statistic)` submatrix to a length-`W *
     n_statistic` vector (row-major, `np.ravel(order="C")`).
   - Compute the per-statistic mean across the window's `W` timepoints
     (with `np.nanmean` so NaN-only columns produce NaN but finite
     columns survive). This becomes the `window_averages` row.
4. Skip the simulation if `n_timepoint < window_size`; its
   `simulation_id` is named in the skipped-sims warning and recorded
   in the `n_skipped_simulations` provenance attribute.

Per-simulation metadata (parameter values, `ic_id`,
`parameter_combination_id`) is broadcast along the new `window` dim so
each window carries its source-simulation's coords.

## Discovering available strategies

```bash
tmelandscape embed-strategies list
```

```python
from tmelandscape.cli.embed_strategies import _catalogue
print(_catalogue())
```

MCP agents call `list_embed_strategies`.

## `EmbeddingConfig` fields

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `strategy` | `Literal["sliding_window"]` | `"sliding_window"` | Algorithm to apply. |
| `window_size` | `int (>=1)` | **required** | Length of the sliding window in timepoints. The LCSS paper suggests `W ∈ {30, 50, 80}`; the reference uses 50. No package default. |
| `step_size` | `int (>=1)` | `1` | Number of timepoints between consecutive window starts. |
| `source_variable` | `str` | `"value_normalized"` | Which input data variable carries the time series. |
| `output_variable` | `str` | `"embedding"` | Name of the flattened embedding array in the output Zarr. Must differ from `source_variable` and `averages_variable`. |
| `averages_variable` | `str` | `"window_averages"` | Name of the per-window per-statistic means array in the output Zarr. Must differ from `source_variable` and `output_variable`. |
| `drop_statistics` | `list[str]` | `[]` | Explicit list of statistic-coord values to drop *before* windowing. Default `[]` per ADR 0009. |

## Code example

```python
from pathlib import Path
import xarray as xr

from tmelandscape.config.embedding import EmbeddingConfig
from tmelandscape.embedding import embed_ensemble

embed_ensemble(
    "ensemble_normalized.zarr",
    "ensemble_embedded.zarr",
    config=EmbeddingConfig(window_size=50),
)

ds = xr.open_zarr("ensemble_embedded.zarr")
embedding = ds["embedding"]           # (n_window, window_size * n_statistic)
averages = ds["window_averages"]      # (n_window, n_statistic)
sim_ids = ds["simulation_id"]         # (n_window,) — which sim each window came from
```

## CLI

```bash
# Discover available strategies
tmelandscape embed-strategies list

# Run embedding
tmelandscape embed \
    ensemble_normalized.zarr \
    ensemble_embedded.zarr \
    --config embedding_config.json
```

The JSON summary printed to stdout includes the output path and the
applied config.

## The output Zarr

Dimensions: `(window, embedding_feature, statistic)`.

- `window` — flat index over all windows (across all simulations).
- `embedding_feature` — flat index of length `window_size * n_statistic`
  along the flattened-window axis.
- `statistic` — the (post-drop) original statistic names, carried for
  the `window_averages` companion array.

Coords along `window`:

- `simulation_id` (string)
- `window_index_in_sim` (int)
- `start_timepoint`, `end_timepoint` (int, inclusive)
- broadcast per-simulation coords from input: `parameter_combination_id`,
  `ic_id`, `parameter_<name>`

Data variables:

- `embedding` — shape `(n_window, window_size * n_statistic)`, float64.
- `window_averages` — shape `(n_window, n_statistic)`, float64.

Provenance `.zattrs`:

- `embedding_config` (JSON-serialised config),
- `source_input_zarr` (resolved input path),
- `source_variable`, `window_size`, `n_skipped_simulations`,
- `created_at_utc`, `tmelandscape_version`,
- Forwarded: `source_normalize_config`, `source_manifest_hash` (when
  the input carries them).

## What's *not* in step 4

- **Choosing `window_size` automatically.** The LCSS paper's W-sweep
  (over {30, 50, 80}) is a downstream analysis decision; the package
  ships no FNN / mutual-information heuristic in v0.5.0. Users supply
  the window size; future v0.5.x may add optimisation helpers if the
  workflow demands them.
- **Clustering.** Step 5 reads the `embedding` array from this Zarr
  and runs Leiden + Ward on the cluster means (see [ADR
  0007](../adr/0007-two-stage-leiden-ward-clustering.md) and the
  [roadmap](../development/ROADMAP.md)).
