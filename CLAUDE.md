# CLAUDE.md

This is a Claude Code-specific stub. **The canonical agent instructions live in [`AGENTS.md`](AGENTS.md)** — read that first.

## Claude-specific notes

- This repo uses `uv` for environment management. Prefer `uv run <cmd>` over activating the venv manually.
- The MCP server (`tmelandscape-mcp`) is the package's primary surface for agent-driven workflows. When implementing or modifying a public function, update the corresponding MCP tool in `src/tmelandscape/mcp/tools.py` in the same commit.
- Reference scripts are gitignored and live in `reference/` (copied from Eric's OneDrive). Treat them as read-only oracles.
- Permission-sensitive operations:
  - Network IO (Zenodo fetch, GitHub clones for `tissue_simulator` / `spatialtissuepy`) is allowed in `scripts/` only.
  - Never run `uv sync` without first checking that `pyproject.toml` changes are intentional.
- Use `docs/development/STATUS.md` as your session-resume doc.

## Useful slash commands

(None defined yet. Add project-specific slash commands here as they emerge.)
