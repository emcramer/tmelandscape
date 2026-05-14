# STATUS — current session resume doc

> Updated at the **end** of every agent session. New agents read this **first**, then [HANDOFF.md](HANDOFF.md) for the cold-start guide.

## Where the project is (2026-05-14)

**v0.7.1 shipped** (small feature ship on top of v0.7.0). Pipeline steps 1, 3, 3.5, 4, 5, **and 6** are implemented end-to-end. Step 2 (running PhysiCell simulations) is intentionally out of scope. **v1 scope per [ADR 0005](../adr/0005-no-msm-in-v1.md) is functionally complete.** Remaining work: v0.7.x reviewer follow-ups (none blocking) and v1.0 release hardening (Phase 7: real-data CI gate, GitHub Pages docs, CITATION.cff currency — **no PyPI** per owner directive; Zenodo deposit is owner-discretion). A **decision-log system** lives under `docs/development/decisions/` — read its `README.md` before writing new code so you can capture decisions in line with the established process.

**What's new in v0.7.1** (over v0.7.0):

- Three new `cluster_count_metric` options (`wss_lmethod`, `wss_asymptote_fit`, `wss_variance_explained`) — Option 5 from the WSS-elbow algorithm decision log; user picks among **six** WSS-curve interpretation strategies.
- `viz.model_schematic.plot_model_schematic` — programmatic ABM schematic generator (LCSS-1). Generic across any model: takes cell-type list + interaction rules, renders coloured-node / typed-arrow figure in PNG or SVG.
- MCP tool count: 22 → **23**. CLI verbs unchanged. ROADMAP Phase 7 simplified (PyPI line removed).

| Phase | Step | Version | Status | Reference oracle |
| --- | --- | --- | --- | --- |
| 0 | Bootstrap | v0.0.1 | shipped | — |
| 1 | Reference audit | (no bump) | shipped | the `reference/` directory |
| 2 | Sampling | v0.1.0 → v0.1.1 (fixes) | shipped | `/tmp/physim-calibration/code/sampling.py` |
| 3 | Summarisation | v0.2.0 → v0.3.0 (panel rollback) | shipped | `spatialtissuepy` registry |
| 3.5 | Normalisation | v0.4.0 | shipped | `reference/00_abm_normalization.py` |
| 4 | Embedding | v0.5.0 | shipped | `reference/utils.py::window_trajectory_data` |
| 5 | Clustering | v0.6.0 → v0.6.1 (housekeeping) | shipped | `reference/01_abm_generate_embedding.py` lines ~519-720 |
| 6 | Visualisation | v0.7.0 → v0.7.1 (Option 5 + LCSS-1 schematic) | **just shipped** | `reference/01_abm_generate_embedding.py` + `reference/02_abm_state_space_analysis.marimo.py` + manuscript Methods for LCSS-6 / TNBC-6b / TNBC-6c; LCSS-1 has no reference (generic generator) |
| 7 | v1.0 release hardening | (target v1.0.0) | **NEXT** | — |

## Verification snapshot (v0.7.1)

- `uv run pytest -q` — **487 passed, 1 deselected**, warnings only (upstream `spatialtissuepy` deprecation + UMAP `n_jobs` informational + matplotlib `figure.max_open_warning` — all harmless).
- `uv run ruff check .` — clean.
- `uv run ruff format --check .` — clean.
- `uv run mypy src` — clean (52 source files, strict mode).
- `uv run mkdocs build --strict` — exit 0.
- `tmelandscape version` — prints `0.7.1`.
- `tmelandscape-mcp` — boots; **23 tools registered**.

## MCP tools (23)

