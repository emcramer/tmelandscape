# ROADMAP — phased milestones

Each phase ends in a tagged release; CI must be green and `STATUS.md` updated.

## Phase 0 — Bootstrap (v0.0.1) — COMPLETE

- [x] uv project + pyproject.toml + repo layout
- [x] LICENSE, CITATION.cff, README.md, .gitignore
- [x] AGENTS.md + CLAUDE.md
- [x] docs/development/{STATUS,ROADMAP}.md
- [x] ADRs 0001–0005 in docs/adr/
- [x] mkdocs scaffolding (mkdocs.yml + docs/index.md + concepts/api/tutorials/mcp pages)
- [x] fastmcp server stub with `ping` tool
- [x] .pre-commit-config.yaml + .github/workflows/{ci,docs}.yml
- [x] scripts/fetch_example_data.py (Zenodo + --from-local)
- [x] Phase-0 smoke tests (4 passing, 1 deselected real-data)
- [x] Verified: `uv sync` + `uv run pytest` + `uv run ruff check` + `uv run ruff format --check` + `uv run mypy src` + `uv run mkdocs build --strict` + `tmelandscape version` + `tmelandscape-mcp` ping all green.

**Exit criterion (met):** clean `uv sync` + `uv run pytest` + `uv run mkdocs build --strict` succeed.

## Phase 1 — Reference audit + example data import (no version bump)

