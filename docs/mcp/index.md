# MCP server (for LLM agents)

`tmelandscape` ships a Model Context Protocol (MCP) server at the `tmelandscape-mcp` console entry point. The server exposes the package's public API as typed tools that agents can call directly.

## Quick start (Claude Code, Cursor, etc.)

```bash
uv run tmelandscape-mcp
```

The server speaks MCP over stdio. Add it to your IDE's MCP configuration as a stdio server with command `uv run tmelandscape-mcp`.

## Tools (planned)

| Tool | Phase | Purpose |
| --- | --- | --- |
| `ping` | 0 | Health check; returns `tmelandscape.__version__`. |
| `tmelandscape.generate_sweep` | 2 | Sample parameter space + ICs → sweep manifest. |
| `tmelandscape.summarize_ensemble` | 3 | Drive spatialtissuepy + aggregate to Zarr. |
| `tmelandscape.optimize_embedding` | 4 | FNN + MI search for dim/lag. |
| `tmelandscape.fit_landscape` | 5 | One-shot: embed + cluster from a Zarr store. |
| `tmelandscape.describe_landscape` | 5 | Open a `.tmelandscape/` bundle, return summary JSON. |

Each tool's full schema (Pydantic-derived) is available through standard MCP discovery: `client.list_tools()`.

## Design contract

`tmelandscape` adheres to the invariant that **public Python API = MCP tools = CLI verbs**. Anything you can do from `python -c "import tmelandscape; …"` is also available as an MCP tool with an identical typed contract.