| Tool | Phase | What it does |
| --- | --- | --- |
| `ping` | 0 | Health check |
| `generate_sweep` | 2 | Latin Hypercube parameter sweep + tissue_simulator IC replicates |
| `summarize_ensemble` | 3 | spatialtissuepy panel over a PhysiCell output directory tree |
| `list_available_statistics` | 3 | Catalogue of spatialtissuepy metrics |
| `describe_statistic` | 3 | Full description of one metric |
| `normalize_ensemble` | 3.5 | Within-time-step normalisation on a Zarr ensemble |
| `list_normalize_strategies` | 3.5 | Catalogue of normalisation strategies |
| `embed_ensemble` | 4 | Sliding-window embedding of a Zarr ensemble |
| `list_embed_strategies` | 4 | Catalogue of embedding strategies |
| `cluster_ensemble` | 5 | Two-stage Leiden + Ward clustering of an embedding Zarr |
| `list_cluster_strategies` | 5 | Catalogue of clustering strategies |
| `plot_state_umap` | 6 | TNBC-2b — state-coloured UMAP scatter |
| `plot_time_umap` | 6 | TNBC-2c — UMAP coloured by per-window mean time |
| `plot_feature_umap` | 6 | LCSS-4 / TNBC-2e — multi-panel UMAP by features |
| `plot_trajectory_umap` | 6 | TNBC-2d — UMAP with named sim trajectories overlaid |
| `plot_state_umap_with_vector_field` | 6 | LCSS-3 — UMAP + per-state vector field + density contours |
| `plot_state_feature_clustermap` | 6 | TNBC-2a — Leiden-means × features clustermap |
| `plot_trajectory_clustergram` | 6 | TNBC-6a — (sim × window) state heatmap |
| `plot_phase_space_vector_field` | 6 | TNBC-6b — per-state vector field in 2D feature phase space |
| `plot_parameter_by_state` | 6 | TNBC-6c — violin of a sweep parameter by terminal state |
| `plot_attractor_basins` | 6 | LCSS-6 — parameter-space attractor basins via kNN |
| `plot_model_schematic` | 6 | LCSS-1 (generalised) — programmatic ABM schematic from cell types + interactions (v0.7.1) |
| `list_viz_figures` | 6 | Catalogue of Phase-6 figure tools |

## CLI verbs

```bash
tmelandscape sample                # step 1
tmelandscape summarize             # step 3
tmelandscape normalize             # step 3.5
tmelandscape embed                 # step 4
tmelandscape cluster               # step 5
tmelandscape statistics list/describe       # step 3 discovery
tmelandscape normalize-strategies list      # step 3.5 discovery
tmelandscape embed-strategies list          # step 4 discovery
tmelandscape cluster-strategies list        # step 5 discovery
tmelandscape viz-figures list               # step 6 discovery
tmelandscape version
```

Note: Phase 6 does **not** ship per-figure CLI verbs. Eleven verbs in
one namespace would overwhelm `--help`; agents reach the figures via
the MCP tools above, humans via `tmelandscape.viz.*` Python imports.
The `viz-figures list` discovery verb returns the same catalogue as the
`list_viz_figures` MCP tool.

## ADRs (10)

| # | Title | Phase | Key invariant |
| --- | --- | --- | --- |
| 0001 | Package name `tmelandscape` | 0 | — |
| 0002 | `uv` + pyproject.toml | 0 | — |
| 0003 | Zarr as the ensemble-store format | 0/3 | Zarr v3 acceptable; document spec drift |
| 0004 | MCP server is a first-class surface | 0 | Every public API has an MCP tool |
| 0005 | v1 scope ends at clustering | 0 | No MSM/MDP, no projection in v1 |
| 0006 | Normalisation is a discrete pipeline step | 1/3.5 | **Never overwrite raw data**; **no built-in feature drops** |
| 0007 | Two-stage Leiden + Ward clustering | 1/5 | Reference faithfulness for the clustering pipeline |
| 0008 | Dependency pin policy | 2 | Git+URL deps tagged before PyPI; pin via tag |
| 0009 | No hardcoded statistics panel | 3 | **Dynamic discovery**; user picks the panel |
| 0010 | Cluster-count auto-selection | 5 | **No silent default for `n_final_clusters`**; auto-select via tunable metric (default: WSS elbow) |

## Project owner's binding directives (cumulative)

1. **Never overwrite raw data** — applies to every pipeline step. Each phase writes a NEW Zarr at a user-supplied path.
2. **No hardcoded panels / defaults / cluster counts** — `SummarizeConfig.statistics` is required; `EmbeddingConfig.window_size` is required; `ClusterConfig.n_final_clusters` defaults to `None` (auto-select via tunable metric, default WSS elbow — ADR 0010). Strategy literals can have defaults, but data-selection knobs cannot bake in literature numbers.
3. **No built-in feature drops** — `drop_columns`/`drop_statistics` always default to `[]`.
4. **Buddy-pair pattern for non-trivial phases** — Implementer agent + Reviewer agent per stream; reviewer audits read-only and emits BUG/RISK/SMELL findings; orchestrator integrates.
5. **Three public surfaces** — every pipeline step exposes Python API, CLI, MCP tool, with integration tests proving they produce equivalent output.
6. **Dependency pins tagged, not floating** — `tissue_simulator` and `spatialtissuepy` pinned via git tags (ADR 0008). Currently `@v0.1.4` and `@v0.0.1` respectively.

## In-flight tasks

_None._ Phase 6 complete (v0.7.0). v1 scope per ADR 0005 is functionally complete. Next phase is Phase 7 (release hardening) — see ROADMAP.

## Open questions (for Eric)

_None as of v0.7.1._ All three v0.7.0 open questions were resolved on 2026-05-14 (see decision log):

