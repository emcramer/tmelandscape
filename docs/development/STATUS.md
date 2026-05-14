# STATUS — current session resume doc

> Updated at the **end** of every agent session. New agents read this **first**, then [HANDOFF.md](HANDOFF.md) for the cold-start guide.

## Where the project is (2026-05-13)

**v0.5.0 shipped.** Pipeline steps 1, 3, 3.5, and 4 are implemented end-to-end via three public surfaces (Python API, CLI, MCP). Step 2 (running PhysiCell simulations) is intentionally out of scope. Step 5 (two-stage Leiden + Ward clustering) is the next phase, with a pre-drafted task file ready at `tasks/06-clustering-implementation.md` (in the repo root, not on the docs site).

| Phase | Step | Version | Status | Reference oracle |
| --- | --- | --- | --- | --- |
| 0 | Bootstrap | v0.0.1 | shipped | — |
| 1 | Reference audit | (no bump) | shipped | the `reference/` directory |
| 2 | Sampling | v0.1.0 → v0.1.1 (fixes) | shipped | `/tmp/physim-calibration/code/sampling.py` |
| 3 | Summarisation | v0.2.0 → v0.3.0 (panel rollback) | shipped | `spatialtissuepy` registry (68 metrics) |
| 3.5 | Normalisation | v0.4.0 | shipped | `reference/00_abm_normalization.py` |
| 4 | Embedding | v0.5.0 | **just shipped** | `reference/utils.py::window_trajectory_data` |
| 5 | Clustering | (target v0.6.0) | **NEXT** | `reference/01_abm_generate_embedding.py` (Leiden + Ward sections) |

## Verification snapshot (v0.5.0)

- `uv run pytest -q` — **247 passed, 1 deselected**, 1 warning (`spatialtissuepy.topology.visualization` upstream deprecation, harmless).
- `uv run ruff check .` — clean.
- `uv run ruff format --check .` — clean.
- `uv run mypy src` — clean (45 source files, strict mode).
- `uv run mkdocs build --strict` — exit 0.
- `tmelandscape version` — prints `0.5.0`.
- `tmelandscape-mcp` — boots; 9 tools registered.

## MCP tools (9)

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

## CLI verbs

```bash
tmelandscape sample                # step 1
tmelandscape summarize             # step 3
tmelandscape normalize             # step 3.5
tmelandscape embed                 # step 4
tmelandscape statistics list/describe       # step 3 discovery
tmelandscape normalize-strategies list      # step 3.5 discovery
tmelandscape embed-strategies list          # step 4 discovery
tmelandscape version
```

## ADRs (9)

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

## Project owner's binding directives (cumulative)

1. **Never overwrite raw data** — applies to every pipeline step. Each phase writes a NEW Zarr at a user-supplied path.
2. **No hardcoded panels / defaults** — `SummarizeConfig.statistics` is required; `EmbeddingConfig.window_size` is required. Strategy literals can have defaults, but data-selection knobs cannot.
3. **No built-in feature drops** — `drop_columns`/`drop_statistics` always default to `[]`.
4. **Buddy-pair pattern for non-trivial phases** — Implementer agent + Reviewer agent per stream; reviewer audits read-only and emits BUG/RISK/SMELL findings; orchestrator integrates.
5. **Three public surfaces** — every pipeline step exposes Python API, CLI, MCP tool, with integration tests proving they produce equivalent output.

## In-flight tasks

_None._ Phase 5 not yet started; task file pre-drafted but no implementer agents have run yet.

## Open questions (for Eric)

1. **`tissue_simulator` v0.1.0 upstream tag** and **`spatialtissuepy` v0.2.0 upstream tag** — Eric is handling these separately per ADR 0008. Once tags exist, update the `git+URL` pins in `pyproject.toml` from commit SHAs to tag names.
2. **Phase 5 (clustering) — confirm the binding invariants ship:**
   - Cluster labels are written to a NEW Zarr; the input embedding store is never modified.
   - `n_final_clusters` is a required user input (no default); we do not pick "6 TME states" silently.
   - Output structure mirrors the rest of the pipeline (raw arrays preserved; new labels added alongside).

