# STATUS — current session resume doc

> Updated at the **end** of every agent session. New agents read this **first**.

## Current focus

**Phase 1 — Reference audit: complete.** All four architectural questions resolved; ADRs 0006 + 0007 written; `normalize/` + reshaped `cluster/` submodules scaffolded; deps added. Ready to tag `v0.0.1` and proceed to Phase 2 (sampling).

## In-flight tasks

_None._ (`tasks/00-reference-audit.md` closed 2026-05-12; see repo `tasks/` directory.)

## Recently completed (this session, 2026-05-12)

- Wrote and approved the development plan.
- Created repo directory skeleton (`src/tmelandscape/{config,sampling,summarize,embedding,cluster,landscape,viz,io,cli,mcp,utils}/`, `tests/`, `docs/`, `tasks/`, `examples/`, `scripts/`, `.github/workflows/`).
- Wrote `pyproject.toml` (uv + hatchling), `LICENSE` (BSD-3-Clause), `CITATION.cff`, `README.md`, `.gitignore`, `.python-version`.
- Wrote `AGENTS.md` (cross-tool contract) and `CLAUDE.md` (Claude-specific stub).
- Wrote ADRs 0001–0005 + `docs/adr/README.md`.
- Scaffolded mkdocs site (`mkdocs.yml`, `docs/index.md`, `docs/getting-started.md`, `docs/concepts/*`, `docs/api/index.md`, `docs/tutorials/index.md`, `docs/mcp/index.md`).
- Scaffolded library entry points: `src/tmelandscape/__init__.py`, CLI (`tmelandscape` with `version` subcommand), MCP server (`tmelandscape-mcp` with `ping` tool), structlog-based logging utility.
- Wrote `scripts/fetch_example_data.py` (Zenodo-stub + `--from-local` mode) and `tests/data/example_physicell/README.md`.
- Wrote `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `.github/workflows/docs.yml`.
- Wrote Phase 0 smoke tests (4 passing: version constant, CLI version command, MCP server name, MCP ping).
- Wrote `tasks/README.md` (template for per-task work-files).

**Bootstrap verification (all green):**

- `uv sync --all-extras` — succeeds.
- `uv run pytest -q` — 4 passed, 1 deselected (`-m "not real"` excludes real-data test).
- `uv run ruff check .` — clean.
- `uv run ruff format --check .` — clean (21 files formatted).
- `uv run mypy src` — clean (15 source files, strict mode).
- `uv run mkdocs build --strict` — exit 0.
- `uv run tmelandscape version` — prints `0.0.1`.
- `uv run tmelandscape-mcp` — boots; `ping()` returns `{'status': 'ok', 'version': '0.0.1'}`.

## Blockers

_None._

## Open questions (for Eric)

### Resolved this session

- ~~Reference scripts inventory~~ → `00/01/02_abm_*` are the landscape-generation oracles; `03_abm+` is downstream analysis. Plain `utils.py` is also required.
- ~~Zenodo upload~~ → Live at [10.5281/zenodo.20148946](https://doi.org/10.5281/zenodo.20148946); fetch script downloads + MD5-verifies + extracts.
- ~~Clustering pipeline~~ → Two-stage Leiden + Ward-on-means as default ([ADR 0007](../adr/0007-two-stage-leiden-ward-clustering.md)).
- ~~Normalization placement~~ → New `tmelandscape.normalize` submodule between summarize and embedding ([ADR 0006](../adr/0006-normalize-as-pipeline-step.md)).
- ~~Reference script format~~ → Marimo notebooks stay as the oracle in `reference/`; port relevant cells directly into `tmelandscape` modules during each phase.
- ~~Missing dependencies~~ → `leidenalg`, `python-igraph`, `networkx`, `scikit-learn` added to core deps in `pyproject.toml`.

### Still open

1. **Python version baseline.** `pyproject.toml` requires `>=3.11`; CI matrix tests 3.11 + 3.12. Confirm matches your HPC/cluster Python availability.
2. **GitHub repo creation.** Assumed `github.com/emcramer/tmelandscape`. Create the empty repo there so we can push the initial commit.

## Next agent's first actions

1. Read this file + `AGENTS.md`.
2. Confirm with Eric on the four new open questions (Q3–Q6 above).
3. If Q3 (clustering pipeline) confirms Leiden+Ward, write ADRs 0006 (normalization step) and 0007 (two-stage clustering), then revise the development plan and the `cluster/` submodule layout.
4. Initialise git and commit Phase 0 + Phase 1 (reference audit) as the first commits. Tag `v0.0.1`.
5. Once GitHub repo exists (Q2), push.

## Last-session handoff

**Session date:** 2026-05-12  
**Agent:** Claude Code (claude-opus-4-7)

Bootstrap is **complete** and **verified**. All Phase-0 exit criteria met. Phase 1 is unblocked except for Open Q #2 (reference scripts inventory).
