# STATUS — current session resume doc

> Updated at the **end** of every agent session. New agents read this **first**.

## Current focus

**Phase 3.5 — normalisation: complete (v0.4.0).** Within-timestep normalisation shipped end-to-end via the buddy-pair team (Implementer + Reviewer per stream, all reviewer findings applied pre-integration). The orchestrator reads the input Zarr read-only, writes a NEW Zarr containing both the raw `value` and a `value_normalized` array, refuses to overwrite, inherits the input's chunk grid. 168 tests pass; ruff/format/mypy/mkdocs strict all clean. Ready for Phase 4 (time-delay embedding).

## In-flight tasks

_None._ (`tasks/03-summarize-implementation.md` closed 2026-05-13.)

## Recently completed (Phase 3, 2026-05-13)

- **Recon**: cloned and inspected `spatialtissuepy` (`emcramer/spatialtissuepy`, commit `c03cfa4`). Native PhysiCell parser, no `pcdl` dep. Confirmed install via `git+URL`.
- **Added core deps**: `spatialtissuepy[network] @ git+...@c03cfa4` and `xarray>=2024.5`. Added `pandas-stubs>=2.2` to dev. Widened mypy overrides to cover `spatialtissuepy.*`, `scipy.io.*`.
- **Drafted** `tasks/03-summarize-implementation.md` with frozen Pydantic / function-signature contracts.
- **Buddy-pair team** (3 Implementer + 3 Reviewer agents):
  - **Stream A** (Implementer A1 + Reviewer A2): `summarize_simulation` + synthetic PhysiCell-shaped fixture (3 sims × 3 timepoints × 21 cells, deterministic rebuild via `build.py`, 112 KB).
  - **Stream B** (Implementer B1 + Reviewer B2): `build_ensemble_zarr` (xarray-on-zarr, chunked, NaN-filled for ragged timepoints, provenance .zattrs).
  - **Stream C** (Implementer C1 + Reviewer C2): `SummarizeConfig` (Pydantic, validator against `KNOWN_STATISTICS`) + `registry.compute_statistic` (the only file that knows how spatialtissuepy is organised).
- **5 RISKs surfaced by reviewers, all fixed before integration**:
  - A1: interaction-matrix key separator (cell-type names contain underscores) → rekey to `interaction_<src>|<dst>`.
  - A2: empty-timepoint schema drift → empty-cell timepoints emit no rows except `cell_counts`.
  - B8: silent first-frame-wins for `time` coord → made `time` a 2D `(simulation, timepoint)` coord.
  - B11: Zarr v3 install vs ADR 0003 v2 spec → ADR 0003 update + pytest `filterwarnings` for unstable-spec warnings.
  - C4 / C13: `graph_radius_um` doubles as interaction radius → docstring note; ditto units (μm).
  - C11: SummarizeConfig JSON round-trip (not just dict) → added test.
- **Integration** (orchestrator):
  - `src/tmelandscape/summarize/__init__.py` — top-level `summarize_ensemble`.
  - `src/tmelandscape/cli/summarize.py` + wired into `cli/main.py` (`tmelandscape summarize`).
  - `src/tmelandscape/mcp/tools.py` — `summarize_ensemble_tool` registered on the MCP server.
  - `tests/integration/test_summarize_end_to_end.py` — 5 tests: Python API + CLI + MCP + missing-dir error + API↔CLI equality.
  - `docs/concepts/summarize.md` filled in (88 lines).
- **Phase 2 polish from audit**:
  - Sweep-scoped IC subdirectories: `generate_sweep` now writes ICs under `<initial_conditions_dir>/sweep_<config_hash[:8]>_<timestamp>/`. `SweepManifest` gained `sweep_id` field and `ic_root()` helper. Multiple sweeps coexist without collisions; stale ICs from prior runs no longer haunt the parent dir.
- **ADR 0008**: dependency pin policy (tag git+URL deps; move to PyPI before v1.0).

**Phase 3 verification (all green):**

