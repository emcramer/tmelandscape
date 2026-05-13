# 0001 — Package name: `tmelandscape`

- **Status:** Accepted
- **Date:** 2026-05-12
- **Deciders:** Eric, Claude

## Context

The package needs a short, memorable import name that signals its purpose (tumor-microenvironment state landscapes) and pairs well with its sibling packages `tissue_simulator` and `spatialtissuepy`.

## Decision

Use `tmelandscape` as the PyPI distribution name and the Python import name. CLI entry points: `tmelandscape` (main CLI) and `tmelandscape-mcp` (MCP server).

## Consequences

- Clear domain signal (TME = tumor microenvironment + landscape).
- Composes naturally in code: `from tmelandscape.embedding import optimize_embedding`.
- The name is sufficiently unique on PyPI to be reservable (verify before v0.1.0).

## Alternatives considered

- `landscapegen` — too generic, doesn't signal TME domain.
- `tmestate` — emphasises the output (states) over the artefact (landscape).
- `tnbc-trajectory` — too narrow; would lock in TNBC framing even though the methodology is cancer-type-agnostic.
