# 03 — Phase 3 summarisation implementation

- **slug:** 03-summarize-implementation
- **status:** done (2026-05-13)
- **owner:** Claude Code orchestrator + buddy-pair team (3 Implementer + 3 Reviewer agents)
- **opened:** 2026-05-13
- **closed:** 2026-05-13
- **roadmap link:** Phase 3 — Step 3 summarisation (v0.2.0)

## Context

Implement step 3 of the pipeline: drive `spatialtissuepy` over each PhysiCell simulation output directory listed in a `SweepManifest`, producing per-timepoint spatial-statistic summaries, and aggregate them into a single chunked Zarr store for downstream consumption by step 3.5 (normalize) and step 4 (embedding).

Working references:

- `spatialtissuepy` is now a core dep (`git+...@c03cfa4`, no PyPI release). Native PhysiCell parser at `spatialtissuepy.synthetic.PhysiCellSimulation.from_output_folder(path)`; statistics registry at `spatialtissuepy.summary.StatisticsPanel`.
- The marimo oracle for the downstream `00_abm_normalization.py` reads a CSV named `normed_scaled_features_local_time_*.csv` whose columns are `time_step, sim_id, ...spatial stats..., M0_macrophage_density, ...`. The summarize step should produce data whose column names match this contract so the normalize step in Phase 3.5 can consume it cleanly (after the cell-density columns are dropped per ADR 0006).
- ADR 0003: ensemble store is Zarr (chunked, Dask-readable) per ensemble. Dims `(simulation, timepoint, statistic)`; coord arrays for parameter values + IC ids.
- AGENTS.md house-style invariants are binding (Pydantic configs, no global RNG, no silent network IO, etc.).

## Public API (frozen — buddy pairs must match these signatures exactly)

### Config — `tmelandscape.config.summarize`

```python
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field

class SummarizeConfig(BaseModel):
    """Config for `summarize_ensemble`. Frozen public contract."""
    statistics: list[str] = Field(
        default_factory=lambda: [
            # Cell-type composition
            "cell_counts",
            "cell_type_fractions",
            # Graph-based centrality (mean by cell type)
            "mean_degree_centrality_by_type",
            "mean_closeness_centrality_by_type",
            "mean_betweenness_centrality_by_type",
            # Cell-cell interactions
            "interaction_strength_matrix",
        ],
        description="StatisticsPanel keys to compute per timepoint. "
        "Default mirrors the LCSS paper's panel.",
    )
    graph_method: Literal["proximity", "knn", "delaunay", "gabriel"] = "proximity"
    graph_radius_um: float = Field(default=30.0, gt=0.0)
    n_workers: int = Field(default=1, ge=1, description="Dask workers for ensemble aggregation.")
    include_dead_cells: bool = False
```

### Synthetic fixture — `tests/data/synthetic_physicell/`

A hand-built PhysiCell-shaped directory tree that `spatialtissuepy.synthetic.PhysiCellSimulation.from_output_folder` can read end-to-end. Three subdirectories, each named after a manifest `simulation_id`:

```
tests/data/synthetic_physicell/
├── sim_000000_ic_000/
│   ├── PhysiCell_settings.xml          # cell-type id -> name mapping
│   ├── initial.xml                     # (optional, can be skipped)
│   ├── output00000000.xml              # timepoint 0
│   ├── output00000000_cells_physicell.mat
│   ├── output00000001.xml              # timepoint 1
│   ├── output00000001_cells_physicell.mat
│   └── output00000002.xml + .mat       # timepoint 2
├── sim_000001_ic_000/   (same layout)
└── sim_000002_ic_000/   (same layout)
```

Each `_cells_physicell.mat` carries ~20 cells of 3 cell types (`tumor`, `effector_T_cell`, `M0_macrophage`). Total fixture: 3 sims × 3 timepoints × 20 cells. Must be < 200 KB total so it can be tracked in git.

### PhysiCell adapter — `tmelandscape.summarize.spatialtissuepy_driver`

```python
import pandas as pd
from pathlib import Path
from tmelandscape.config.summarize import SummarizeConfig

def summarize_simulation(
    physicell_dir: Path,
    *,
    config: SummarizeConfig,
) -> pd.DataFrame:
    """Run spatialtissuepy over one PhysiCell output directory.

    Returns a long-form DataFrame with columns:
        time_index (int), time (float), statistic (str), value (float)
    Rows: one per (timepoint, statistic) pair. Matrix-valued statistics
    (e.g. interaction_strength_matrix) are exploded into multiple rows
    keyed by `interaction_<src>_<dst>` etc.
    """
    ...
```

### Ensemble aggregator — `tmelandscape.summarize.aggregate`

```python
import xarray as xr
from pathlib import Path
import pandas as pd
from tmelandscape.sampling.manifest import SweepManifest

def build_ensemble_zarr(
    manifest: SweepManifest,
    summary_frames: dict[str, pd.DataFrame],
    output_zarr: str | Path,
    *,
    chunk_simulations: int = 32,
    chunk_timepoints: int = -1,  # -1 = full axis (one chunk)
    chunk_statistics: int = -1,
) -> Path:
    """Aggregate per-simulation summary DataFrames into one chunked Zarr store.

    `summary_frames` is keyed by `simulation_id` and contains the long-form
    DataFrames returned by `summarize_simulation`. The Zarr store has:
        Dimensions: (simulation, timepoint, statistic)
        Coordinates:
            simulation: array of simulation_id strings
            timepoint: array of time-index ints (max across all sims)
            statistic: array of statistic-name strings
            parameter_<name>: 1D arrays along `simulation` carrying scaled
                parameter values from the manifest
            ic_id: 1D int array along `simulation`
            parameter_combination_id: 1D int array along `simulation`
    Variables:
        value: float64 array (simulation, timepoint, statistic). NaN for
            timepoints a given simulation didn't reach.
    Provenance:
        .zattrs include: tmelandscape_version, manifest_hash, created_at_utc,
        SummarizeConfig dump.
    Returns the absolute path of the written Zarr store.
    """
    ...
```

