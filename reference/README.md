# reference/ — read-only oracle scripts

This directory is **gitignored**. It contains read-only reference scripts copied from Eric's local machine, used as the numerical oracle for pipeline-step implementations.

**Agents must not edit these files.** Treat them as a frozen oracle. Numerical-agreement tests in `tests/unit/` and `tests/integration/` pin the package's outputs against the behaviour of these scripts on fixed inputs.

## Source

`/Users/cramere/OneDrive - Oregon Health & Science University/graduate/knowledgebase/00-projects/parameter-exploration/code/`

Per Eric, the authoritative scripts for the *landscape generation* steps (sampling → summarize → normalize → embed → cluster) are those whose filenames begin with `00_abm`, `01_abm`, or `02_abm`. Files numbered `03_abm` and beyond are downstream analysis (mapping, transition analysis, forecasting) and are **out of scope for tmelandscape v1**.

## Files copied (2026-05-12)

| File | Purpose | Pipeline step |
| --- | --- | --- |
| `00_abm_normalization.py` | Within-time-step normalization: per-step mean → power transform → z-score → re-add original mean. Filters out cell-density features. | Step 3.5 (normalization between summarize and embedding) |
| `01_abm_generate_embedding.py` | Sliding-window construction + kNN graph + UMAP + **Leiden community detection** + Ward hierarchical clustering on Leiden cluster means | Step 4 (embedding/window) + Step 5 (clustering) |
| `02_abm_state_space_analysis.marimo.py` | State-space analysis; clustering refinement, state-labeling, diagnostics | Step 5 (clustering) + downstream analysis |
| `utils.py` | Shared helpers: `window_trajectory_data`, `unnest_list`, `create_pmf`, `jensen_shannon_divergence`, `calculate_jsd_baseline`, `zscore_then_minmax_normalize`, `sliding_window_average`, `add_suffix_to_repeats`, `consistent_labels`, `majority_vote`, `enhance_legend_markers`, `get_today`, `ensure_directory` | All steps |

Sizes: 311 / 930 / 1261 / 295 lines respectively.

## Key findings from initial scan

1. **Reference scripts are marimo notebooks** (`.marimo.py`), not plain Python. Open question for Eric: do we keep that format in `reference/` (read-only oracle) or also extract plain-Python ports for unit testing?
2. **Clustering is a two-stage procedure**, not the single Ward step the LCSS paper describes:
   - **Stage 1:** kNN graph over the windowed feature space (sklearn `kneighbors_graph` + `igraph`), Leiden community detection (`leidenalg`).
   - **Stage 2:** Ward hierarchical clustering on the *means* of each Leiden community → ~6 final TME states.
3. **Window size = 50** (matches LCSS paper).
4. **JSD-based metrics** appear in the kNN-graph construction (`jensen_shannon_divergence`, `create_pmf`, `calculate_jsd_baseline` in `utils.py`).
5. **Normalization filters out density features** (`M0/M1/M2_macrophage_density`, `effector/exhausted_T_cell/malignant_epithelial_cell_density`). These should be excluded by default but configurable.
6. **Missing from current `pyproject.toml` deps:** `leidenalg`, `python-igraph` (the `igraph` package), `networkx`, `seaborn`, `umap-learn` (already in `viz`).

## How to refresh

If the upstream scripts change:

```bash
cp "/Users/cramere/OneDrive - Oregon Health & Science University/graduate/knowledgebase/00-projects/parameter-exploration/code/{00,01,02}_abm_*.py" reference/
```

After refreshing, re-run any numerical-agreement tests pinned against these scripts. If outputs diverge, write an ADR before changing tmelandscape to match the new behaviour.