## Quirks worth knowing (across phases)

- **tissue_simulator monkey-patch** (Phase 2): upstream's unseeded `np.random.default_rng()` calls are monkey-patched at the call site for the duration of `generate_initial_conditions`. Scoped via `ExitStack`. File upstream issue when convenient.
- **Interaction-key `|` rewrite** (Phase 3): output keys like `interaction_<src>_<dst>` are rewritten to `interaction_<src>|<dst>` because cell-type names contain underscores (`M0_macrophage`). Off via `SummarizeConfig.rewrite_interaction_keys=False`.
- **Empty-timepoint contract** (Phase 3): only `cell_counts` emits a row when a timepoint has zero live cells; the aggregator NaN-fills missing entries from the union schema. Centrality, fractions, interactions stay silent.
- **2D `time` coord** (Phase 3): `time` is `(simulation, timepoint)`-aligned, not `(timepoint,)`-aligned. Different sims may emit different wall-clock times for the same step index.
- **Sweep-scoped IC subdirectories** (Phase 2 polish): ICs land under `<initial_conditions_dir>/sweep_<hash>_<timestamp>/`. `SweepManifest.ic_root()` returns the actual directory.
- **Float32→float64 promotion** (Phase 3.5 algorithm): the within-timestep normalisation promotes float32 inputs to float64. Documented in the algorithm's docstring.
- **NaN policy in `fill_nan_with`** (Phase 3.5): config validator rejects NaN to keep `model_dump_json` round-trips lossless.
- **`output_variable == "value"`** (Phase 3.5) and **the three variable-collision checks** (Phase 4): each orchestrator has defence-in-depth guards in addition to the config validators.
- **Zarr v3 unstable string dtype warnings** (Phase 3 / ADR 0003 update): xarray writes string coords as `FixedLengthUTF32` which is pre-spec on Zarr v3; `pyproject.toml.[tool.pytest.ini_options].filterwarnings` filters them in tests.

## Next agent's first actions

1. **Read** `docs/development/HANDOFF.md` (the cold-start guide), then this STATUS, then `AGENTS.md`.
2. **Verify the project state**: `uv sync --all-extras && uv run pytest -q` should show **247 passed, 1 deselected**.
3. **Read the Phase 5 task file**: `tasks/06-clustering-implementation.md` (in the repo root, not on the docs site). All Pydantic schemas and function signatures are frozen there.
4. **Confirm with Eric** on the Open Questions above before starting Phase 5 implementation. In particular: confirm the binding invariants for clustering output.
5. **Spawn the buddy-pair team for Phase 5** following the pattern used in v0.4.0 and v0.5.0:
   - Wave 1: 3 Implementer agents in parallel (A: Leiden+Ward algorithm; B: Zarr orchestrator; C: ClusterConfig + alternatives).
   - Wave 2: 3 Reviewer agents in parallel (read-only audit).
   - Orchestrator: apply review findings, integrate, release v0.6.0.

## Last-session handoff

**Session date:** 2026-05-13  
**Agent:** Claude Code (claude-opus-4-7)

Phase 4 **complete and verified**. 247 tests passing, all checks green. Repo is tagged at `v0.5.0` and pushed. Handoff documentation refreshed:

- `docs/development/STATUS.md` — this file.
- `docs/development/HANDOFF.md` — cold-start agent onboarding guide.
- `docs/development/ROADMAP.md` — Phase 5 plan filled in.
- `CHANGELOG.md` — full release history.
- `tasks/06-clustering-implementation.md` — Phase 5 task file pre-drafted with frozen API contracts.

Phase 5 (two-stage Leiden + Ward clustering, v0.6.0) is fully unblocked except for the binding-invariants confirmation in Open Questions #2.
