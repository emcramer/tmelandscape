# Decision: Phase 6 — visualisation session log (v0.7.0)

- **Date:** 2026-05-14 (UTC)
- **Status:** Accepted (work shipped as v0.7.0)
- **Owner / decider:** Eric (directives) + Claude orchestrator (execution)
- **Session agent:** claude-opus-4-7, 1M-context

## Context

Phase 6 of `tmelandscape` — producing the publication figures from the
LCSS and TNBC manuscripts programmatically. Owner directive
(2026-05-14):

> We will want to be able to create the following figures from the
> LCSS manuscript: 1, 3, 4, 6. And the following figures from the
> other TNBC manuscript: 2a-e, 6a-c.

That's **eleven data figures** plus one schematic (LCSS Fig. 1, shipped
as a static SVG asset under `docs/assets/` per the task file's
out-of-scope clause).

This session followed the v0.6.0 / v0.6.1 ship earlier the same day,
and built on the new decision-log system established in the
[decision-log-system entry](./2026-05-14-decision-log-system.md).

## Decisions made during the session

The session captured **seven** standalone decision-log entries plus this
session log. Brief index of decisions written:

1. [`umap_result` parameter rename](./2026-05-14-viz-umap-result-param-rename.md)
   — A1's first positional kwarg shadow-fix, accepted with a task-file update.
2. [`plot_time_umap` colours by window-bound midpoint](./2026-05-14-viz-time-umap-uses-window-bounds.md)
   — Phase 4's coord-skip forces a derived computation rather than the
   reference's direct 2D `time` lookup.
3. [LCSS-3 vector field uses "both endpoints in state s"](./2026-05-14-viz-lcss3-vector-field-semantics.md)
   — strict interpretation of the TNBC Methods prose; cross-checked
   against Stream C's TNBC-6b implementation (same convention).
4. [viz.trajectories deviations](./2026-05-14-viz-trajectories-deviations.md)
   — ragged trajectories raise, `leiden_labels` optional with graceful
   degradation, first-appearance sim ordering.
5. [Centralise `seaborn.*` in mypy overrides](./2026-05-14-seaborn-mypy-override.md)
   — Wave-3 cleanup of cross-stream per-import ignores.
6. [Terminal cluster label is the mode of the last N windows](./2026-05-14-terminal-cluster-label-mode.md)
   — C1's algorithmic choice for `join_manifest_cluster`.
7. [Hand-roll Benjamini-Hochberg FDR for TNBC-6c](./2026-05-14-bh-fdr-hand-rolled.md)
   — avoid adding `statsmodels` for ~10 LOC of correction logic.

## Session log — wave-by-wave

### Pre-Wave-1 (orchestrator)

1. Spawned a research agent to scope the figures against the reference
   notebooks and the manuscript PDFs. Report identified:
   - 10 figure functions / 11 figures (LCSS-4 and TNBC-2e share
     `plot_feature_umap`).
   - LCSS-1 is a schematic; ship as SVG asset.
   - LCSS-6, TNBC-6b, TNBC-6c have **no direct reference script** —
     implementable from manuscript Methods prose.
   - `seaborn>=0.13` needed in the `viz` extra.
   - Stream-C-only prerequisite: `landscape.join_manifest_cluster`.
2. Drafted `tasks/07-visualisation-implementation.md` with frozen API
   contracts and stream allocation (A: UMAP family, B: heatmaps,
   C: dynamics + landscape join).
3. Bumped `viz` extra to include `seaborn>=0.13`; committed as
   `43c2b01` ("docs(phase-6): drafted task file + seaborn dep").

### Wave 1 — three parallel implementer agents

| Stream | Agent ID | Files | Tests | Verification | Notes |
| --- | --- | --- | --- | --- | --- |
| A (UMAP family) | a16cc6f... | `viz/__init__.py` (3), `viz/embedding.py` (784) | 25 | all gates pass | param rename `umap → umap_result`; `# type: ignore[import-untyped]` on seaborn; `0.5*(start+end)` for time; "both endpoints in s" for vector field |
| B (heatmaps) | ab253f4... | `viz/trajectories.py` (440) | 15 | all gates pass | ragged → raise; `leiden_labels` optional; first-appearance sim ordering |
| C (dynamics + join) | a35fe3b... | `landscape/__init__.py` (146), `viz/dynamics.py` (590) | 8 + 17 = 25 | all gates pass | hand-rolled BH-FDR; terminal-label = mode of last N windows; **wrote 2 decision-log entries inline** |

**Wave 1 totals:** 65 new tests. Integrated pre-Wave-2 test suite: 442
passed.

### Wave 2 — three parallel reviewer agents (read-only)

| Stream | Agent ID | Verdict | BUGs | RISKs | SMELLs |
| --- | --- | --- | --- | --- | --- |
| A2 | a6b36b0... | LGTM-with-nits | 0 | 5 | 6 |
| B2 | ab27b84... (after first run watchdog-killed) | LGTM-with-nits | 0 | 2 | 3 |
| C2 | a08d7f5... | LGTM-with-nits | 0 | 5 | 4 |

