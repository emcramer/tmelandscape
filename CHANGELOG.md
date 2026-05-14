# Changelog

All notable changes to `tmelandscape`. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project follows SemVer pre-1.0 (breaking changes are allowed on minor bumps but called out below).

## [Unreleased] — Phase 5 (clustering)

Pre-drafted task file ready at `tasks/06-clustering-implementation.md`. No code shipped yet.

## [0.5.0] — 2026-05-13 — Phase 4: time-delay embedding

### Added

- `tmelandscape.embedding.sliding_window.window_trajectory_ensemble` — pure function implementing the reference sliding-window algorithm (`reference/utils.py::window_trajectory_data`). Per-simulation sliding window of length `W` with step 1 (default), flattening each window's `(W, n_statistic)` submatrix to a length-`W * n_statistic` row vector. Per-window per-statistic means computed in parallel via `np.nanmean`.
- `tmelandscape.embedding.embed_ensemble` — Zarr orchestrator. Reads input Zarr lazily as a context manager; refuses to overwrite the output path; per-window coords broadcast from per-simulation coords via `np.take(simulation_index)`; cleans up partial output on `to_zarr` failure.
- `tmelandscape.embedding.alternatives.embed_identity` — passthrough baseline / future-strategy anchor.
- `tmelandscape.config.embedding.EmbeddingConfig` — Pydantic config. `window_size` is required (no default). Three pairwise variable-name collision checks via `@model_validator(mode="after")`. `drop_statistics=[]` default per ADR 0009.
- CLI verbs: `tmelandscape embed` and `tmelandscape embed-strategies list`.
- MCP tools: `embed_ensemble` and `list_embed_strategies` (total tool count now 9).
- `docs/concepts/embedding.md` — full concept page.
- 74 unit tests + 5 integration tests; total test count now **247**.

### Reviewer findings applied (buddy-pair team)

- A2 SMELL: A1's docstring perf estimate softened to match empirical ~20 ms/1000 windows on `W=50` × `n_stat=30`.
- B2 SMELL: `_serialise_config` dead `dict(config)` branch replaced with `vars(config)` for `SimpleNamespace` test stubs.
- Three other reviewer SMELLs noted but non-blocking (output chunking heuristic, source-hash chained forwarding, PEP 673 `Self` style).

## [0.4.0] — 2026-05-13 — Phase 3.5: within-timestep normalisation

### Added

- `tmelandscape.normalize.within_timestep.normalize_within_timestep` — pure function implementing the reference algorithm (`reference/00_abm_normalization.py`): per-timestep mean → Yeo-Johnson power transform → z-score → re-add per-step mean. Handles NaN, zero-variance, and MLE-collapse edge cases.
- `tmelandscape.normalize.normalize_ensemble` — Zarr orchestrator. Reads input as context manager; refuses to overwrite output; inherits the input's chunk grid where applicable; partial-output cleanup on failure.
- `tmelandscape.normalize.alternatives.normalize_identity` — passthrough baseline.
- `tmelandscape.config.normalize.NormalizeConfig` — Pydantic config. Validators reject `output_variable == "value"` (would shadow raw) and `fill_nan_with = NaN` (would corrupt JSON round-trip).
- CLI verbs: `tmelandscape normalize` and `tmelandscape normalize-strategies list`.
- MCP tools: `normalize_ensemble` and `list_normalize_strategies`.
- `docs/concepts/normalize.md`.

### Reviewer findings applied

- B-RISK 6: orchestrator-side defence-in-depth guard against `output_variable == "value"` collision.
- C-RISK 10: validator rejects `fill_nan_with = NaN`.
- B-SMELL 8: output Zarr inherits input chunk grid.
- B-RISK 9: input Dataset opened as context manager; partial output removed on `to_zarr` failure.
- A-SMELL: float32 → float64 promotion documented.

## [0.3.0] — 2026-05-13 — Statistics-panel rollback (post-Phase 3 directive)

### Removed (breaking, intentional)

- **Hardcoded default panel** in `SummarizeConfig.statistics`. Field is now required.
- `KNOWN_STATISTICS` frozenset in `tmelandscape.summarize.registry`.
- Custom `_compute_*` dispatch helpers.
- `tmelandscape.normalize.feature_filter.DEFAULT_DROP_COLUMNS`.

### Added

