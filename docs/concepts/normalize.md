# Concept: spatial-statistic normalisation (step 3.5)

Step 3.5 takes the raw ensemble Zarr from step 3 and writes a new Zarr containing both the unchanged raw `value` array and a freshly computed normalised array. The raw store is never modified; the new store is what step 4 (embedding) consumes.

The default algorithm is within-timestep normalisation, faithfully porting the reference oracle (`reference/00_abm_normalization.py`): per-timestep mean → Yeo-Johnson power transform → z-score → re-add per-step mean. The mean-preservation step keeps the temporal trend visible to the embedding step rather than zero-meaning it away.

## Binding invariants

Two project-owner directives shape this step (see [ADR 0006](../adr/0006-normalize-as-pipeline-step.md) and [ADR 0009](../adr/0009-no-hardcoded-statistics-panel.md)):

1. **Never overwrite raw data.** `normalize_ensemble` reads the input Zarr lazily, never writes to it, and refuses to clobber an existing output path. Tests assert byte-equality of every file in the input store before and after every call.
2. **No feature-drop default.** `NormalizeConfig.drop_columns` defaults to `[]`. Earlier iterations of the reference dropped six cell-density columns; that choice was specific to one application of the method, not a property of the algorithm.

## Inputs

- The ensemble Zarr produced by `tmelandscape summarize` (or its Python / MCP equivalents).
- A `NormalizeConfig` (Pydantic) selecting the strategy and any optional column drops.

## Algorithm — `within_timestep` (default)

For each `(timepoint,)` slab of the `(n_sim, n_stat)` value matrix:

1. Compute per-statistic mean across simulations (`m_t`).
2. For each statistic column with non-zero variance: apply `scipy.stats.yeojohnson` to the finite slice.
3. Apply `scipy.stats.zscore` per column. Zero-variance columns pass through unchanged.
4. NaN entries that survived (e.g. a cell-type fraction absent for the entire timestep) are replaced with `config.fill_nan_with` (default `0.0`).
5. With `preserve_time_effect=True` (default), re-add `m_t` to every column so the temporal trend survives into the embedding step.

## Discovering available strategies

`tmelandscape` ships two strategies in v0.4.0: `within_timestep` (the reference algorithm) and `identity` (passthrough; useful as a baseline / for diagnosing orchestrator plumbing). The catalogue is discoverable from every surface:

```bash
# CLI
tmelandscape normalize-strategies list
```

```python
# Python
from tmelandscape.cli.normalize_strategies import _catalogue
print(_catalogue())
```

MCP agents call the same catalogue via the `list_normalize_strategies` tool.

## `NormalizeConfig` fields

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `strategy` | `Literal["within_timestep"]` | `"within_timestep"` | Algorithm to apply. |
| `preserve_time_effect` | `bool` | `True` | Re-add per-timestep mean (reference behaviour). |
| `drop_columns` | `list[str]` | `[]` | Statistic-coord names to drop *before* normalisation. Explicit opt-in only. |
| `fill_nan_with` | `float` | `0.0` | Scalar substituted for any NaN that remains after the transform. NaN is rejected at validation time to keep the JSON round-trip lossless. |
| `output_variable` | `str` | `"value_normalized"` | Name of the new array in the output Zarr. Must not equal `"value"` — the orchestrator preserves the raw under that name. |

## Code example

```python
from pathlib import Path
import xarray as xr

from tmelandscape.config.normalize import NormalizeConfig
from tmelandscape.normalize import normalize_ensemble

normalize_ensemble(
    "ensemble.zarr",
    "ensemble_normalized.zarr",
    config=NormalizeConfig(),
)

ds = xr.open_zarr("ensemble_normalized.zarr")
raw = ds["value"]               # passed through verbatim
normed = ds["value_normalized"] # the new array

# With preserve_time_effect=True, the per-(timepoint, statistic) mean is preserved.
```

## CLI

```bash
# Discover available strategies
tmelandscape normalize-strategies list

# Run normalisation
tmelandscape normalize \
    ensemble.zarr \
    ensemble_normalized.zarr \
    --config normalize_config.json
```

A JSON summary (output path + applied config) is printed to stdout.

## The output Zarr

Same dimensions and coordinates as the input. Two data variables:

- `value` — the raw array, copied verbatim. Available for raw-vs-normalised diffing.
- `value_normalized` (or whatever name `config.output_variable` carries) — the normalised array.

Chunk grid inherits from the input where possible so downstream Dask reads stay aligned. Provenance `.zattrs` carry `normalize_config` (JSON-serialised config), `created_at_utc`, `tmelandscape_version`, and `source_manifest_hash` (forwarded from the input when present).

## What's *not* in step 3.5

- **Running the simulations** (external step 2).
- **Recomputing spatial statistics** (step 3 — re-run `tmelandscape summarize` if you need a different panel).
- **Time-delay embedding** (step 4) and **two-stage clustering** (step 5) — see the [roadmap](../development/ROADMAP.md).