- `uv run pytest -q` — 115 passed, 1 deselected.
- `uv run ruff check .` + `uv run ruff format --check .` — clean.
- `uv run mypy src` — clean (36 source files, strict mode).
- `uv run mkdocs build --strict` — exit 0.
- `tmelandscape version` — prints `0.2.0`.
- `tmelandscape summarize <manifest.json> --physicell-root <dir>` — end-to-end against the synthetic fixture; emits a clean JSON summary.
- `tmelandscape-mcp` — boots; `generate_sweep` and `summarize_ensemble` tools both callable.

## Blockers

_None._

## Open questions (for Eric)

1. **Tag `tissue_simulator` v0.1.0 and `spatialtissuepy` v0.2.0.** Per ADR 0008, both upstream repos should be tagged at the commits captured in tmelandscape v0.2.0's lockfile (`tissue_simulator @ 67becc1`, `spatialtissuepy @ c03cfa4`). Once tagged, I'll update the pyproject pins from commit SHAs to tags.
2. **Normalisation source data.** Phase 3.5 takes the Zarr from step 3 and applies within-time-step normalisation (per ADR 0006). The reference oracle is `reference/00_abm_normalization.py`. Should the normalisation step write a _second_ Zarr (preserving the raw ensemble for re-runs) or overwrite the value array in place? My recommendation: second Zarr (or new variable in the same store), keep raw immutable.
3. **Drop the six density columns at normalise step?** The reference drops them right before normalisation. Confirm this is where the drop should live in tmelandscape too (vs at summarize time).

## Quirks worth knowing (for the next agent)

- **interaction-matrix keys use `|`.** Pair keys are `interaction_<src>|<dst>` (not `_`), because cell-type names contain underscores. Stream A's test fixture uses the three types `tumor`, `effector_T_cell`, `M0_macrophage`.
- **Empty-timepoint policy.** A timepoint with zero live cells emits only the `cell_counts` row; centrality / fraction / interaction stats are silent. Aggregator NaN-fills the resulting Zarr cells.
- **`time` is 2D.** Coord shape is `(simulation, timepoint)`, not just `(timepoint,)`. Each sim can have its own time array at the same step index.
- **Zarr v3 strings.** xarray writes string coords as `FixedLengthUTF32` which is pre-spec on Zarr v3. Test warnings are filtered via `pyproject.toml.[tool.pytest.ini_options].filterwarnings`. Cross-library reads (zarr.js, future zarr-python) may need to revisit.
- **Sweep-scoped IC dirs.** `generate_sweep` now writes ICs under a `sweep_<hash>_<timestamp>/` subdirectory; manifests gained a `sweep_id` and `ic_root()` helper. The synthetic-fixture tests use `manifest.ic_root()` to find the CSVs.
- **tissue_simulator monkey-patch.** Still in place (see Phase 2 STATUS). Once upstream fixes the unseeded `default_rng()` call, the patch can come out.

## Next agent's first actions

1. Read this file + `AGENTS.md`.
2. Confirm Open Questions 1–3 above with Eric.
3. Open `tasks/04-normalize-implementation.md` and design Phase 3.5 (within-time-step normalisation). Reference oracle: `reference/00_abm_normalization.py` (already in `reference/`, gitignored).
4. Consider the same buddy-pair pattern (Implementer + Reviewer per stream). Streams might be: (a) within-time-step normalisation algorithm, (b) feature-filter (cell-density drop), (c) Zarr read-modify-write or write-new-store driver.
5. Final verify + tag `v0.3.0` after Phase 3.5 ships.

## Last-session handoff

**Session date:** 2026-05-13  
**Agent:** Claude Code (claude-opus-4-7) orchestrator + 6 buddy-pair agents (3 Implementers + 3 Reviewers) + 1 docs agent (timed out, orchestrator finished docs).

Phase 3 **complete** and **verified**. Repo is ready to tag `v0.2.0` and push. Phase 3.5 (normalisation) is unblocked except for Open Questions 1-3.