- Dynamic statistics discovery via `spatialtissuepy`'s live `_registry`. Validates user-supplied names at config construction.
- `StatisticSpec` Pydantic model with per-metric `parameters` dict for parameterised metrics.
- `tmelandscape.summarize.list_available_statistics()` + `describe_metric(name)`.
- CLI verbs: `tmelandscape statistics list/describe`.
- MCP tools: `list_available_statistics` and `describe_statistic`.
- ADR 0009: "No hardcoded statistics panel; dynamic discovery."
- ADR 0006 update: never overwrite raw data; no built-in feature drops.

This release implements the project owner's directive that *the user* picks which spatial statistics enter their TME landscape — the package does not bake in the LCSS-paper panel.

## [0.2.0] — 2026-05-13 — Phase 3: spatial-statistic summarisation

### Added

- `tmelandscape.summarize.spatialtissuepy_driver.summarize_simulation` — drives `spatialtissuepy` over one PhysiCell output directory, returns a long-form DataFrame.
- `tmelandscape.summarize.aggregate.build_ensemble_zarr` — aggregates per-simulation DataFrames into a chunked Zarr ensemble (xarray-on-zarr). Dims `(simulation, timepoint, statistic)`; NaN-fill for ragged timepoints; provenance .zattrs.
- Synthetic PhysiCell-shaped fixture in `tests/data/synthetic_physicell/`.
- CLI verb `tmelandscape summarize`; MCP tool `summarize_ensemble`.
- Sweep-scoped IC subdirectories: `generate_sweep` now writes ICs under `<dir>/sweep_<hash>_<timestamp>/`. `SweepManifest.sweep_id` + `ic_root()` helper.
- ADR 0008: dependency pin policy (tag git+URL deps; PyPI before v1.0).

## [0.1.1] — 2026-05-13 — Phase 2 audit fixes

### Fixed

- BUG: `ParameterSpec(scale="log10", low=0)` silently produced NaN in manifests → validator rejects at config time.
- BUG: `lhs_unit_hypercube(n_samples=1)` crashed with cryptic numpy error → falls back to no-criterion when `n_samples < 2`.
- RISK: `datetime.utcnow` deprecated on Python 3.12 → switched `SweepManifest.created_at` default factory to tz-aware `datetime.now(UTC)`.
- RISK: top-level `from tissue_simulator import ...` could break `import tmelandscape` if upstream renames → imports deferred into `generate_initial_conditions`.

### Refactored

- Smoke test uses `importlib.metadata.version("tmelandscape")` instead of a hardcoded version string.
- Stale "Phase 0" comment in MCP server replaced.
- Inline `# type: ignore[import-untyped]` pragmas moved to `[[tool.mypy.overrides]]` in `pyproject.toml`.

## [0.1.0] — 2026-05-13 — Phase 2: parameter sampling

### Added

- `tmelandscape.sampling.generate_sweep` — Python API for Step 1 of the pipeline.
- pyDOE3 LHS + scipy.qmc Sobol/Halton/LHS alternatives.
- `tissue_simulator` wrapper for IC replicate generation (with monkey-patch workaround for upstream's unseeded `default_rng()` calls).
- `SweepConfig` and `SweepManifest` Pydantic models; JSON + Parquet persistence.
- CLI verb `tmelandscape sample`; MCP tool `generate_sweep`.
- `docs/concepts/sampling.md`.
- ADRs 0001-0007 covering package name, env manager, Zarr store, MCP from day one, no-MSM-in-v1, normalize as discrete step, two-stage Leiden + Ward clustering.

## [0.0.1] — 2026-05-12 — Bootstrap

### Added

- `uv`-managed package skeleton with `pyproject.toml` (Python >=3.11).
- BSD-3-Clause license, CITATION.cff, README.
- AGENTS.md and CLAUDE.md (cross-tool agent contract).
- mkdocs-material docs site scaffolding.
- fastmcp MCP server with a `ping` tool.
- CI workflows (lint + type + tests on macOS + Linux × Python 3.11 + 3.12); docs deploy workflow.
- `scripts/fetch_example_data.py` for Zenodo-backed example PhysiCell sims.

[unreleased]: https://github.com/emcramer/tmelandscape/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/emcramer/tmelandscape/releases/tag/v0.5.0
[0.4.0]: https://github.com/emcramer/tmelandscape/releases/tag/v0.4.0
[0.3.0]: https://github.com/emcramer/tmelandscape/releases/tag/v0.3.0
[0.2.0]: https://github.com/emcramer/tmelandscape/releases/tag/v0.2.0
[0.1.1]: https://github.com/emcramer/tmelandscape/releases/tag/v0.1.1
[0.1.0]: https://github.com/emcramer/tmelandscape/releases/tag/v0.1.0
[0.0.1]: https://github.com/emcramer/tmelandscape/releases/tag/v0.0.1
