# tmelandscape

Generate tumor microenvironment (TME) state landscapes from agent-based model simulation ensembles.

> **Status:** pre-alpha (v0.0.1). API is not yet stable.

## What it does

Given a parameter space for an agent-based model (ABM) of the tumor microenvironment, `tmelandscape`:

1. **Samples** the parameter space (Latin Hypercube by default) and pairs each combination with initial cell positions from [`tissue_simulator`](https://github.com/emcramer/tissue_simulator).
2. *(External step — out of scope.)* You run the ABM (PhysiCell) for each manifest row.
3. **Summarises** each simulation with spatial statistics via [`spatialtissuepy`](https://github.com/emcramer/spatialtissuepy); aggregates into a chunked Zarr store.
4. **Embeds** the time series with delay-coordinate (Takens) embedding, optimised by False Nearest Neighbours and mutual information.
5. **Clusters** the embedding to identify discrete TME states.

The methodology follows Cramer et al. (TNBC manuscript) and Cramer, Heiser, Chang (LCSS short paper). Citations are tracked in [`CITATION.cff`](https://github.com/emcramer/tmelandscape/blob/main/CITATION.cff).

## Audience

Both human scientists and LLM agents. Every feature is reachable from three surfaces:

- **Python API** — `from tmelandscape import …`
- **CLI** — `tmelandscape <verb>`
- **MCP server** — `tmelandscape-mcp` (typed tools for agents)

## Start here

- [Getting started](getting-started.md)
- [Pipeline concepts](concepts/sampling.md)
- [MCP server reference](mcp/index.md) (for agent users)
- [Architecture decisions](adr/README.md)
- [Roadmap](development/ROADMAP.md) and [current status](development/STATUS.md)
