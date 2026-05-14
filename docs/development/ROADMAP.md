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

## Phase 3.5 — Step 3.5 normalization (v0.4.0) — COMPLETE

Shipped 2026-05-13 with the buddy-pair team pattern (3 Implementer + 3 Reviewer agents). See [ADR 0006](../adr/0006-normalize-as-pipeline-step.md) and [ADR 0009](../adr/0009-no-hardcoded-statistics-panel.md) for binding invariants.

- [x] `tmelandscape.normalize.within_timestep` — reference algorithm (per-step mean → Yeo-Johnson → z-score → re-add mean).
- [x] `tmelandscape.normalize.alternatives` — `normalize_identity` passthrough as baseline / future-strategy anchor.
- [x] `tmelandscape.normalize.normalize_ensemble` — Zarr orchestrator. Reads input lazily, writes a NEW Zarr containing both raw `value` and the new `value_normalized` arrays. Refuses to overwrite existing outputs.
- [x] `tmelandscape.config.normalize.NormalizeConfig` (Pydantic): strategy literal, `preserve_time_effect`, `drop_columns=[]` default, `output_variable` validates `!= "value"`, `fill_nan_with` rejects NaN to keep JSON round-trip lossless.
- [x] CLI: `tmelandscape normalize` + `tmelandscape normalize-strategies list`.
- [x] MCP tools: `normalize_ensemble` + `list_normalize_strategies`.
- [x] Reviewer-surfaced fixes baked in:
  - **B-RISK 6**: orchestrator-side guard against `output_variable == "value"` collision.
  - **C-RISK 10**: validator rejects `fill_nan_with = NaN`.
  - **B-SMELL 8**: output Zarr inherits the input's chunk grid.
  - **B-RISK 9**: input `Dataset` opened as context manager; partial output cleaned on `to_zarr` failure.
  - **A-SMELL**: float32 → float64 promotion documented in the algorithm's docstring.
- [x] 168 tests passing (existing 158 + 5 new normalize unit tests in driver, 11 in orchestrator, 23 in config + alternatives, 5 integration = +27 new tests). ruff + format + mypy strict + mkdocs strict all clean.

## Phase 4 — Step 4 embedding (v0.5.0) — COMPLETE

Shipped 2026-05-13 via the buddy-pair team (3 Implementer + 3 Reviewer agents). Reference oracle: `reference/utils.py::window_trajectory_data`.

- [x] `tmelandscape.embedding.sliding_window.window_trajectory_ensemble` — pure function, reference-faithful (row-major flatten, step-1 default, `np.nanmean` for averages).
- [x] `tmelandscape.embedding.alternatives.embed_identity` — passthrough baseline / future-strategy anchor.
- [x] `tmelandscape.embedding.embed_ensemble` — Zarr orchestrator. Reads input lazily, writes a NEW Zarr containing the flattened embedding plus per-window metadata. Per-window coords broadcast from per-sim coords via `np.take(simulation_index)`. Refuses to overwrite; cleans up partial output on failure.
- [x] `tmelandscape.config.embedding.EmbeddingConfig` (Pydantic): `window_size` required (no default), three pairwise variable-name collision checks via `@model_validator(mode="after")`, `drop_statistics=[]` default.
- [x] CLI: `tmelandscape embed` + `tmelandscape embed-strategies list`.
- [x] MCP tools: `embed_ensemble`, `list_embed_strategies`.
- [x] Reviewer findings applied:
  - **A2 SMELL**: A1's docstring perf claim softened to match empirical ~20 ms/1000 windows.
  - **B2 SMELL**: `_serialise_config` dead `dict(config)` branch replaced with `vars(config)` for SimpleNamespace stubs.
  - Three other reviewer SMELLs noted but non-blocking (chunking heuristic, source-hash forwarding, PEP 673 `Self` style).
- [x] 247 tests passing (existing 168 + 17 A + 19 B + 38 C + 5 integration = +79 new tests across Phase 4). ruff + format + mypy strict + mkdocs strict all clean.

Deferred (in line with project-owner "don't add features beyond what's required"):

- FNN / MI optimisation: the reference doesn't use them; user can request as v0.5.x.
- Takens lag-coordinate delay embedding: the reference uses sliding window (same purpose, different math); user can request as v0.5.x.

## Phase 5 — Step 5 clustering (target v0.6.0) — NEXT

> See [ADR 0007](../adr/0007-two-stage-leiden-ward-clustering.md) and the pre-drafted `tasks/06-clustering-implementation.md` (in the repo root) for the frozen API contracts and buddy-pair stream allocation.

Reference oracle: `reference/01_abm_generate_embedding.py` lines ~519-720.

- [ ] `tmelandscape.cluster.leiden_ward.cluster_leiden_ward` — pure two-stage algorithm: kNN graph → Leiden (default partition `CPMVertexPartition`, matching the reference) → Ward on Leiden cluster means → `fcluster(maxclust)` to cut the dendrogram.
- [ ] `tmelandscape.cluster.alternatives.cluster_identity` — passthrough baseline.
- [ ] `tmelandscape.cluster.cluster_ensemble` — Zarr orchestrator. Reads input lazily; refuses to overwrite output; passes through `embedding` and `window_averages`; adds `leiden_labels`, `cluster_labels` (final), `leiden_cluster_means`, `linkage_matrix`.
- [ ] `tmelandscape.config.cluster.ClusterConfig` — Pydantic. `n_final_clusters` required (no default per ADR 0009). Five-way variable-name collision validator.
- [ ] CLI: `tmelandscape cluster` + `tmelandscape cluster-strategies list`.
- [ ] MCP tools: `cluster_ensemble`, `list_cluster_strategies`.
- [ ] Integration test: Python API + CLI + MCP byte-equal equivalence on a synthetic embedding Zarr.
- [ ] `docs/concepts/cluster.md` filled in (currently a placeholder).
- [ ] Bump to `v0.6.0` once all checks green.

Deferred (out of scope for v0.6.0 unless the owner says otherwise):

- Leiden resolution sweep / silhouette-based selection helpers.
- The `Landscape` facade and `.tmelandscape/` bundle format (revisit when projection is on the table — see [ADR 0005](../adr/0005-no-msm-in-v1.md)).
- Interpretable state names ("Effector-Dominant" etc.) — purely a downstream labelling concern.

## Phase 6 — Visualisation (target v0.7.0)

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
