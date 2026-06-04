# Changelog

All notable changes to `tmelandscape`. Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project follows SemVer pre-1.0 (breaking changes are allowed on minor bumps but called out below).

## [0.8.1] — 2026-06-04 — Fix: MCP plot tools on macOS (Agg backend)

### Fixed

- **MCP plot tools no longer crash on macOS.** `tmelandscape-mcp` now
  forces the `Agg` backend before any matplotlib import in
  `tmelandscape.mcp.server`, so the 11 figure-producing tools (`plot_*`)
  succeed when FastMCP dispatches them on worker threads. Previously, the
  default `MacOSX` GUI backend required the main thread and raised
  "Cannot create a GUI FigureManager outside the main thread..." on the
  first `plt.figure()` call. Reproduced 2026-06-04 against v0.8.0 on
  macOS 14.x while running the M00_S01_canary pipeline.

### Unchanged (by design)

- `tmelandscape.viz.*` modules contain no `matplotlib.use(...)` calls.
  Direct Python callers (Jupyter, scripts) keep whatever backend they
  chose. The fix is isolated to the MCP server entry.
- Operator override is honoured: launching with
  `MPLBACKEND=pdf tmelandscape-mcp` writes PDFs instead of PNGs, since
  the server uses `os.environ.setdefault(...)` not a hard assignment.

### Verification snapshot

- `uv run pytest tests/unit tests/integration -q` — 500 passed (was 499;
  the new `test_mcp_server_forces_agg_backend` adds one).
- `uv run ruff check .` / `uv run ruff format --check .` /
  `uv run mypy src` — clean.
- `python -c "from tmelandscape.mcp.server import mcp; import matplotlib;
  print(matplotlib.get_backend())"` — prints `agg`.

### Known follow-ups (not addressed here)