- [ ] Eric provides per-step reference-script pointers (Open Q #2 in STATUS.md)
- [ ] Copy authoritative scripts into gitignored `reference/`
- [ ] ADR documenting reference oracles
- [ ] Upload sim_000, sim_003, sim_014 to Zenodo; record DOI in `scripts/fetch_example_data.py`
- [ ] `uv run python scripts/fetch_example_data.py --from-local …` succeeds locally

## Phase 2 — Step 1 sampling (v0.1.0) — COMPLETE

- [x] Implement `tmelandscape.sampling` (LHS via pyDOE3 + scipy.qmc Sobol/Halton/LHS alternatives + tissue_simulator wrapper + SweepManifest)
- [x] `tmelandscape.config.sweep` (`ParameterSpec`, `SweepConfig` Pydantic models)
- [x] CLI: `tmelandscape sample`
- [x] MCP tool: `tmelandscape.generate_sweep`
- [x] Unit tests (49 unit-level: config, manifest, LHS, alternatives, tissue_init wrapper)
- [x] Integration tests (4 tests: Python API + CLI + MCP + round-trip)
- [x] `docs/concepts/sampling.md` populated (160 lines)
- [x] Three streams delegated to general-purpose agents in parallel; orchestrator integrated and tested

Deferred from this phase (rolled into later phases or follow-ups):

- _Synthetic PhysiCell-shaped fixture_ — moved to Phase 3 (the fixture is needed to test summarisation, not sampling).
- _Numerical agreement vs reference scripts_ — sampling reference is `physim-calibration` (uses scipy.qmc), not the marimo notebooks; default backend is pyDOE3 per user preference, so seed-identity is not expected. Statistical agreement (range, shape, uniformity) is enforced by the unit tests instead.

**Exit criterion met:** end-to-end `tmelandscape sample <cfg.json>` produces a `SweepManifest` consumable by the (future) step-2 runner.

## Phase 3 — Step 3 summarisation (v0.2.0) — COMPLETE

- [x] `tmelandscape.summarize.spatialtissuepy_driver` + Zarr aggregation
- [x] `tmelandscape.summarize.aggregate.build_ensemble_zarr` (xarray-on-zarr, chunked)
- [x] `tmelandscape.summarize.registry` (LCSS-default panel: cell counts, fractions, three centrality metrics, interaction matrix)
- [x] `tmelandscape.config.summarize.SummarizeConfig` (Pydantic; validates against `KNOWN_STATISTICS`)
- [x] Synthetic PhysiCell-shaped fixture in `tests/data/synthetic_physicell/` (3 sims × 3 timepoints × 21 cells, 112 KB)
- [x] CLI: `tmelandscape summarize`
- [x] MCP tool: `tmelandscape.summarize_ensemble`
- [x] Integration test: Python API + CLI + MCP all produce equivalent Zarr stores
- [x] Buddy-pair team: 3 Implementer agents + 3 Reviewer agents, 5 RISKs surfaced and fixed before integration
- [x] Sweep-scoped IC subdirectories added to `generate_sweep` (Phase 2 audit follow-up)
- [x] ADR 0008 (dependency pin policy: tag git+URL deps)

**Verification:** 115 tests passing; ruff + format + mypy strict + mkdocs strict all green.

### v0.3.0 — panel hardcoding rollback (post-v0.2.0, 2026-05-13)

Project owner directive: never hardcode the spatial-statistics panel; never overwrite raw data; never drop features by default. ADR 0009 documents the rationale.

- [x] `SummarizeConfig.statistics` is required (no default panel); validated against `spatialtissuepy`'s live `_registry`.
- [x] `StatisticSpec` carries name + per-metric `parameters` dict for parameterised metrics.
- [x] `registry.compute_panel` replaces the custom `_compute_*` dispatch; uses `spatialtissuepy.summary.StatisticsPanel.compute()` directly.
- [x] Removed `KNOWN_STATISTICS`, `_default_statistics`, the rekey helpers for `cell_proportions`/centrality, and `feature_filter.DEFAULT_DROP_COLUMNS`.
- [x] Interaction-key `|` rewrite stays as a vocabulary-aware post-processing pass (vocabulary discovered from `spatial_data.cell_types_unique`).
- [x] Discovery surfaces: `tmelandscape statistics list/describe` CLI verbs; MCP tools `list_available_statistics` and `describe_statistic`.
- [x] ADR 0009 written; ADR 0006 updated with the "never overwrite, no built-in drop" invariants.
- [x] Tests updated to pass explicit `statistics=[...]`; 107 tests passing.

## Phase 3.5 — Step 3.5 normalization (v0.2.5)

> Added 2026-05-12 after the Phase 1 reference audit. See [ADR 0006](../adr/0006-normalize-as-pipeline-step.md).

- [ ] `tmelandscape.normalize.within_timestep` (per-step mean → power transform → z-score → +mean)
- [ ] `tmelandscape.normalize.feature_filter` (configurable drop of cell-density columns)
- [ ] `tmelandscape.normalize.alternatives` (global / local-time / feature-distribution variants)
- [ ] CLI: `tmelandscape normalize`
- [ ] MCP tool: `tmelandscape.normalize_ensemble`
- [ ] Numerical agreement vs `reference/00_abm_normalization.py` on the synthetic fixture

## Phase 4 — Step 4 embedding (v0.3.0)

- [ ] `tmelandscape.embedding.delay_embed` (Takens)
- [ ] FNN dimension search (cross-check vs nolitsa)
- [ ] Mutual-information lag selection
- [ ] Joint `optimize_embedding`
- [ ] Sliding-window construction (`W=50` default per LCSS paper / reference)
- [ ] Golden-file regression vs reference
- [ ] CLI: `tmelandscape embed`
- [ ] MCP tools: `tmelandscape.optimize_embedding`, `tmelandscape.delay_embed`

## Phase 5 — Step 5 clustering + Landscape facade (v0.4.0)

> Reshaped 2026-05-12 after Phase 1. See [ADR 0007](../adr/0007-two-stage-leiden-ward-clustering.md).

- [ ] `tmelandscape.cluster.leiden` — kNN graph + Leiden community detection (stage 1)
- [ ] `tmelandscape.cluster.meta` — Ward hierarchical clustering on Leiden cluster means (stage 2)
- [ ] `tmelandscape.cluster.selection` — Leiden resolution sweep + Ward elbow / silhouette
- [ ] `tmelandscape.cluster.labels` — state-label persistence + interpretable names (Effector-Dominant, etc.)
- [ ] `Landscape` facade + `.tmelandscape/` bundle format (stores both Leiden labels and Ward final labels)
- [ ] CLI: `tmelandscape fit`
- [ ] MCP tools: `tmelandscape.fit_landscape`, `tmelandscape.describe_landscape`
- [ ] End-to-end integration test on synthetic fixture (Python API + CLI + MCP)
- [ ] Numerical agreement vs `reference/01_abm_generate_embedding.py` clustering output on the synthetic fixture

## Phase 6 — Visualisation (v0.5.0)

- [ ] `tmelandscape.viz.diagnostics` (FNN curve, elbow, MI-vs-lag)
- [ ] `tmelandscape.viz.embedding` (UMAP scatter; vector-field-style)
- [ ] `tmelandscape.viz.trajectories` (state-colored time series, Fig. 2 style)
- [ ] Notebook tutorials in `docs/tutorials/` executed in CI

## Phase 7 — Release hardening (v1.0.0)

- [ ] `pytest -m real` green against the three Zenodo-fetched sim_xxx directories
- [ ] mkdocs published to GitHub Pages
- [ ] PyPI release via trusted publisher
- [ ] Zenodo DOI for the software + updated CITATION.cff

## Beyond v1.0 (deferred — not v1)

- MSM construction + Markov state model fitting
- MDP / intervention-design analysis (LCSS paper, sections IV–VI)
- Landscape projection: mapping new/clinical observations onto a fitted landscape
- SLURM-specific helpers for HPC consumption
