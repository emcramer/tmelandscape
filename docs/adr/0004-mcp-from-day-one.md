# 0004 — MCP server is a first-class surface, built from day one

- **Status:** Accepted
- **Date:** 2026-05-12
- **Deciders:** Eric, Claude

## Context

The intended consumers of `tmelandscape` include LLM agents driving multi-step workflows (parameter sweep → run sims externally → summarise → embed → cluster). Bolting on an MCP server post-hoc to a package designed only for human users tends to expose ill-shaped APIs and require breaking changes.

## Decision

Build the MCP server (`tmelandscape-mcp`) from day one. Use `fastmcp` (FastMCP 2.x). Every top-level Python function in the public API has a corresponding MCP tool with:

- A short docstring (one-sentence summary + arguments).
- A JSON Schema generated from the Pydantic config model.
- Example invocations in the tool description.

This forces all public functions to take Pydantic config objects (not loose kwargs) and to be deterministic and JSON-serialisable at their I/O boundary — both desirable independently of MCP.

## Consequences

- "Public API = MCP tools = CLI verbs" becomes a hard invariant (codified in `AGENTS.md`).
- Adding a public function obligates the author to register an MCP tool and a CLI verb in the same commit.
- Server transport defaults to stdio (works with Claude Code, Cursor, IDEs); HTTP transport planned for remote agents.
- The synthetic fixture is shipped as an MCP resource so agents can sanity-check the pipeline without external data.

## Alternatives considered

- **MCP later (post v1.0):** rejected because retrofitting tends to leak design debt into the public API.
- **CLI only:** weaker affordance for agents; structured outputs require ad-hoc JSON parsing.
- **Python API only:** the package would still be agent-usable, but the friction of writing Python in an agent loop is higher than calling a typed tool.