- `plot_state_feature_clustermap` still fails on Leiden cluster-mean
  matrices that contain NaN entries (common when `*_by_type` spatial
  statistics are computed on cell types that start at population 0 and
  arise via transformations — e.g. M00's CD8 / M1 / M2 / exhausted-T).
  Open follow-up: decide whether the figure function skips NaN rows /
  columns automatically, emits a more actionable error, or whether
  `summarize_ensemble` drops all-NaN stats upstream. Flagged by the
  M00_S01_canary report; tracked separately.

## [0.8.0] — 2026-05-28 — Graph-coloring IC generation (breaking)

Step 1 (`generate_sweep`) now produces per-replicate initial-condition CSVs
that match a user-supplied typed source tissue in both per-type proportions
and per-type-pair edge counts. The previous wrapper was a single-type
plumbing stub built on `tissue_simulator.ReplicateGenerator` with a hardcoded
400×400×20 µm tissue and one generic `"cell"` type — it ran no
simulated-annealing type assignment and silently produced uniform-random
output bearing no relation to the model's cell types or spatial structure.
The rewrite uses the correct entry points (`load_tissue_from_csv`,
`SpatialNetworkAnalyzer`, `GraphColorizer.colorize`) and threads scaffold
strategy, SA schedule, and graph mode through `SweepConfig`.

This is a **breaking change** under pre-1.0 SemVer: old `SweepConfig` JSONs
and old `SweepManifest` JSONs do not validate (the new fields are
required). There is no migration shim. See "Migration" below.

### Added

- **`SweepConfig.ic_source`** (required) — discriminated union of
  `IcSourceOwnData` (mode A: user's typed CSV) and `IcSourceStructured`
  (mode B: agent-described tissue realized to a typed CSV upstream).
  Both modes end in a single typed-coordinate CSV; the `mode` field exists
  for manifest provenance. The upstream `/tme-landscape` skill flow is
  responsible for producing the structured CSV.
- **`SweepConfig.ic_scaffold_strategy`** — `"uniform_random"` (default) or
  `"perturb_source"`. The latter copies source positions and jitters by
  `Normal(0, 0.5 * min_radius)`; useful for preserving source morphology.
- **`SweepConfig.ic_sa_params`** (`SAParams` model) — `initial_temp=10.0`,
  `final_temp=0.01`, `cooling_rate=0.9997`, `max_iterations=60_000`.
  Tuned empirically against ~250–2000 node TME graphs.
- **`SweepConfig.ic_network_mode`** (default `"radius"`) and
  **`ic_network_radius_um`** (default `None` ⇒ `2.5 * max(source cell radius)`
  at call time).
- **`SweepRow.ic_scaffold_seed`** — deterministic per-replicate seed
  (spawned from `SweepConfig.seed` via `numpy.random.SeedSequence`).
- **`SweepRow.ic_sha256`** — SHA-256 hex digest of the IC CSV bytes.
  Lets the downstream content-addressing layer in `llm_abm_landscapes`
  verify byte-level reproducibility without a post-hoc walk of the
  manifest's IC directory.
- **`SweepRow.ic_sa_final_cost`** — diagnostic; cost of the SA solution
  on the matched-N scaffold graph.
- **`SweepRow.ic_achieved_proportions`** — per-type proportion realized
  in the generated IC.
- **`IcGenResult`** dataclass — return type of
  `generate_initial_conditions`, carrying the five diagnostics above per
  replicate so the orchestrator does not re-read the CSV.
- **Parquet sidecar columns** — `ic_scaffold_seed: int64`,
  `ic_sha256: string`, `ic_sa_final_cost: float64`, and a JSON-encoded
  `ic_achieved_proportions_json: string` (kept as JSON so the schema stays
  stable across sweeps with different cell-type vocabularies).
- **Static test fixture** `tests/data/ic_source_structured.csv` — a
  30-cell hand-rolled tumor-disc / fibroblast-ring / CD8-annulus tissue
  with CD8↔tumor edges = 0 under the default radius graph; used by every
  `tests/unit/test_sampling_tissue_init.py` test.
- **`tests/integration/conftest.py`** — session-scoped fixture
  `structured_source_csv` that builds a ~30-cell ringed source tissue via
  `tissue_simulator.TissueSection.generate_cells` at a fixed seed.

### Changed

- **`tissue_simulator` dependency** pinned to **v0.1.9** (was v0.1.4).
  v0.1.9 ships explicit `seed=` on `TissueSection` / `SpherePacker` /
  `GraphColorizer`, so the previous
  `tissue_simulator.{packing,tissue}.np.random.default_rng` monkey-patch
  is gone. v0.1.9 also exposes `GraphColorizer`, `SpatialNetworkAnalyzer`,
  and `load_tissue_from_csv` — the symbols this rewrite needs.
- **`generate_initial_conditions` signature** rewritten:
  - **Added** `source_csv`, `scaffold_strategy`, `sa_params`,
    `network_mode`, `network_radius_um`.
  - **Removed** `target_n_cells`, `cell_radii_um`, `tissue_dims_um`,
    `similarity_tolerance` (all physical parameters now come from the
    source CSV per acceptance criterion #4 of the spec).
  - **Return type** changed from `list[Path]` to `list[IcGenResult]`.

### Removed (breaking)

- **`generate_sweep` kwargs** `target_n_cells`, `cell_radii_um`,
  `tissue_dims_um`, `similarity_tolerance` — geometry comes from
  `config.ic_source.source_csv` now.
- **MCP `generate_sweep_tool` kwargs** `target_n_cells`,
  `similarity_tolerance`.
- **CLI `tmelandscape sample` flags** `--target-n-cells` and
  `--similarity-tolerance`. The CLI now exposes only `--manifest-out`
  and `--ic-dir`; all IC knobs live on the JSON config.
- **`_seeded_default_rng_factory`** and the `ExitStack` /
  `patch.object` block in `tissue_init.py` — no longer needed now that
  upstream honours explicit seeds.

### Migration

Adding `ic_source` (required) to every `SweepConfig` JSON is the minimum
to load an existing config under v0.8.0. Both shapes are valid:

```json
{
  "mode": "own_data",
  "source_csv": "/abs/path/to/your_tissue.csv"
}
```

```json
{
  "mode": "structured",
  "source_csv": "/abs/path/to/agent_realised_tissue.csv",
  "description": "tumor disc + fibroblast ring + CD8 annulus"
}
```

Old `SweepManifest` JSONs cannot be loaded; they lack the four new
`SweepRow` fields. Regenerate them by re-running step 1 against the same
config (with `ic_source` added).

### Verification snapshot

- `uv run pytest tests/unit tests/integration -q` — **499 passed**
  (459 unit + 40 integration).
- End-to-end smoke on the static fixture: per-replicate proportions match
  source exactly (10 tumor / 12 fibroblast / 8 CD8 → 10/12/8); per-IC
  CD8↔tumor edges = 0 under `scaffold_strategy="perturb_source"`.
- Same `(config, seed, source_csv)` produces byte-identical CSVs (same
  `ic_sha256`) — verified against v0.1.9 `GraphColorizer.seed=`.

### Acceptance criteria coverage (from spec)

1. Multi-type structured source ⇒ matched proportions and preserved
   CD8↔tumor exclusion: ✅ (`test_proportions_match_source_exactly`,
   `test_cd8_tumor_edge_fraction_preserved_with_perturb_source`).
2. Reproducibility: ✅ (`test_same_seed_yields_identical_csvs`).
3. Manifest carries `ic_sha256` per row: ✅ (parquet test +
   integration test).
4. No hardcoded cell type or default dims: ✅ (geometry from source CSV).
5. MCP `generate_sweep` round-trips new config fields: ✅
   (`test_mcp_tool_matches_python_api`).
6. Existing tests pass with extensions for the new fields: ✅
   (`test_config_sweep.py` round-trip + discriminator dispatch).

### Out of scope (per spec, restated)

- Generation of the structured source CSV upstream (skill flow +
  PhysiCell `place_initial_cells`).
- `/tme-landscape` skill prompts for `ic_source` mode and source path.
- Content-addressing layer (`model_hash` / `sweep_hash` / per-IC
  `sha256` binding) — lives in `llm_abm_landscapes`. This release just
  emits `ic_sha256` per row.

## [0.7.1] — 2026-05-14 — WSS-elbow Option 5 + LCSS-1 schematic generator

Three owner directives received after v0.7.0; all three resolved in
this release. See [v0.7.1 session log](docs/development/decisions/2026-05-14-v0-7-1-session.md).

### Added

- **Three new `cluster_count_metric` options** (WSS-elbow Option 5 per
  [decision log](docs/development/decisions/2026-05-14-wss-elbow-option-5-accepted.md)):
  - `wss_lmethod` — Salvador & Chan 2004 L-method (two-linear-fit knee detection).
  - `wss_asymptote_fit` — exponential decay fit; pick smallest k whose remaining distance to the fitted asymptote ≤ 0.1 (90%-of-reduction).
  - `wss_variance_explained` — smallest k whose `1 − WSS(k)/WSS(k_min)` reaches 0.85.
  - Existing `wss_elbow` / `calinski_harabasz` / `silhouette` are unchanged. `ClusterConfig.cluster_count_metric` Literal grows from 3 → 6 options. The four `wss_*` metrics share the WSS computation; only the chosen-k extraction differs.
- **`tmelandscape.viz.model_schematic`** — new module shipping a programmatic ABM schematic generator (`plot_model_schematic`). Renders coloured-circle nodes (cell types) with text labels and typed arrows (`promotes` / `inhibits` / `transitions_to` / `secretes`) from a user-supplied model description. **Generic across any ABM**, not just the LCSS paper's TME model — see [decision log](docs/development/decisions/2026-05-14-lcss-1-schematic-in-scope.md). Output supports PNG (raster) and SVG (vector) via matplotlib's extension dispatch. Reproduces LCSS Figure 1 conceptually (the original "ships as a static SVG asset" plan is retired).
- **`CellType` + `Interaction` dataclasses** (both `frozen=True`) in `viz.model_schematic`.
- **MCP tool `plot_model_schematic_tool`** registered on the server. **Total MCP tool count: 22 → 23.** `list_viz_figures` catalogue extended with the LCSS-1 entry.
- **2 new integration tests** for schematic Python-API ↔ MCP equivalence (PNG byte-equality + SVG round-trip).
- **28 new unit tests** total (9 across the three new WSS metrics + 19 for the schematic generator).
- **Four new decision-log entries**: WSS-elbow Option 5 accepted, LCSS-1 in scope, no PyPI ever, v0.7.1 session log.

### Changed

- **`SelectionResult.metric` docstring** updated to list all six metric values (was: three).
- **`tests/unit/test_cluster_config.py` `cluster_count_metric` parametrize** extended from 3 → 6 options (renamed `test_all_three_options_accepted` → `test_all_six_options_accepted`).
- **`networkx.*` added to `pyproject.toml [[tool.mypy.overrides]]`**; per-import `# type: ignore[import-untyped]` stripped from `viz/model_schematic.py` (same centralisation pattern as seaborn in v0.7.0).
- **ADR 0010 amended** to enumerate all six metrics and reference the Option-5 decision log.
- **ROADMAP Phase 7** simplified — PyPI publishing line removed; Zenodo deposit framed as owner-discretion rather than a phase-completion gate. See [decision log](docs/development/decisions/2026-05-14-no-pypi-ever.md).
- **`docs/concepts/cluster.md`** and **`docs/concepts/viz.md`** updated to reflect both new feature sets.
- **`tasks/07-visualisation-implementation.md`** marks LCSS-1 as in-scope; the figure catalogue table gains an LCSS-1 row.

### Reviewer findings applied (buddy-pair team)

- A2 SMELL: `SelectionResult.metric` docstring (cosmetic — listed only 3 metrics post-Option-5).
- A2 SMELL: extend `test_cluster_config.py`'s `cluster_count_metric` parametrize to all six options.
- A2 R2: inline comment in `_asymptote_fit_knee` documenting the `denom = max(..., 1e-12)` degenerate-fit behaviour.
- B2 SMELL: centralised `networkx.*` in mypy overrides; stripped the inline ignore.

### Deferred to v0.7.x (none blocking)

- Reciprocal-edge curvature in `plot_model_schematic` (overlapping arrows when A↔B both have edges).
- Self-loop endcap geometry polish.
- `arrow_style` public type widening (`dict[str, dict[str, str]]` → `dict[str, dict[str, Any]]`).
- `_data_radius_to_points` snapshot-at-call-time concern.
- Theoretical non-monotone-WSS risk on the `wss_asymptote_fit` and `wss_variance_explained` argmax (real Ward-WSS curves are monotone).

### Verification snapshot

- `uv run pytest -q` — 487 passed, 1 deselected.
- `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` — clean.
- `uv run mkdocs build --strict` — exit 0.
- `tmelandscape version` — prints `0.7.1`.
- `tmelandscape-mcp` — boots; **23 tools registered**.

## [0.7.0] — 2026-05-14 — Phase 6: visualisation (LCSS + TNBC manuscript figures)

### Added

- **`tmelandscape.viz.embedding`** — UMAP-projection family. `fit_umap` (caches a 2D projection of the cluster-Zarr embedding) + five plot functions reproducing **LCSS Figures 3 and 4** and **TNBC Figures 2b, 2c, 2d, 2e**: `plot_state_umap`, `plot_time_umap`, `plot_feature_umap`, `plot_trajectory_umap`, `plot_state_umap_with_vector_field`. First positional kwarg renamed `umap_result` (avoids shadowing `import umap`; see [decision log](docs/development/decisions/2026-05-14-viz-umap-result-param-rename.md)).
- **`tmelandscape.viz.trajectories`** — heatmap family. `plot_state_feature_clustermap` (TNBC-2a) and `plot_trajectory_clustergram` (TNBC-6a). Ragged trajectories raise rather than NaN-pad; `leiden_labels` is optional with graceful row-colour-bar degradation. See [decision log](docs/development/decisions/2026-05-14-viz-trajectories-deviations.md).
- **`tmelandscape.viz.dynamics`** — phase-space and parameter-state plots. `plot_phase_space_vector_field` (TNBC-6b), `plot_parameter_by_state` (TNBC-6c), `plot_attractor_basins` (LCSS-6). BH-FDR hand-rolled to avoid adding `statsmodels` (see [decision log](docs/development/decisions/2026-05-14-bh-fdr-hand-rolled.md)). Parameter / feature names are user-supplied per ADR 0009 — no hardcoded `(rexh, radh)` or `(epithelial, T_eff)` defaults.
- **`tmelandscape.landscape.join_manifest_cluster`** — Phase-2-manifest ↔ Phase-5-cluster-Zarr join. Returns a DataFrame indexed by `simulation_id` with one column per parameter plus `terminal_cluster_label` (mode of last `terminal_window_count` windows; default 5) and `n_windows`. See [decision log](docs/development/decisions/2026-05-14-terminal-cluster-label-mode.md).
- **MCP tools** — **10 figure tools** (one per figure function) plus `list_viz_figures` discovery. **Total MCP tool count now 22** (was 11). Each figure tool requires `save_path` (MCP can't return Figure objects) and returns the resolved PNG path plus a small summary.
- **CLI** — `tmelandscape viz-figures list` discovery verb. Per-figure CLI verbs intentionally **not** shipped (eleven verbs in one namespace would overwhelm `--help`; agents use MCP, humans use the Python API).
- **`docs/concepts/viz.md`** — full concept page with figure catalogue, module layout, worked example, and MCP-usage section.
- **`seaborn>=0.13`** added to the `viz` extra (used by clustermap, kdeplot, violinplot).
- **65 new unit tests** (25 UMAP family + 15 heatmaps + 8 landscape join + 17 dynamics) + **12 new integration tests** (Python-API ↔ MCP equivalence on every figure + discovery surface). Total test count now **454**.
- **Five Phase-6 decision-log entries** plus a comprehensive Phase 6 session log. See `docs/development/decisions/`.

### Changed

- **`seaborn.*` added to `[[tool.mypy.overrides]]`** in `pyproject.toml`. Per-import `# type: ignore[import-untyped]` on `import seaborn as sns` in all three viz modules removed. See [decision log](docs/development/decisions/2026-05-14-seaborn-mypy-override.md).
- **`tasks/07-visualisation-implementation.md` frozen API updated** to reflect the `umap_result: UMAPResult` parameter rename.

### Reviewer findings applied (buddy-pair team)

- A2 R3: 7 mypy errors in `test_viz_embedding.py:392` — fixed via `np.asarray(c.get_offsets())`.
- A2 R1: contour test now asserts `LineCollection` artists appear when `show_density_contours=True`.
- A2 R2: vector-field smoke test now asserts at least one quiver `PolyCollection`.
- C2 R5: mismatched-sim-set error-test now asserts both offending sim ids appear in the message.
- A2 / B2 / C2 cross-stream SMELL: `seaborn.*` centralised in mypy overrides.

### Deferred to v0.7.x (none blocking)

- Float-equality fragility on `Axes.get_xlim()` — switch to `assert_allclose`.
- `warnings.warn` on `leiden_labels` graceful degradation and on `KNeighborsClassifier` silent neighbor clamp.
- Quiver false-positive-bin assertion strengthening.
- Entry-point cross-marker explicit test.
- LCSS Figure 1 SVG asset (pending hand-off from Eric).

### Verification snapshot

- `uv run pytest -q` — 454 passed, 1 deselected.
- `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` — clean.
- `uv run mkdocs build --strict` — exit 0.
- `tmelandscape version` — prints `0.7.0`.
- `tmelandscape-mcp` — boots; **22 tools registered**.

## [0.6.1] — 2026-05-14 — housekeeping: cluster-count cap, k≥4 regression test, decision-log system

### Changed

- **`cluster_count_max` default narrowed** from `min(20, n_leiden_clusters)` to `min(12, n_leiden_clusters)` in `tmelandscape.cluster.selection.select_n_clusters`. The cap of 12 reflects the biologically interpretable upper bound for TME states (Eric: "anything past 8-10 clusters becomes biologically less interpretable"). Callers who need a wider range can still pass `cluster_count_max=N` explicitly. See [decision log](docs/development/decisions/2026-05-14-cluster-count-max-default.md).
- **ADR 0008 revised** — removed the "PyPI before v1.0" target language per owner directive. `tissue_simulator` and `spatialtissuepy` will remain git+tag pinned indefinitely. See [decision log](docs/development/decisions/2026-05-14-no-pypi-plan.md).

### Added

- **Decision-log system** under `docs/development/decisions/` — per-decision and per-session entries with a chronological index. Excluded from the published docs site (it's an internal artefact). Process: write one entry per non-obvious choice and one session log per working session. See `docs/development/decisions/README.md` for the rules. Initial entries cover the four v0.6.1 housekeeping decisions plus a session log for the Phase 5 v0.6.0 ship.
- **k≥4 anchor regression test** in `tests/unit/test_cluster_selection.py` — exercises a 5-blob fixture where the true WSS elbow is at k=5. Verifies the private k=1 anchor used to expose convex shape to kneed doesn't bias the chosen k toward small values. Both `wss_elbow` and `calinski_harabasz` land in `[4, 6]` on this fixture.
- **Decision-log entry** [`2026-05-14-wss-elbow-algorithm-options.md`](docs/development/decisions/2026-05-14-wss-elbow-algorithm-options.md) — surveys six options for replacing the marginal-decrease fallback (kneed-only, L-method, exponential-asymptote fit, etc.) with a recommendation. Status: Proposed; awaiting owner pick.

### Verification snapshot

- `uv run pytest -q` — 377 passed (375 v0.6.0 + 2 new regression tests), 1 deselected, 1 warning.
- `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` — clean.
- `uv run mkdocs build --strict` — exit 0.
- `tmelandscape version` — prints `0.6.1`.

## [0.6.0] — 2026-05-14 — Phase 5: two-stage Leiden + Ward clustering

### Added

- `tmelandscape.cluster.leiden_ward.cluster_leiden_ward` — pure function implementing the reference two-stage clustering algorithm (`reference/01_abm_generate_embedding.py` lines ~519-720). Stage 1 builds a kNN graph (sklearn) over the embedding and runs Leiden community detection (leidenalg). Stage 2 computes per-Leiden-community mean embedding vectors and runs Ward hierarchical clustering on those means; the dendrogram is cut at `n_final_clusters` to produce the final TME-state labels.
- `tmelandscape.cluster.selection.select_n_clusters` — cluster-count auto-selection over a candidate range. Supports `wss_elbow` (default; kneed-based knee of the within-cluster sum of squares), `calinski_harabasz`, and `silhouette` metrics. Returns the chosen k plus the per-candidate scores for provenance.
- `tmelandscape.cluster.cluster_ensemble` — Zarr orchestrator. Reads input lazily as a context manager; refuses to overwrite the output path; six-way variable-name collision defence; 2D source-array guard; partial-output cleanup on `to_zarr` failure; cleans up after itself; lifts a bare `embedding_config` input attr into the `source_embedding_config` output slot so fresh Phase 4 stores get a clean audit chain. Emits `cluster_ensemble.start` / `.done` structlog events on stderr.
- `tmelandscape.cluster.alternatives.cluster_identity` — passthrough baseline (single-cluster labels) / future-strategy anchor.
- `tmelandscape.config.cluster.ClusterConfig` — Pydantic config. `n_final_clusters` is `int | None` with **no package default** — when `None`, the package picks k via `cluster_count_metric` over the candidate range (default `wss_elbow`). See [ADR 0010](docs/adr/0010-cluster-count-auto-selection.md). Two `@model_validator(mode="after")` checks (six-way variable-name collision; cluster-count range consistency).
- CLI verbs: `tmelandscape cluster` (with `--config` for the `ClusterConfig` JSON) and `tmelandscape cluster-strategies list`.
- MCP tools: `cluster_ensemble` and `list_cluster_strategies` (total tool count now **11**).
- [ADR 0010](docs/adr/0010-cluster-count-auto-selection.md) — cluster-count auto-selection policy. `n_final_clusters` is `int | None` with no silent default; auto-selection uses a tunable metric, defaulting to WSS elbow.
- `docs/concepts/cluster.md` — full concept page describing the two-stage algorithm, the auto-selection layer, and the output Zarr schema.
- 121 new unit tests (algorithm 17, selection 9, orchestrator 18, config 71, alternatives 6) + 7 integration tests covering Python API / CLI / MCP equivalence on both explicit-k and auto-select paths. Total test count now **375**.
- Structlog wired into CLI startup via `configure_logging()` so JSON CLI summaries stay on stdout while structured logs flow to stderr.

### Changed

- `tissue_simulator` dependency pin bumped from floating-`main` (v0.1.0 commit) to tagged `v0.1.4` per ADR 0008.
- `spatialtissuepy` dependency pin moved from commit-SHA form (`@c03cfa4`) to tag form (`@v0.0.1`) — same commit, cosmetic improvement per ADR 0008.
- Centralised `[[tool.mypy.overrides]]` for stub-less third-party deps (scipy, sklearn, kneed, igraph, leidenalg) in `pyproject.toml`, eliminating per-import `# type: ignore[import-untyped]` noise in library code.

### Reviewer findings applied (buddy-pair team)

- A2 SMELL: 7 per-import `# type: ignore[import-untyped]` collapsed into `[[tool.mypy.overrides]]` so future stub releases don't break under `warn_unused_ignores=true`.
- B2 RISK: orchestrator now asserts `linkage_matrix.shape[1] == 4` after the algorithm call (defence-in-depth on the scipy linkage contract).
- B2 SMELL: orchestrator docstring documents the float64 upcast on the `embedding` passthrough and clarifies that `leiden_to_final` is intentionally not surfaced in the output Zarr (the mapping is collapsed into per-window `final_labels`).
- B2 SMELL: `test_source_variable_missing_raises` regex tightened to `r"available variables: \[.+\]"` so it actually pins the non-empty-listing requirement.
- Several other reviewer RISKs/SMELLs noted but deferred to follow-up: marginal-decrease fallback semantics (currently dominated by the WSS k=1 anchor), tightening the auto-selection range assertion from `[2,4]` to `==2`, and optionally adding a regression fixture for elbows at k≥4.

### Verification snapshot

- `uv run pytest -q` — 375 passed, 1 deselected, 1 warning.
- `uv run ruff check .` / `uv run ruff format --check .` / `uv run mypy src` — clean.
- `uv run mkdocs build --strict` — exit 0.
- `tmelandscape version` — prints `0.6.0`.
- `tmelandscape-mcp` — boots; 11 tools registered.

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

[0.7.1]: https://github.com/emcramer/tmelandscape/releases/tag/v0.7.1
[0.7.0]: https://github.com/emcramer/tmelandscape/releases/tag/v0.7.0
[0.6.1]: https://github.com/emcramer/tmelandscape/releases/tag/v0.6.1
[0.6.0]: https://github.com/emcramer/tmelandscape/releases/tag/v0.6.0
[0.5.0]: https://github.com/emcramer/tmelandscape/releases/tag/v0.5.0
[0.4.0]: https://github.com/emcramer/tmelandscape/releases/tag/v0.4.0
[0.3.0]: https://github.com/emcramer/tmelandscape/releases/tag/v0.3.0
[0.2.0]: https://github.com/emcramer/tmelandscape/releases/tag/v0.2.0
[0.1.1]: https://github.com/emcramer/tmelandscape/releases/tag/v0.1.1
[0.1.0]: https://github.com/emcramer/tmelandscape/releases/tag/v0.1.0
[0.0.1]: https://github.com/emcramer/tmelandscape/releases/tag/v0.0.1
