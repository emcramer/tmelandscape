# tmelandscape

[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD_3--Clause-blue.svg)](LICENSE)

**tmelandscape** generates tumor microenvironment (TME) state landscapes from agent-based model (ABM) simulation ensembles. It implements the parameter sampling, spatial-statistic summarisation, time-delay embedding, and clustering steps of the trajectory-landscape pipeline described in Cramer et al. (TNBC manuscript) and Cramer, Heiser, Chang (LCSS short paper).

> **Status:** pre-alpha (v0.0.1). API is not yet stable.

## Pipeline scope

`tmelandscape` implements steps **1**, **3**, **4**, and **5** below; step 2 (running ABM simulations) is handled by a separate tool.

1. **Sample** ABM parameter space (Latin Hypercube via [pyDOE3](https://pypi.org/project/pyDOE3/)) and pair with initial cell positions from [`tissue_simulator`](https://github.com/emcramer/tissue_simulator). Produces a sweep manifest.
2. *(External)* **Run** PhysiCell simulations for each manifest row. Out of scope.
3. **Summarise** each simulation with spatial statistics via [`spatialtissuepy`](https://github.com/emcramer/spatialtissuepy); aggregate into a chunked Zarr store.
4. **Embed** the spatial-statistic time series with time-delay (Takens) embedding; optimise dimension via False Nearest Neighbours and lag via mutual information.
5. **Cluster** the embedding to identify discrete TME states (default: hierarchical agglomerative + Ward).

## Quick start

```bash
# 1. Install uv (https://docs.astral.sh/uv/)
# 2. Sync the environment
uv sync --all-extras

# 3. Run tests
uv run pytest

# 4. Serve the docs locally
uv run mkdocs serve

# 5. Start the MCP server (for LLM agents)
uv run tmelandscape-mcp
```

## Documentation

Full docs live at <https://emcramer.github.io/tmelandscape/> (once published). Locally:

```bash
uv run mkdocs serve
```

Key documents:

- [Project roadmap](docs/development/ROADMAP.md)
- [Current status / handoff](docs/development/STATUS.md)
- [Architecture Decision Records](docs/adr/)
- [Agent handoff conventions](AGENTS.md)

## License

BSD 3-Clause. See [LICENSE](LICENSE).

## Citing

See [CITATION.cff](CITATION.cff) for the software citation; cite the linked manuscripts for the methodology.
