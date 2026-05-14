# STATUS — current session resume doc

> Updated at the **end** of every agent session. New agents read this **first**, then [HANDOFF.md](HANDOFF.md) for the cold-start guide.

## Where the project is (2026-05-14)

**v0.6.0 shipped.** Pipeline steps 1, 3, 3.5, 4, and 5 are implemented end-to-end via three public surfaces (Python API, CLI, MCP). Step 2 (running PhysiCell simulations) is intentionally out of scope. v1 scope (per [ADR 0005](../adr/0005-no-msm-in-v1.md)) ends at clustering; the next phase is visualisation (Phase 6, target v0.7.0).

| Phase | Step | Version | Status | Reference oracle |
| --- | --- | --- | --- | --- |
| 0 | Bootstrap | v0.0.1 | shipped | — |
| 1 | Reference audit | (no bump) | shipped | the `reference/` directory |
| 2 | Sampling | v0.1.0 → v0.1.1 (fixes) | shipped | `/tmp/physim-calibration/code/sampling.py` |
| 3 | Summarisation | v0.2.0 → v0.3.0 (panel rollback) | shipped | `spatialtissuepy` registry |
| 3.5 | Normalisation | v0.4.0 | shipped | `reference/00_abm_normalization.py` |
| 4 | Embedding | v0.5.0 | shipped | `reference/utils.py::window_trajectory_data` |
| 5 | Clustering | v0.6.0 | **just shipped** | `reference/01_abm_generate_embedding.py` lines ~519-720 |
| 6 | Visualisation | (target v0.7.0) | **NEXT** | TBD |

## Verification snapshot (v0.6.0)

- `uv run pytest -q` — **375 passed, 1 deselected**, 1 warning (`spatialtissuepy.topology.visualization` upstream deprecation, harmless).
- `uv run ruff check .` — clean.
- `uv run ruff format --check .` — clean.
- `uv run mypy src` — clean (45 source files, strict mode).
- `uv run mkdocs build --strict` — exit 0.
- `tmelandscape version` — prints `0.6.0`.
- `tmelandscape-mcp` — boots; **11 tools registered**.

## MCP tools (11)

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
tmelandscape version
```

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

_None._ Phase 5 complete. Phase 6 (visualisation) not yet started; no task file pre-drafted yet.

## Open questions (for Eric)

1. **Phase 6 (visualisation) — what to ship.** ROADMAP currently lists FNN/MI diagnostics, UMAP scatter, state-coloured trajectories. Which of these are highest priority? Are there figures from the LCSS paper or other manuscripts that v0.7.0 should reproduce? Should we draft a task file similar to `tasks/06-clustering-implementation.md` before kicking off?
2. **PyPI publishing for `tissue_simulator` and `spatialtissuepy`.** Both are git-pinned via tag right now (per ADR 0008). The ADR's target is to migrate to PyPI before v1.0 ships. Is there a timeline for that, or should we plan to remain on git+URL through v0.7.0?

## Deferred follow-up tickets from Phase 5 reviews

These were noted by reviewers but punted out of v0.6.0 — none are blockers.

1. **Marginal-decrease fallback semantics** in `cluster/selection.py`. The WSS k=1 anchor dominates the kneed knee detection; when kneed returns `None` and the fallback runs, it currently always selects `k_min` because the steepest-decrease segment is the 1→2 step. Either refactor the fallback to operate on the un-anchored candidates, or document explicitly that the fallback collapses to `k_min` under the anchor regime.
2. **Tighten the auto-selection test range.** `test_auto_selection_two_blob_wss_elbow_picks_small_k` currently asserts `chosen in [2, 4]`; if the choice is stable as `==2` across kneed minor versions in CI, tighten it.
3. **Add a regression fixture for elbows at k≥4** to confirm the k=1 anchor doesn't bias auto-selection toward smaller k in pathological cases.
4. **Decide on logging consistency across phases.** Phase 5 emits `cluster_ensemble.start` / `.done` structlog events (per contract); Phase 3.5 and Phase 4 orchestrators don't log at all. Either retrofit the earlier phases or drop the Phase 5 logs. Currently keeping them — they live on stderr now that `configure_logging()` is wired into CLI startup.

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

1. **Read** `docs/development/HANDOFF.md` (the cold-start guide), then this STATUS, then `AGENTS.md`.
2. **Verify the project state**: `uv sync --all-extras && uv run pytest -q` should show **375 passed, 1 deselected**.
3. **Decide on Phase 6 scope** with Eric (Open Question #1). If approved, pre-draft `tasks/07-visualisation-implementation.md` mirroring the structure of `tasks/06-clustering-implementation.md`.
4. **Address the deferred follow-ups** if and when there's spare bandwidth — none are urgent.
5. **Spawn the buddy-pair team for Phase 6** once the scope is agreed; mirror the Wave-1 / Wave-2 / Wave-3 pattern used in v0.4.0, v0.5.0, and v0.6.0.

## Last-session handoff

**Session date:** 2026-05-14
**Agent:** Claude Code (claude-opus-4-7)

Phase 5 **complete and verified**. 375 tests passing, all checks green. Repo at v0.6.0; commit and tag pending owner approval to push. Handoff documentation refreshed:

- `docs/development/STATUS.md` — this file.
- `docs/development/HANDOFF.md` — cold-start agent onboarding guide (unchanged from v0.5.0 — still accurate).
- `docs/development/ROADMAP.md` — Phase 5 marked COMPLETE, Phase 6 unchanged.
- `CHANGELOG.md` — v0.6.0 entry with full reviewer-findings log.
- `tasks/06-clustering-implementation.md` — revised in-flight (added auto-selection contract) then executed.
- `docs/adr/0010-cluster-count-auto-selection.md` — new ADR (cluster-count auto-selection policy).
- `docs/concepts/cluster.md` — filled in (was placeholder).

Phase 5 wave-by-wave summary:

- **Pre-Wave**: bumped `tissue_simulator` pin from floating-main (v0.1.0 commit) to tagged `@v0.1.4`; `spatialtissuepy` pin moved from commit (`@c03cfa4`) to tag (`@v0.0.1`). 247 tests stayed green.
- **Wave 1 (parallel implementers)**: A wrote `leiden_ward.py` + `selection.py` + 26 tests; B wrote `cluster/__init__.py` + 18 tests (mocked the algorithm to insulate from cross-stream timing); C wrote `config/cluster.py` + `alternatives.py` + 77 tests. Two of three agents hit transient Cloudflare 522s on first dispatch; reissued cleanly.
- **Wave 2 (parallel reviewers, read-only)**: A2 LGTM-with-nits (no BUGs); B2 LGTM; C2 LGTM. All recommended changes were cheap; applied in Wave 3a.
- **Wave 3 (orchestrator)**: applied review fixes, wrote CLI + MCP tools + 7 integration tests, filled `docs/concepts/cluster.md`, wired `configure_logging()` into CLI startup (logs now flow to stderr so JSON-stdout stays pure), updated handoff docs, bumped to v0.6.0.

Phase 6 (visualisation, v0.7.0) is unblocked once Eric confirms the scope per Open Question #1.
