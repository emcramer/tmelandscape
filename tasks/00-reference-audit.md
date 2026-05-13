# 00 — Reference-script audit (Phase 1)

- **slug:** 00-reference-audit
- **status:** done (open questions resolved 2026-05-12; full code-trace deferred to per-phase tasks)
- **owner:** Claude Code (claude-opus-4-7) + Eric
- **opened:** 2026-05-12
- **closed:** 2026-05-12
- **roadmap link:** Phase 1 — Reference audit + example data import

## Context

Per the development plan, Phase 1 audits the existing reference scripts that produced the landscapes in the manuscripts. The audit (a) identifies which scripts are authoritative oracles for each pipeline step, (b) captures behaviour that needs to be replicated by tmelandscape, and (c) surfaces architectural decisions the plan didn't anticipate.

Eric pointed us at the `*abm*`-prefixed scripts in `/Users/cramere/OneDrive - Oregon Health & Science University/graduate/knowledgebase/00-projects/parameter-exploration/code/`. Files `00_abm_*`, `01_abm_*`, `02_abm_*` are the landscape-generation oracles; `03_abm_*` and beyond are downstream analysis (out of scope for v1).

## Plan

- [x] Copy oracle scripts to `reference/` (gitignored). Done 2026-05-12: `00_abm_normalization.py`, `01_abm_generate_embedding.py`, `02_abm_state_space_analysis.marimo.py`, `utils.py`.
- [x] First-pass scan: line counts, top-level imports, clustering method, dependencies.
- [ ] **Open question to Eric** (see Decisions section below) — clustering pipeline, normalization placement, format of the reference scripts, dependencies to add.
- [ ] Read each script in full and write a step-by-step trace in this file (deferred until open questions resolved, since they may reframe scope).
- [ ] Open a follow-up task `01-normalization-module.md` *if* Eric confirms normalization should be its own module.

## Findings (first-pass, 2026-05-12)

### File map

| Reference file | Authoritative for | Notes |
| --- | --- | --- |
| `00_abm_normalization.py` (311 lines) | Step 3.5 (normalize) | Within-time-step normalization: per-step mean → power transform → z-score → re-add mean. Drops cell-density columns. |
| `01_abm_generate_embedding.py` (930 lines) | Step 4 (window/embed) + Step 5a (Leiden) + Step 5b (Ward-on-means) | Sliding-window construction (W=50), kNN-graph + Leiden, then Ward on Leiden means. |
| `02_abm_state_space_analysis.marimo.py` (1261 lines) | Step 5 refinement + diagnostics | Likely state-labeling, evaluation, and visualisation. Full read pending. |
| `utils.py` (295 lines) | Shared helpers | Window construction, JSD distance, normalization helpers, labeling helpers. |

### Surprises vs the development plan

1. **Reference scripts are marimo notebooks**, not plain Python (`.marimo.py`). They run under `marimo`. tmelandscape itself will be plain Python; the reference files stay as marimo (oracle only).
2. **Clustering is a two-stage procedure** (not the single Ward step inferred from the LCSS paper):
   - Stage 1: **Leiden community detection** on a kNN graph over the windowed feature space (using `leidenalg` + `python-igraph`).
   - Stage 2: **Ward hierarchical clustering** on the *means* of each Leiden community, merging Leiden's over-segmented communities into the ~6 final TME states.
3. **Window size = 50** (matches LCSS paper; codified in reference as a hard-coded constant for now).
4. **JSD-based metrics** appear in graph construction (`jensen_shannon_divergence` in `utils.py`); kNN distances may be JSD or Euclidean — pending full read.
5. **Density features are filtered out** during normalization (six density columns). Should be a configurable column-filter in the package.
6. **`pyproject.toml` is missing required deps:** `leidenalg`, `python-igraph` (provides `igraph`), `networkx`, `seaborn` (used by reference for plotting; may not be needed in tmelandscape if matplotlib alone suffices).

### Implications for tmelandscape architecture

The plan's `tmelandscape.cluster` module — currently designed around scipy Ward — should be reshaped into a **two-stage clustering pipeline**:

```text
src/tmelandscape/cluster/
├── __init__.py
├── leiden.py          # Leiden on kNN graph (primary)
├── meta.py            # Ward on cluster means (secondary)
├── selection.py       # Resolution / k selection across both stages
└── labels.py          # Persistence + state labels
```

And a normalization step is missing entirely; proposed:

```text
src/tmelandscape/normalize/
├── __init__.py
├── within_timestep.py    # per-step mean → power → z-score → +mean (reference oracle)
├── feature_filter.py     # configurable column drop (density features by default)
└── alternatives.py       # global / local-time / feature-distribution variants
```

These need an ADR before implementation (likely 0006 and 0007).

## Decisions (resolved 2026-05-12)

- [x] **Clustering pipeline.** ✅ Adopt the reference's two-stage Leiden + Ward-on-means as the default. See [[adr-0007-two-stage-leiden-ward-clustering]].
- [x] **Normalization module.** ✅ Add `tmelandscape.normalize` as a separate top-level submodule. See [[adr-0006-normalize-as-pipeline-step]].
- [x] **Reference scripts.** ✅ Keep the marimo notebooks as the oracle in `reference/`. Do not extract parallel plain-Python ports; instead, **port the relevant marimo cells directly into `tmelandscape` modules during each phase**.
- [x] **Dependencies.** ✅ `leidenalg`, `python-igraph`, `networkx` added to core deps (not optional). `scikit-learn` also promoted to core for `PowerTransformer`/`StandardScaler`.

## Follow-ups

- [x] Wrote ADR 0006 (normalize as a discrete step) and ADR 0007 (two-stage Leiden + Ward clustering).
- [x] Added `tmelandscape.normalize` submodule skeleton (`__init__.py`, `within_timestep.py`, `feature_filter.py`, `alternatives.py`).
- [x] Reshaped `tmelandscape.cluster` submodule into `leiden.py` + `meta.py` + `selection.py` + `labels.py`.
- [x] Updated `docs/development/ROADMAP.md` with a new Phase 3.5 and a reshaped Phase 5.
- [ ] Open `tasks/01-normalize-module.md` at start of Phase 3.5 (after Phase 3 / summarize is complete).
- [ ] Open `tasks/02-cluster-leiden-ward.md` at start of Phase 5.

## Session log

- 2026-05-12 (Claude Code, opus-4-7): Copied four reference files; ran first-pass scan; wrote findings + open questions for Eric.
- 2026-05-12 (Claude Code, opus-4-7): Eric resolved all four open questions. Wrote ADRs 0006 + 0007, scaffolded `normalize/` and reshaped `cluster/`, added core deps, updated ROADMAP. Task closed.
