# Getting started

## Install

Requires Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/emcramer/tmelandscape
cd tmelandscape
uv sync --all-extras
```

This installs the package plus all optional dependency groups (`viz`, `mcp`, `dev`, `docs`).

## Sanity checks

```bash
uv run pytest                              # unit + integration tests
uv run mkdocs build --strict               # docs build cleanly
uv run tmelandscape --help                 # CLI is wired up
uv run tmelandscape-mcp --help             # MCP server is wired up
```

## Quickstart (planned API — not yet implemented)

The full pipeline below will be available in v0.4.0 (Phase 5):

```python
from tmelandscape import (
    SweepConfig, ParameterSpec, generate_sweep,
    summarize_ensemble,
    Landscape, LandscapeConfig,
)

# 1. Sample parameter space
cfg = SweepConfig(
    parameters=[
        ParameterSpec(name="r_exh", low=1e-4, high=10**-2.5, scale="log10"),
        ParameterSpec(name="r_adh", low=0,    high=5,        scale="linear"),
    ],
    n_parameter_samples=1000,
    n_initial_conditions=100,
    sampler="lhs",
    seed=20260512,
)
manifest = generate_sweep(cfg, initial_conditions_dir="ics/")
manifest.save("sweep_manifest.json")

# 2. (You run PhysiCell externally, producing one output dir per manifest row.)

# 3. Summarise each simulation
summarize_ensemble(
    manifest_path="sweep_manifest.json",
    physicell_root="/scratch/sims/",
    output_zarr="ensemble.zarr",
)

# 4 + 5. Fit the landscape
ls = Landscape.fit("ensemble.zarr", config=LandscapeConfig())
ls.save("tnbc_landscape.tmelandscape/")
```

## Next

- Read the [pipeline concepts](concepts/sampling.md) for what each step does and why.
- Read the [MCP reference](mcp/index.md) if you're driving the pipeline from an agent.