**Cross-stream finding (all three reviewers):** `seaborn.*` mypy
override needs centralising; per-import `# type: ignore[import-untyped]`
should be stripped in Wave 3.

**B2 first run** was killed by the watchdog at 600s; re-dispatched with
a tighter time-budget prompt and completed cleanly.

### Wave 3 — orchestrator integration

1. **Must-do reviewer fixes:**
   - Added `seaborn.*` to `pyproject.toml` `[[tool.mypy.overrides]]`;
     stripped the per-import ignores in all three viz modules. Decision
     log: [seaborn-mypy-override](./2026-05-14-seaborn-mypy-override.md).
   - Fixed A2 R3 (7 mypy errors in `test_viz_embedding.py:392`) by
     wrapping `c.get_offsets()` in `np.asarray(...)`.
2. **Should-do reviewer fixes:**
   - Strengthened A2 R1 (contour test asserts `LineCollection`
     differential between contours-on vs contours-off).
   - Strengthened A2 R2 (vector-field smoke test asserts at least one
     quiver `PolyCollection`).
   - Tightened C2 R5 (mismatched-sim error-test asserts both offending
     sim ids appear in the message).
3. **Decision-log entries** (Wave-3 batch): five new entries
   (umap_result rename, time-coord, LCSS-3 vector-field, viz.trajectories
   deviations, seaborn override). INDEX updated.
4. **MCP tools:** 10 figure tools (one per figure function) plus
   `list_viz_figures` discovery tool. Registered on
   `tmelandscape.mcp.server`. **Total MCP tool count: 11 → 22.**
5. **CLI discovery:** `tmelandscape viz-figures list` verb. Per-figure
   CLI verbs explicitly **not** shipped per the task file's "MCP
   surface" section (eleven verbs in one namespace would overwhelm
   `--help`).
6. **Integration test:** `tests/integration/test_visualisation_end_to_end.py`
   — 12 tests covering Python-API ↔ MCP equivalence on every figure
   tool plus the discovery surface. All pass.
7. **Docs:** `docs/concepts/viz.md` written (was a placeholder);
   `mkdocs.yml` nav updated.
8. **Task file:** frozen API updated to `umap_result: UMAPResult`;
   status row marked COMPLETE.
9. **Handoff updates:** STATUS, ROADMAP, CHANGELOG bumped to v0.7.0.
10. **Bump + verify + commit + tag + push:** `pyproject.toml` and
    `src/tmelandscape/__init__.py` bumped to 0.7.0. Verification —
    pytest, ruff, format, mypy, mkdocs --strict all green. Commit, tag,
    push pending owner approval (the pattern from v0.6.0 / v0.6.1).

## Reviewer findings applied vs. deferred

**Applied in v0.7.0:**

- All three reviewers' MUST-DO and SHOULD-DO items (see Wave 3 above).
- All four orchestrator-recommended decision-log entries.

**Deferred to v0.7.1** (none are blockers):

- A2 R4: integration test exercising a real Phase-5 output (Wave 3
  uses a synthetic fixture, which suffices for the equivalence test;
  real-data verification is the `pytest -m real` gate's job).
- A2 R5: switch float-equality on `Axes.get_xlim()` to `assert_allclose`
  for future-proofing.
- A2 S5, S6: minor docstring + error-message tightening.
- B2 nit: optional `warnings.warn` when `leiden_labels` is absent.
- B2 nit: tighten clustermap data-correctness test by inverting the
  dendrogram reordering.
- C2 R1: Quiver "false-positive bin" complement assertion.
- C2 R2: entry-point cross-marker test.
- C2 R3: `n_windows < terminal_window_count` edge-case test.
- C2 R4: `warnings.warn` on `KNeighborsClassifier` silent neighbor clamp.

## Consequences

- v0.7.0 shipped end-to-end. Pipeline now spans steps 1, 3, 3.5, 4, 5,
  6 — every step except 2 (external; runs PhysiCell sims).
- v1 scope per [ADR 0005](../../adr/0005-no-msm-in-v1.md) is now
  **functionally complete**; the remaining work is v0.7.x reviewer
  follow-ups, optional LCSS-1 SVG asset, and v1.0 release hardening
  (CI, PyPI publish, Zenodo DOI — see ROADMAP Phase 7).
- The decision-log discipline established in v0.6.1 paid off
  immediately: implementer C1 wrote two entries unprompted during
  Wave 1, capturing decisions that would have been ambiguous to future
  readers.

## References

- [Phase 6 task file](../../../tasks/07-visualisation-implementation.md)
- [ADR 0005 — v1 scope ends at clustering](../../adr/0005-no-msm-in-v1.md)
- [ADR 0009 — no silent hardcoded science defaults](../../adr/0009-no-hardcoded-statistics-panel.md)
- CHANGELOG v0.7.0 entry
- Commits: `43c2b01` (task file + seaborn dep), `<v0.7.0 ship SHA>`
- Tag: `v0.7.0`
