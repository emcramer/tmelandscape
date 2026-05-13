# 02 — Phase 2 sampling implementation

- **slug:** 02-sampling-implementation
- **status:** done (2026-05-13)
- **owner:** Claude Code orchestrator + three delegated streams (A/B/C)
- **opened:** 2026-05-13
- **closed:** 2026-05-13
- **roadmap link:** Phase 2 — Synthetic fixture + Step 1 (v0.1.0)

## Context

Implement step 1 of the pipeline: parameter sampling + initial-condition generation, producing a `SweepManifest` that the external step-2 (PhysiCell-running) agent will consume.

Working reference: [`physim-calibration`](https://github.com/emcramer/physim-calibration) at `/tmp/physim-calibration/` (cloned during recon). Its `code/sampling.py` (`LHSampler` class) is the sampling-pattern oracle. Its `00-multi-config-generation.ipynb` shows how parameter sweeps are constructed and how initial-conditions are attached combinatorially. `tissue_simulator` (already a core dep, installed from git+URL) replaces `physim-calibration`'s static `cell_patterns/` directory with on-the-fly replicate generation that targets similar spatial statistics (~10% error per metric across replicates).

User decisions:

- **Default LHS backend:** `pyDOE3` (per earlier preference). `scipy.stats.qmc` as alternative.
- **tissue_simulator** is a **core dep** (git+URL with `allow-direct-references = true`).

## Public API (frozen — streams must match these signatures exactly)

### Config models — `tmelandscape.config.sweep`

```python
from typing import Literal
from pydantic import BaseModel, Field, field_validator

class ParameterSpec(BaseModel):
    """One ABM parameter to sweep over."""
    name: str = Field(..., description="Parameter name. Free-form; e.g. a PhysiCell XML dotted path.")
    low: float
    high: float
    scale: Literal["linear", "log10"] = "linear"

    @field_validator("high")
    @classmethod
    def _high_above_low(cls, v: float, info) -> float:
        if "low" in info.data and v <= info.data["low"]:
            raise ValueError("high must be strictly greater than low")
        return v


class SweepConfig(BaseModel):
    """Top-level config for `generate_sweep`."""
    parameters: list[ParameterSpec] = Field(..., min_length=1)
    n_parameter_samples: int = Field(..., gt=0, description="N parameter combinations to draw.")
    n_initial_conditions: int = Field(..., gt=0, description="N replicate ICs per parameter combination.")
    sampler: Literal["pyDOE3", "scipy-lhs", "scipy-sobol", "scipy-halton"] = "pyDOE3"
    seed: int = Field(..., description="RNG seed. Drives both parameter sampling and IC replicate generation.")
```

### Manifest — `tmelandscape.sampling.manifest`

```python
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel, Field

class SweepRow(BaseModel):
    """One simulation in the sweep = (parameter combination, initial condition)."""
    simulation_id: str = Field(..., description="Unique id, e.g. 'sim_000042_ic_007'.")
    parameter_combination_id: int = Field(..., ge=0)
    ic_id: int = Field(..., ge=0)
    parameter_values: dict[str, float] = Field(..., description="Param name -> value.")
    ic_path: str = Field(..., description="Relative path to the IC csv file (under initial_conditions_dir).")


class SweepManifest(BaseModel):
    """Artefact handed off to the external step-2 (PhysiCell-running) agent."""
    config: "SweepConfig"  # from tmelandscape.config.sweep
    initial_conditions_dir: str = Field(..., description="Path containing IC CSVs, relative to manifest file.")
    rows: list[SweepRow]
    created_at: datetime = Field(default_factory=datetime.utcnow)
    tmelandscape_version: str

    def save(self, path: str | Path) -> None:
        """Persist to disk. Writes both <path>.json and <path>.parquet (sibling files)."""
        ...

    @classmethod
    def load(cls, path: str | Path) -> "SweepManifest":
        """Load from <path>.json (parquet is canonical for the rows table; json carries metadata)."""
        ...
```

### Samplers — `tmelandscape.sampling.lhs` and `tmelandscape.sampling.alternatives`

```python
# tmelandscape.sampling.lhs
import numpy as np
def lhs_unit_hypercube(n_samples: int, n_dims: int, seed: int) -> np.ndarray:
    """Draw N samples in [0,1]^d using pyDOE3 LHS. Returns (n_samples, n_dims) array."""

# tmelandscape.sampling.alternatives
def scipy_lhs_unit_hypercube(n_samples: int, n_dims: int, seed: int) -> np.ndarray: ...
def sobol_unit_hypercube(n_samples: int, n_dims: int, seed: int) -> np.ndarray: ...
def halton_unit_hypercube(n_samples: int, n_dims: int, seed: int) -> np.ndarray: ...

# tmelandscape.sampling (top-level helper, lives in sampling/__init__.py — written by integrator)
def draw_unit_hypercube(*, sampler: str, n_samples: int, n_dims: int, seed: int) -> np.ndarray:
    """Dispatch to the correct backend by `sampler` name."""
```

### Tissue-simulator wrapper — `tmelandscape.sampling.tissue_init`

```python
from pathlib import Path

def generate_initial_conditions(
    *,
    n_replicates: int,
    output_dir: str | Path,
    seed: int,
    target_n_cells: int = 500,
    cell_radii_um: tuple[float, float] = (8.0, 12.0),
    tissue_dims_um: tuple[float, float, float] = (400.0, 400.0, 20.0),
    similarity_tolerance: float = 0.10,
) -> list[Path]:
    """Generate `n_replicates` CSVs of initial cell positions in `output_dir`.

    Uses `tissue_simulator.ReplicateGenerator` to produce replicates whose
    pairwise spatial statistics are within `similarity_tolerance` (default 10%).
    Returns the list of CSV paths (absolute), one per replicate.

    Output CSV columns: x, y, z, radius, cell_type, is_boundary (per tissue_simulator).
    """
    ...
```

## Stream allocation (parallel)

### Stream A — config & manifest

Files to create:

- `src/tmelandscape/config/sweep.py` — `ParameterSpec`, `SweepConfig`.
- `src/tmelandscape/sampling/manifest.py` — `SweepRow`, `SweepManifest`, `.save()`, `.load()`.

Tests to create:

- `tests/unit/test_config_sweep.py` — Pydantic validation (low<high, n_samples>0, etc.); round-trip dict ↔ model.
- `tests/unit/test_sampling_manifest.py` — `save()`/`load()` round-trip with a tiny manifest; verify both JSON and Parquet sibling files written; verify `tmelandscape.__version__` is captured.

### Stream B — samplers

Files to create:

- `src/tmelandscape/sampling/lhs.py` — pyDOE3 LHS in unit hypercube.
- `src/tmelandscape/sampling/alternatives.py` — scipy.qmc LHS / Sobol / Halton.

Tests to create:

- `tests/unit/test_sampling_lhs.py` — same seed → same samples; shape correct; samples in [0,1]; no duplicates within a single draw.
- `tests/unit/test_sampling_alternatives.py` — same checks for each scipy backend.

### Stream C — tissue_simulator wrapper

Files to create:

- `src/tmelandscape/sampling/tissue_init.py` — `generate_initial_conditions` wrapping `tissue_simulator.ReplicateGenerator`.

Tests to create:

- `tests/unit/test_sampling_tissue_init.py` — call with `n_replicates=2, target_n_cells=20` (smallest practical); verify (a) exactly 2 CSVs written, (b) CSV columns include `x, y, z, radius, cell_type` (per tissue_simulator), (c) same seed → identical content across runs.
- Mark the test `@pytest.mark.slow` if a single call exceeds ~3 seconds.

## Integration (orchestrator, after all three streams return)

- `src/tmelandscape/sampling/__init__.py` — re-exports + `draw_unit_hypercube` dispatcher + top-level `generate_sweep(config: SweepConfig, initial_conditions_dir: Path) -> SweepManifest` that ties everything together (sample → scale to bounds with linear/log10 → call `generate_initial_conditions` → build `SweepRow` list → return `SweepManifest`).
- `src/tmelandscape/cli/sample.py` — Typer subcommand `tmelandscape sample` (config from YAML or JSON file).
- Wire into `src/tmelandscape/cli/main.py`.
- `src/tmelandscape/mcp/tools.py` (new) — MCP tool `tmelandscape.generate_sweep`.
- Update `src/tmelandscape/mcp/server.py` to register the new tool.
- `tests/integration/test_sample_end_to_end.py` — Python API + CLI + MCP all produce identical manifests for the same config/seed.
- Fill out `docs/concepts/sampling.md`.

## House-style invariants (binding on all streams)

1. **Use Pydantic, not loose kwargs.** Public functions take `SweepConfig` or a Pydantic argument model, not raw dicts.
2. **Type hints on every public callable.** mypy strict must pass on the new files.
3. **No global numpy random.** Always plumb `seed` through and instantiate `np.random.default_rng(seed)` locally.
4. **No silent network IO** in the new modules. tissue_simulator is local once installed.
5. **No comments explaining what well-named code already says.** Only WHY for non-obvious decisions.
6. **No new files outside the paths listed above.** No README touch-ups, no CLI/MCP changes (those are mine).
7. **Tests run in <2 s each by default;** anything slower marked `@pytest.mark.slow`.

## Session log

- 2026-05-13 (Claude Code orchestrator): Recon complete; user resolved LHS-default + tissue_simulator-placement decisions; task file frozen; ready to delegate streams A/B/C in parallel.
