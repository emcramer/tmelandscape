# AGENTS.md — instructions for AI coding agents and human contributors

> Read this file at the start of every session. The contract below is binding for both humans and LLMs.

## Mission

`tmelandscape` generates tumor microenvironment state landscapes from agent-based model (ABM) simulation ensembles, following the methods in `docs/literature/`. It implements **steps 1, 3, 4, and 5** of a five-step pipeline; step 2 (running ABM simulations) is intentionally out of scope.

The package targets **both human scientists and LLM agents**. Every feature must be usable from the Python API, the CLI, and the MCP server.

## v1 scope boundaries (do not violate without an ADR)

- **In scope:** parameter sampling (LHS / Sobol / Halton), tissue_simulator-driven initial conditions, spatialtissuepy-driven summarisation, Zarr aggregation, time-delay embedding with FNN+MI optimisation, hierarchical clustering, the `Landscape` facade, visualisation helpers, CLI, MCP server.
- **Out of scope for v1:** running PhysiCell simulations (step 2), MSM / MDP / intervention design (LCSS paper, sections IV–VI), projecting new/clinical data onto a fitted landscape, SLURM-specific helpers.

If you find yourself wanting to add an out-of-scope feature, stop and write an ADR proposing the scope change.

## Canonical commands

```bash
# Sync environment (run after any pyproject.toml change)
uv sync --all-extras

# Run the test suite
uv run pytest                  # default (skips opt-in real-data tests)
uv run pytest -m real          # opt-in real-data integration (requires fetched example data)

# Lint / format / type-check
uv run ruff check .
uv run ruff format .
uv run mypy src

# Docs
uv run mkdocs serve            # local preview at http://127.0.0.1:8000
uv run mkdocs build --strict   # CI build (must be strict-clean)

# MCP server
uv run tmelandscape-mcp        # stdio transport (for IDEs / Claude Code)
uv run tmelandscape-mcp --http # HTTP transport (for remote agents) [planned]

# Fetch the three example PhysiCell sim outputs
uv run python scripts/fetch_example_data.py            # from Zenodo
uv run python scripts/fetch_example_data.py --from-local <path>  # from local copy
```

## House-style invariants

1. **Pydantic configs everywhere.** Public functions take a single `*Config` Pydantic model, not a long list of keyword arguments. This guarantees JSON-Schema availability for the MCP server and CLI.
2. **No global RNG.** All randomness flows through `tmelandscape.utils.seeding.SeedSource`. Library code never calls `np.random.seed`, `random.seed`, or reads `np.random.default_rng()` without an explicit seed argument.
3. **Provenance sidecars are required.** Every artefact written to disk has a `<artefact>.provenance.json` next to it (or as a `.provenance` Zarr group). Use `tmelandscape.utils.provenance.write_sidecar`.
4. **Lazy by default.** Zarr stores are opened with Dask; concrete arrays are materialised only at the public-API boundary or inside CLI commands.
5. **Public API = MCP tools = CLI verbs.** Three surfaces, one set of behaviours. Adding a public function obligates you to expose it through the MCP server (`src/tmelandscape/mcp/tools.py`) and the CLI (`src/tmelandscape/cli/`).
6. **No silent network IO inside library code.** If a function needs to fetch from Zenodo, it lives under `scripts/` or `src/tmelandscape/io/`, takes an explicit URL/DOI, and emits a structured log line.
7. **Tests use the synthetic fixture by default.** The opt-in real-data fixture (`tests/data/example_physicell/`) is gated by `pytest -m real` and is **never** required for default CI.

## Before you start a session

- [ ] Read `docs/development/STATUS.md`. That is the authoritative "where are we" doc.
- [ ] Scan ADRs added since your last session: `ls -t docs/adr/*.md | head`.
- [ ] If a `tasks/<slug>.md` exists for your work, read it and update the `session-log`.

## Before you end a session

- [ ] Update `docs/development/STATUS.md` (current focus, blockers, last-handoff notes).
- [ ] For any non-trivial decision: write an ADR in `docs/adr/NNNN-kebab-title.md`. Numbered, append-only.
- [ ] If your work spans more than one session, leave a `tasks/<slug>.md` work-file. Use the template in `tasks/README.md`.
- [ ] Commit using conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).

## Reference scripts (oracle, read-only)

Authoritative reference code lives in `/Users/cramere/OneDrive - Oregon Health & Science University/graduate/knowledgebase/00-projects/parameter-exploration/code` on Eric's local machine. When working on a pipeline step, ask Eric which scripts/notebooks are the oracle for that step. Copy them into a **gitignored** `reference/` directory and treat as read-only.

**Agents must not invent ABM-specific behaviour from first principles** when reference code exists. Always cross-check numerical outputs against the reference scripts before declaring a step complete.

## Repo layout (abbreviated)

```
src/tmelandscape/   # library code (sampling/ summarize/ embedding/ cluster/ landscape/ viz/ io/ cli/ mcp/ utils/ config/)
tests/              # unit/ integration/ real_data/ + data/{synthetic,example}_physicell/
docs/               # mkdocs site + adr/ + development/{STATUS,ROADMAP}.md + concepts/ tutorials/ mcp/
tasks/              # per-task work-files (markdown)
reference/          # gitignored; reference scripts copied locally
scripts/            # operational scripts (e.g. fetch_example_data.py)
examples/           # tutorial notebooks
```

## When in doubt

Stop, write down what you're unsure about in `docs/development/STATUS.md` under "Open questions", and ask Eric. Do not silently make scope-affecting decisions.
