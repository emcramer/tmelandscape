# Decision: Phase 5 — two-stage Leiden + Ward clustering session log (v0.6.0)

- **Date:** 2026-05-14 (UTC) — note that work started late 2026-05-13 local
- **Status:** Accepted (work shipped as v0.6.0)
- **Owner / decider:** Eric (directives) + Claude orchestrator (execution)
- **Session agent:** claude-opus-4-7, 1M-context

## Context

Phase 5 of the `tmelandscape` pipeline — two-stage Leiden + Ward
clustering of the windowed embedding from Phase 4 — had been
**pre-drafted** at the end of the v0.5.0 session, with frozen API
contracts in `tasks/06-clustering-implementation.md`. The owner opened
this session by answering the v0.5.0 open questions:

1. **Dependency pin update.** Use the latest tags upstream:
   `tissue_simulator@v0.1.4` and `spatialtissuepy@v0.0.1`.
2. **Phase 5 binding invariants.** Leave raw values untouched; write
   cluster labels to a NEW file or alongside; **do not assume a default
   value for `n_final_clusters`** — instead, *optimise* via a metric
   such as WSS elbow / Calinski-Harabasz / silhouette, defaulting to
   WSS elbow.

This second directive **revised the pre-drafted contract**. The original
task file had `n_final_clusters: int = Field(..., ge=2)` (required, no
default); the revised contract makes it `int | None = Field(default=None,
ge=2)` with `cluster_count_metric` driving auto-selection when `None`.

## Decisions made during the session

### D1. Revise the frozen contract before Wave 1, not after

**Context.** The pre-drafted task file would have shipped a contract
that the owner explicitly rejected at session start.

**Decision.** Rewrite `tasks/06-clustering-implementation.md` to embed
the auto-selection layer in the frozen API contract *before* spawning
implementer agents. Capture the rationale in a new ADR (0010).

**Reasoning.** Spawning implementers against a contract the owner has
already rejected would have wasted three parallel agent runs and
required a Wave-2.5 re-spec. The cost of editing the task file plus
writing ADR 0010 was ~30 minutes; the alternative would have cost
hours.

### D2. WSS-elbow as the default metric (vs. CH or silhouette)

**Context.** The owner named three metrics — WSS elbow, CH, silhouette
— and said "Default to the elbow of the WSS — I think you can determine
this by calculating the marginal decrease in WSS as you increment
cluster number and then finding the point of diminishing margins."

**Decision.** Implement all three under `cluster_count_metric` literal;
`wss_elbow` is the default. Use `kneed.KneeLocator` (already in
`pyproject.toml` core deps from v0.4.0). The owner's "marginal decrease"
description became the *fallback* when kneed can't detect a knee.

**Reasoning.** The kneed library implements the Satopaa et al. 2011
algorithm, which is the standard "knee of a curve" detector and matches
the owner's "point of diminishing margins" semantics. The marginal-
decrease formula is a robust fallback for monotonic-but-no-clear-knee
curves.

### D3. WSS k=1 private anchor

**Context.** Empirically, kneed could not detect the convex elbow on a
2-blob fixture when the candidate range started at `k_min=2` — the
algorithm needed to see the very large WSS at k=1 to register the
convex shape.

**Decision (Implementer A1 + orchestrator).** Evaluate WSS at `k=1`
internally as a **private** anchor passed to `KneeLocator`. Clamp the
returned knee to `>= k_min`. The publicly reported
`cluster_count_candidates` and `cluster_count_scores` arrays remain
exactly the user-requested range.

**Reasoning.** Without the anchor, the auto-selection tests on
well-separated cluster fixtures failed. With it, they pass and the
public output contract is preserved.

**Follow-up cost.** Reviewer A2 RISK: this neutralises the
marginal-decrease fallback (the 1→2 transition is always the steepest
in a convex decreasing curve, so `argmin(deltas) + 1` always returns
`k_min` when the anchor is in front). Captured as a deferred ticket;
see [WSS-elbow algorithm options](./2026-05-14-wss-elbow-algorithm-options.md).

### D4. `ModularityVertexPartition` doesn't accept `resolution_parameter`

