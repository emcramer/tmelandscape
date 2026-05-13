# STATUS — current session resume doc

> Updated at the **end** of every agent session. New agents read this **first**.

## Current focus

**Phase 2 — Step 1 sampling: complete (v0.1.0).** `tmelandscape.sampling` is implemented end-to-end (samplers, scaling, tissue_simulator wrapper, manifest persistence), exposed through Python API, CLI verb, and MCP tool. 53 tests passing (49 unit + 4 integration); docs and roadmap updated. Ready to proceed to **Phase 3 (Step 3 summarisation via `spatialtissuepy`)**.

## In-flight tasks

_None._ (`tasks/02-sampling-implementation.md` closed 2026-05-13.)

## Recently completed (Phase 2, 2026-05-13)

- Reconnoitred `physim-calibration` (working sampling oracle) and `tissue_simulator` (initial-condition replicates); confirmed `00/01/02_abm_*` scripts are not the sampling oracle, that lives in `/tmp/physim-calibration/code/sampling.py`.
- Added `tissue_simulator @ git+...` to core deps with `[tool.hatch.metadata] allow-direct-references = true`.
- Drafted `tasks/02-sampling-implementation.md` with frozen Pydantic schemas and signatures for the three streams.
- **Delegated three parallel implementation streams** to general-purpose agents:
  - **Stream A** (config + manifest): `src/tmelandscape/config/sweep.py`, `src/tmelandscape/sampling/manifest.py`, 20 unit tests.
  - **Stream B** (samplers): `src/tmelandscape/sampling/lhs.py` (pyDOE3, maximin criterion), `src/tmelandscape/sampling/alternatives.py` (scipy.qmc LHS/Sobol/Halton), 22 unit tests.
  - **Stream C** (tissue_simulator wrapper): `src/tmelandscape/sampling/tissue_init.py` — wraps `ReplicateGenerator`, monkey-patches `np.random.default_rng()` in upstream packing + tissue modules to honour the AGENTS.md seed-discipline invariant.
- **Integrated** (orchestrator):
  - `src/tmelandscape/sampling/__init__.py` — `draw_unit_hypercube` dispatcher + top-level `generate_sweep()`.
  - `src/tmelandscape/cli/sample.py` + wired into `cli/main.py` (`tmelandscape sample <cfg.json>`).
  - `src/tmelandscape/mcp/tools.py` (`generate_sweep_tool`) registered on the MCP server.
  - `tests/integration/test_sample_end_to_end.py` — 4 tests covering Python API, CLI, MCP, and save/load round-trip.
  - Delegated `docs/concepts/sampling.md` fill-out (160 lines).
- Routed tissue_simulator's chatty stdout to stderr inside `generate_initial_conditions` so the CLI's JSON output is parseable.
- Bumped version to `0.1.0` in `pyproject.toml`, `__init__.py`, `CITATION.cff`.

**Phase 2 verification (all green):**

- `uv run pytest -q` — 53 passed, 1 deselected.
- `uv run ruff check .` + `uv run ruff format --check .` — clean.
- `uv run mypy src` — clean (30 source files, strict mode).
- `uv run mkdocs build --strict` — exit 0.
- `tmelandscape sample <cfg.json>` — works end-to-end against a real `SweepConfig`.
- `tmelandscape-mcp` boots; `generate_sweep` tool callable via MCP.

## Blockers

_None._

## Open questions (for Eric)

All Phase 1 and Phase 2 questions are resolved. New ones for Phase 3:

1. **`spatialtissuepy` install method.** PyPI release, git+URL, or already core dep? Mirror the `tissue_simulator` pattern (git+URL + `allow-direct-references`)?
2. **PhysiCell-output adapter.** What's the directory layout `spatialtissuepy` expects per simulation? Single `output/` dir per sim, with the standard `output%08d.xml` + `cells_%08d.mat` files? Or is there a pre-processing step?
3. **Synthetic fixture sizing.** For `tests/data/synthetic_physicell/`, what's the minimum shape `spatialtissuepy` will accept? (e.g., 3 timepoints × 20 cells × 3 cell types). Phase 3 needs a CI-fast fixture.
4. **Spatial statistics selection.** Which subset of `spatialtissuepy`'s output should `tmelandscape.summarize` materialise into the ensemble Zarr by default? (cell-type composition, graph centrality, interaction frequency are mentioned in the LCSS paper; should we expose a configurable selector or hard-code the LCSS set?)

## Quirks worth knowing (for the next agent)

- **tissue_simulator monkey-patch.** `tmelandscape.sampling.tissue_init` patches `tissue_simulator.{packing,tissue}.np.random.default_rng` for the duration of `generate_initial_conditions` calls because upstream instantiates `default_rng()` with no argument. Scoped via `ExitStack`, doesn't leak. Worth filing an upstream issue eventually.
- **tissue_simulator stdout.** Upstream prints progress to stdout; we redirect to stderr in our wrapper so structured stdout (CLI JSON, MCP tool returns) stays clean.
- **`TargetStatistics.target_density`.** Upstream rejects density > 1; our wrapper clears the field after bootstrapping because the upstream estimator counts boundary cells as fully inside the tissue.
- **pyDOE3 vs scipy.qmc.** Default sampler is `pyDOE3` (per user preference) with `criterion="maximin"`. The working physim-calibration oracle uses `scipy.stats.qmc.LatinHypercube(optimization='random-cd')` — exposed as `sampler="scipy-lhs"` for users who want byte-for-byte reproducibility against that oracle.

## Next agent's first actions

1. Read this file + `AGENTS.md`.
2. Confirm Open Questions 1–4 above with Eric.
3. Open `tasks/03-summarize-implementation.md` and design Phase 3 (Step 3 summarisation). Key decisions:
   - `spatialtissuepy` integration (similar pattern to `tissue_init.py`?)
   - Ensemble Zarr schema (dims, coords, chunking)
   - Synthetic PhysiCell-shaped fixture for fast CI
4. Consider delegating Phase 3 streams analogously to Phase 2 (recon → frozen contract → parallel implementation streams → integration).
5. Push commits + tag at end of Phase 3 (target: `v0.2.0`).

## Last-session handoff

**Session date:** 2026-05-13  
**Agent:** Claude Code (claude-opus-4-7) orchestrator + 3 delegated general-purpose agents + 1 docs agent

Phase 2 **complete** and **verified**. Repo is ready to tag `v0.1.0` and push. Phase 3 is unblocked except for Open Questions 1–4 (spatialtissuepy install + fixture sizing).