- ~~WSS-elbow algorithm pick~~ → **Option 5 accepted**: ship multiple metrics; see [decision log](decisions/2026-05-14-wss-elbow-option-5-accepted.md). Three new metrics land in v0.7.1.
- ~~LCSS Figure 1 schematic SVG~~ → **now in scope as a programmatic generator**; see [decision log](decisions/2026-05-14-lcss-1-schematic-in-scope.md). New `plot_model_schematic` function lands in v0.7.1.
- ~~Phase 7 scope confirmation~~ → **no PyPI**; see [decision log](decisions/2026-05-14-no-pypi-ever.md). ROADMAP Phase 7 simplified to real-data CI gate, GitHub Pages, docs-up-to-date, CITATION.cff. Zenodo deposit is at Eric's discretion, not a phase-completion gate.

Resolved earlier this session (see decision log):

- ~~Phase 6 scope~~ — figures decided and shipped in v0.7.0.
- ~~PyPI plan for `tissue_simulator` / `spatialtissuepy`~~ — not a goal; ADR 0008 amended.

## Deferred follow-up tickets (v0.7.x)

Cumulative across Phase 5 + Phase 6 reviewer findings. None are blockers.

**From Phase 5 reviews:**

1. **Marginal-decrease fallback semantics** in `cluster/selection.py` — captured in [decision log: WSS-elbow algorithm options](decisions/2026-05-14-wss-elbow-algorithm-options.md). Pending owner pick (Open Q #1).
2. **Tighten the auto-selection test range** from `chosen in [2, 4]` to `==2`. Safe to do once CI confirms stability across kneed minor versions.
3. **Decide on logging consistency across phases.** Phase 5 emits `cluster_ensemble.start` / `.done` structlog events; Phase 3.5 and Phase 4 orchestrators don't. Either retrofit or drop. Currently keeping the Phase-5 logs — they live on stderr.

**From Phase 6 reviews:**

4. **`Axes.get_xlim()` float-equality** in `test_viz_embedding.py` — switch to `np.testing.assert_allclose` for future-proofing.
5. **`warnings.warn` on `leiden_labels` graceful degradation** in `plot_state_feature_clustermap` so the silently-uniform row-colour bar is observable.
6. **`warnings.warn` on `KNeighborsClassifier` silent neighbor clamp** in `plot_attractor_basins`.
7. **Quiver false-positive-bin assertion** in `test_phase_space_vector_field_*` — strengthen to distinguish real-NaN vs matplotlib's `Quiver.U/V` NaN→1.0 substitution.
8. **Entry-point cross-marker test** in `plot_phase_space_vector_field`.
9. **`n_windows < terminal_window_count` edge-case test** for `join_manifest_cluster`.
10. **Clustermap data-correctness test** — tighten via inverting `dendrogram_row.reordered_ind`.

## Quirks worth knowing (across phases)

- **tissue_simulator monkey-patch** (Phase 2): upstream's unseeded `np.random.default_rng()` calls are monkey-patched at the call site for the duration of `generate_initial_conditions`. Scoped via `ExitStack`. File upstream issue when convenient.
- **Interaction-key `|` rewrite** (Phase 3): output keys like `interaction_<src>_<dst>` are rewritten to `interaction_<src>|<dst>` because cell-type names contain underscores (`M0_macrophage`). Off via `SummarizeConfig.rewrite_interaction_keys=False`.
- **Empty-timepoint contract** (Phase 3): only `cell_counts` emits a row when a timepoint has zero live cells; the aggregator NaN-fills missing entries from the union schema. Centrality, fractions, interactions stay silent.
- **2D `time` coord** (Phase 3): `time` is `(simulation, timepoint)`-aligned, not `(timepoint,)`-aligned. Different sims may emit different wall-clock times for the same step index.
- **Sweep-scoped IC subdirectories** (Phase 2 polish): ICs land under `<initial_conditions_dir>/sweep_<hash>_<timestamp>/`. `SweepManifest.ic_root()` returns the actual directory.
- **Float32→float64 promotion** (Phase 3.5 algorithm; Phase 5 orchestrator): both promote float32 inputs to float64. Documented in the affected docstrings.
- **NaN policy in `fill_nan_with`** (Phase 3.5): config validator rejects NaN to keep `model_dump_json` round-trips lossless.
- **`output_variable == "value"`** (Phase 3.5) and **the three variable-collision checks** (Phase 4): each orchestrator has defence-in-depth guards in addition to the config validators. Phase 5 extends this to a six-way variable-collision check on `ClusterConfig`.
- **WSS k=1 anchor** (Phase 5 selection): when `cluster_count_metric="wss_elbow"`, the algorithm evaluates a private k=1 anchor in addition to the user's candidate range so `kneed` can see the convex elbow; the returned candidates / scores arrays expose only the user range (the anchor is not surfaced). See ADR 0010 + the follow-up ticket on marginal-decrease semantics.
- **Modularity partition doesn't take resolution** (Phase 5 algorithm): `leidenalg.ModularityVertexPartition` doesn't accept `resolution_parameter`; the algorithm dispatches accordingly. CPM (the reference default) and RBConfiguration do.
- **Zarr v3 unstable string dtype warnings** (Phase 3 / ADR 0003 update): xarray writes string coords as `FixedLengthUTF32` which is pre-spec on Zarr v3; `pyproject.toml.[tool.pytest.ini_options].filterwarnings` filters them in tests.
- **Structured logging now active in CLI** (Phase 5): `tmelandscape/cli/main.py` calls `configure_logging()` in the root callback, routing structlog to stderr so CLI JSON-stdout summaries stay machine-parseable. Library code uses `tmelandscape.utils.logging.get_logger`.

## Next agent's first actions

1. **Read** `docs/development/HANDOFF.md` (the cold-start guide), then this STATUS, then `AGENTS.md`, then `docs/development/decisions/README.md` (decision-log process).
2. **Verify the project state**: `uv sync --all-extras && uv run pytest -q` should show **454 passed, 1 deselected**.
3. **Address Open Questions** with Eric (WSS-elbow algorithm pick, LCSS-1 SVG asset, Phase 7 scope confirmation).
4. **Address deferred follow-up tickets** if and when there's spare bandwidth — none are urgent.
5. If Phase 7 (release hardening) is greenlit, **draft `tasks/08-release-hardening.md`** mirroring the structure of `tasks/06-clustering-implementation.md` / `tasks/07-visualisation-implementation.md`.

## Last-session handoff

**Session date:** 2026-05-14
**Agent:** Claude Code (claude-opus-4-7)

A single working session shipped **three releases**: v0.6.0 (Phase 5 — clustering), v0.6.1 (housekeeping + decision-log system), and v0.7.0 (Phase 6 — visualisation). 519 tests passing, all checks green. 22 MCP tools registered. All decisions captured under `docs/development/decisions/` (12 entries plus a chronological INDEX).

Handoff documentation refreshed:

- `docs/development/STATUS.md` — this file.
- `docs/development/HANDOFF.md` — cold-start agent onboarding guide.
- `docs/development/ROADMAP.md` — Phases 5 and 6 marked COMPLETE; Phase 7 next.
- `CHANGELOG.md` — v0.6.0, v0.6.1, v0.7.0 entries.
- `tasks/06-clustering-implementation.md` and `tasks/07-visualisation-implementation.md` — both marked COMPLETE.
- `docs/adr/0010-cluster-count-auto-selection.md` (new), `docs/adr/0008-dependency-pin-policy.md` (revised).
- `docs/concepts/cluster.md`, `docs/concepts/viz.md` — filled in.
- `docs/development/decisions/` — new directory; 12 entries plus README, TEMPLATE, INDEX.

Phase 6 wave-by-wave summary:

- **Pre-Wave**: spawned scope-research agent against LCSS + TNBC PDFs and reference notebooks; identified 10 figure functions / 11 figures + an SVG-only LCSS-1; drafted `tasks/07-visualisation-implementation.md` with frozen API contracts; added `seaborn>=0.13` to `viz` extra.
- **Wave 1 (parallel implementers)**: A wrote `viz/embedding.py` (5 plot fns + `fit_umap` + 25 tests); B wrote `viz/trajectories.py` (2 plot fns + 15 tests); C wrote `viz/dynamics.py` (3 plot fns + 17 tests) **and** `landscape/__init__.py` (`join_manifest_cluster` + 8 tests). **65 new unit tests**.
- **Wave 2 (parallel reviewers, read-only)**: A2 LGTM-with-nits, B2 LGTM-with-nits, C2 LGTM-with-nits. **No BUGs.** B2 first run hit the 600s watchdog; re-dispatched with tighter time budget.
- **Wave 3 (orchestrator)**: applied must-do reviewer fixes (centralised seaborn mypy override; fixed 7 test-file mypy errors; strengthened contour + vector-field assertions; tightened mismatched-sim error message); wrote 5 decision-log entries; added 10 MCP tools + `list_viz_figures` discovery + `viz-figures list` CLI; wrote 12 integration tests; filled `docs/concepts/viz.md`; updated handoff docs; bumped to v0.7.0.

Phase 7 (release hardening, target v1.0.0) is next once Eric confirms scope.