## Stream allocation (buddy pairs, two waves)

### Stream A — PhysiCell adapter + synthetic fixture

**Implementer A1** writes:
- `src/tmelandscape/summarize/spatialtissuepy_driver.py` (`summarize_simulation`).
- `tests/data/synthetic_physicell/<three sim dirs>/` (XML + .mat files; pure scipy.io / xml.etree to construct them).
- `tests/data/synthetic_physicell/build.py` — script that *regenerates* the fixture deterministically from a seed (so it can be rebuilt rather than blind-edited).
- `tests/unit/test_summarize_driver.py` — unit tests that load the fixture and assert the DataFrame shape + a few known values.

**Reviewer A2** audits A1's work read-only:
- Does the synthetic fixture parse cleanly via `PhysiCellSimulation.from_output_folder`?
- Does `summarize_simulation` cover the default `SummarizeConfig.statistics` list (no `KeyError` on any of them)?
- Are matrix-valued statistics (interactions) exploded sensibly (no information loss, names are reversible)?
- Reproducibility: same fixture seed → byte-identical fixture files.
- Edge cases: empty cell list, single cell, missing `PhysiCell_settings.xml`.
- Reports findings in markdown; does not edit code.

### Stream B — Ensemble aggregator (Zarr)

**Implementer B1** writes:
- `src/tmelandscape/summarize/aggregate.py` (`build_ensemble_zarr`).
- `src/tmelandscape/summarize/schema.py` — canonical names, helper to materialise dim/coord arrays from a manifest.
- `tests/unit/test_summarize_aggregate.py` — unit tests for build/roundtrip on a tiny manifest + synthetic summary frames.

**Reviewer B2** audits B1's work:
- Chunking semantics (does `chunk_simulations=32` produce 32-sim chunks on a 100-sim manifest?).
- Coord array alignment (does `parameter_<name>` align with the `simulation` dim correctly?).
- NaN handling for ragged timepoints (sims of different lengths).
- Round-trip via `xarray.open_zarr` returns equivalent data (no silent dtype coercion).
- Provenance .zattrs present and valid JSON.
- Edge cases: empty manifest (zero rows), one sim, one timepoint.

### Stream C — SummarizeConfig + statistics-name dictionary

**Implementer C1** writes:
- `src/tmelandscape/config/summarize.py` (`SummarizeConfig` Pydantic model).
- `src/tmelandscape/summarize/registry.py` — a thin layer that translates `SummarizeConfig.statistics` names into the actual `spatialtissuepy.summary.StatisticsPanel` calls + centrality calls + colocalization calls. **Important**: this is the only file that should know how spatialtissuepy is organised; the rest of `summarize/` consumes a single function from `registry.py`.
- `tests/unit/test_summarize_config.py` — config validation; default panel is the LCSS panel; rejects unknown statistic names.

**Reviewer C2** audits C1's work:
- Does the registry handle every statistic name in `SummarizeConfig.statistics` default?
- Are unknown stat names rejected at config-validation time (Pydantic validator) or only at runtime (worse)?
- Is the registry layer a clean abstraction over `spatialtissuepy.{summary,network,statistics}` modules?
- Does `graph_method` correctly map to `CellGraph.from_spatial_data(method=...)`?

## House-style invariants (binding on every Implementer)

1. Pydantic models for public configs.
2. mypy strict-clean on every new file.
3. No global numpy random. Pass seeds explicitly.
4. No silent network IO.
5. No new files outside the paths listed above.
6. Tests run in < 2s each (mark `@pytest.mark.slow` otherwise).
7. NO modifications to `pyproject.toml` (orchestrator's job).

## Buddy-pair workflow

Round 1: Implementers A1, B1, C1 run in parallel; each produces a written report listing files created, test counts, and any deviations from the contract.

Round 2: Reviewers A2, B2, C2 run in parallel against their partner's output. **Reviewers may NOT edit code.** Each produces a findings report with severity-tagged items (BUG / RISK / SMELL).

Round 3 (orchestrator):
1. Apply minor Reviewer fixes directly (SMELL items, trivial typos).
2. For BUG / RISK items, either fix directly or send back to the Implementer with a targeted SendMessage prompt.
3. Once each pair signs off, integrate the streams:
   - `src/tmelandscape/summarize/__init__.py` — top-level `summarize_ensemble(manifest, physicell_root, output_zarr, config)`.
   - `src/tmelandscape/cli/summarize.py` + wire into `cli/main.py`.
   - `src/tmelandscape/mcp/tools.py` — add `summarize_ensemble_tool`.
   - `tests/integration/test_summarize_end_to_end.py` — Python API + CLI + MCP roundtrip on the synthetic fixture.
   - `docs/concepts/summarize.md` fill-out.

## Session log

- 2026-05-13 (Claude Code orchestrator): Recon (WebFetch + general-purpose agent recon of spatialtissuepy) complete; spatialtissuepy installed and importable; task file frozen. Ready to spawn Round 1 implementers.