**Context.** Implementer A1 surfaced this leidenalg API constraint
during Wave 1.

**Decision.** Dispatch in `cluster_leiden_ward`: CPM and RBConfiguration
receive `resolution_parameter=leiden_resolution`; Modularity does not.
The reference uses CPM, so reference fidelity is preserved.

### D5. Implementer C added `Field(description=...)` to "bare-default"
fields in the frozen contract

**Context.** The frozen contract had bare-default fields like
`strategy: Literal["leiden_ward"] = "leiden_ward"`. Stream C wrapped
each with `Field(default=..., description=...)` so every property
carries a description in `ClusterConfig.model_json_schema()`.

**Decision.** Accept the deviation. It matches AGENTS.md invariant #1
("Pydantic configs everywhere ... JSON-Schema availability for the MCP
server and CLI") and the precedent in `config/embedding.py`.

### D6. Logging consistency: route structlog to stderr; keep the new logs

**Context.** Stream B added `cluster_ensemble.start` and `.done`
structlog events per the contract. Phase 4 and Phase 3.5 orchestrators
emit no logs. The new logs polluted CLI stdout (which is supposed to be
pure JSON), breaking the CLI integration test.

**Decision.** Wire `tmelandscape.utils.logging.configure_logging()`
into the CLI root callback (`src/tmelandscape/cli/main.py`). Logs flow
to stderr; CLI stdout remains pure machine-readable JSON. Keep the new
logs in `cluster_ensemble`. Don't retrofit Phase 4 / 3.5 in this commit
(deferred ticket).

**Reasoning.** The contract requested logging; the logs are well-
structured; routing to stderr resolves the test failure without
deleting useful telemetry.

### D7. Centralise mypy overrides in `pyproject.toml`

**Context.** Stream A added seven `# type: ignore[import-untyped]` per
import. With `warn_unused_ignores=true` in `pyproject.toml`, these
become brittle if any upstream dep ships stubs.

**Decision.** Move all stub-less third-party module names
(`scipy`, `scipy.*`, `sklearn.*`, `kneed.*`, `igraph.*`, `leidenalg.*`)
into the existing `[[tool.mypy.overrides]]` block. Strip the per-import
ignores from `leiden_ward.py` and `selection.py`.

**Reasoning.** Single source of truth; future-proof against upstream
stub releases.

## Session log — wave-by-wave

### Pre-Wave: dependency pin update

- Bumped `pyproject.toml`: `tissue_simulator @ git+...` (no ref) →
  `@v0.1.4`. `spatialtissuepy @ ...@c03cfa4` → `@v0.0.1` (same commit,
  cosmetic).
- `uv sync --all-extras`: tissue_simulator 0.1.0 → 0.1.4.
- `uv run pytest -q`: 247 passed, 1 deselected — same as v0.5.0
  baseline. No regression from the dep bump.

### Wave 1 — three parallel implementer agents

Spawned via `Agent` tool, general-purpose subagent_type, run in
background.

| Stream | Agent ID | Files | Tests | Verification |
| --- | --- | --- | --- | --- |
| A (algorithm + selection) | a7aa752... | `leiden_ward.py` (315), `selection.py` (329) | 26 | all gates pass |
| B (Zarr orchestrator) | adbb5df... (retry) | `cluster/__init__.py` (400), tests (837 LOC, 18 tests) | 18 | all gates pass |
| C (config + alternatives) | a43ea70... (retry) | `config/cluster.py` (263), `alternatives.py` (46), tests | 77 | all gates pass |

**Two Cloudflare 522 errors hit on initial dispatch** (Streams B and C);
both re-dispatched cleanly. Total Wave-1 new tests: **121**.

### Wave 2 — three parallel reviewer agents (read-only)

| Stream | Verdict | BUGs | RISKs surfaced | SMELLs surfaced |
| --- | --- | --- | --- | --- |
| A2 | LGTM-with-nits | 0 | 4 | 4 |
| B2 | LGTM | 0 | 4 | 3 |
| C2 | LGTM | 0 | 0 | 3 |

**No BUGs.** All reviewer recommendations were either applied in
Wave 3 (cheap fixes) or deferred as follow-up tickets (see STATUS.md).

### Wave 3 — orchestrator integration

1. **Applied cheap reviewer fixes:**
   - Moved 7 per-import `# type: ignore[import-untyped]` into
     `[[tool.mypy.overrides]]` (decision D7 above).
   - Added `linkage_matrix.shape[1] == 4` defence-in-depth assertion
     in `cluster_ensemble`.
   - Added docstring note about the float64 upcast on `embedding`
     passthrough; documented `leiden_to_final` intentionally absent
     from output Zarr.
   - Tightened `test_source_variable_missing_raises` regex to
     `r"available variables: \[.+\]"`.
2. **Built three public surfaces:**
   - CLI: `src/tmelandscape/cli/cluster.py` + `cluster_strategies.py`,
     wired in `cli/main.py`.
   - MCP: `cluster_ensemble_tool` + `list_cluster_strategies_tool` in
     `mcp/tools.py`; registered in `mcp/server.py`. Total tool count:
     **9 → 11**.
   - Wired `configure_logging()` into CLI root callback (decision D6).
3. **Integration test:** `tests/integration/test_clustering_end_to_end.py`
   covers Python API + CLI + MCP equivalence on both explicit-k and
   auto-select paths. 7 tests, all green.
4. **Docs:** filled in `docs/concepts/cluster.md` (was a placeholder).
   Fixed an `[ADR 0010]` autoref collision with the `[x]` checkbox in
   ROADMAP.md by rephrasing.
5. **Version bump and handoff:**
   - `pyproject.toml`, `src/tmelandscape/__init__.py`: 0.5.0 → 0.6.0.
   - Updated STATUS.md (375 passed, Phase 5 COMPLETE, Phase 6 NEXT).
   - Updated ROADMAP.md (Phase 5 COMPLETE).
   - Updated CHANGELOG.md (v0.6.0 entry with reviewer-findings log).
6. **Final verification:** 375 passed, 1 deselected, 1 warning. ruff +
   format + mypy strict + mkdocs strict all clean.
7. **Commit + tag + push:** `cb2802f`, tag `v0.6.0`, pushed to
   `origin/main` and `origin/v0.6.0`.

## Reviewer findings applied vs. deferred

**Applied in v0.6.0:**

- A2 SMELL: centralised mypy overrides (D7).
- B2 RISK: linkage shape assertion.
- B2 SMELL: float64-cast docstring note + `leiden_to_final` clarification.
- B2 SMELL: tighter regex on `test_source_variable_missing_raises`.

**Deferred to follow-up tickets (logged in STATUS.md and addressed in
v0.6.1 housekeeping bundle):**

- A2 RISK: marginal-decrease fallback semantics under the k=1 anchor.
  See [WSS-elbow algorithm options](./2026-05-14-wss-elbow-algorithm-options.md).
- A2 RISK: tighten the auto-selection test range from `[2, 4]` to
  `==2` if CI stability allows.
- A2 RISK: regression fixture for elbows at k≥4.
- B2 SMELL: decide on logging consistency across phases.

## Consequences

- v0.6.0 shipped end-to-end. Pipeline now has all five steps (1, 3,
  3.5, 4, 5) wired through Python API, CLI, and MCP.
- Phase 5 is **complete**; Phase 6 (visualisation, target v0.7.0) is
  next. Task file pending.
- The decision log was established this session ([decision-log
  system](./2026-05-14-decision-log-system.md)); from here forward
  every working session writes one of these entries.

## References

- [ADR 0007 — Two-stage Leiden + Ward clustering](../../adr/0007-two-stage-leiden-ward-clustering.md)
- [ADR 0008 — Dependency pin policy](../../adr/0008-dependency-pin-policy.md)
- [ADR 0010 — Cluster-count auto-selection](../../adr/0010-cluster-count-auto-selection.md)
- [tasks/06-clustering-implementation.md](../../../tasks/06-clustering-implementation.md)
- [CHANGELOG.md — v0.6.0 entry](../../../CHANGELOG.md)
- Commits: `cb2802f` (v0.6.0 ship)
- Tag: `v0.6.0`
