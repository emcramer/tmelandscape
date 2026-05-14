# Decision: hand-roll Benjamini-Hochberg FDR for TNBC-6c (parameter-by-state)

- **Date:** 2026-05-14 (UTC)
- **Status:** Accepted
- **Owner / decider:** Stream C Implementer (Claude Code) for the Phase 6 orchestrator

## Context

`tmelandscape.viz.dynamics.plot_parameter_by_state` (TNBC-6c) annotates
the pairwise Mann-Whitney U tests with significance markers. The
manuscript uses a Benjamini-Hochberg false-discovery-rate correction
across the m pairs.

The Phase 6 task file (`tasks/07-visualisation-implementation.md`)
explicitly flagged this as a "Decision point":

> Pairwise Mann-Whitney U (`scipy.stats.mannwhitneyu`) with BH-FDR
> correction. **Decision point**: implement BH-FDR by hand (~10 LOC) or
> import `statsmodels.stats.multitest.multipletests`. statsmodels is in
> the viz extra per the task file footnote — pick one and write a
> decision-log entry explaining why.

A check of the live `pyproject.toml` shows that statsmodels is **not**
in the `viz` extra; the task-file footnote suggested adding it but did
not assert it had been added. The current `viz` extra is matplotlib +
umap-learn + plotly + seaborn.

## Options considered

### Option A — Hand-rolled Benjamini-Hochberg

- Pros:
  - **Zero new dependency.** Avoids adding statsmodels (a fairly heavy
    install — pulls in patsy, large stats compile units) for a 10-LOC
    procedure.
  - **Auditable.** The BH algorithm is short enough that a reader can
    verify correctness inline. Provenance into the figure stays
    self-contained in `dynamics.py`.
  - **Avoids touching pyproject.toml.** The implementer is forbidden by
    the Stream C contract from editing `pyproject.toml`; declaring the
    new dependency would have to wait for an orchestrator pass.
- Cons:
  - Slight maintenance burden — if a future contributor edits the BH
    block, they must re-derive correctness.
  - No tie to the canonical statsmodels test suite.

### Option B — `statsmodels.stats.multitest.multipletests(method='fdr_bh')`

- Pros:
  - Off-the-shelf, well-tested.
  - Future-proofs other corrections (Holm, Bonferroni) for the same
    helper.
- Cons:
  - Adds a third-party dependency that pulls in a lot of transitive
    code for one ~10-LOC calculation.
  - statsmodels was **not** in the viz extra at decision time; using it
    would require an orchestrator-level `pyproject.toml` edit that the
    Stream C contract prohibits.
  - Heavier import-time cost for a function called in a single figure.

## Decision

**Option A — hand-rolled.** The BH algorithm is:

```
1. Discard pairs whose Mann-Whitney p-value is NaN (degenerate sample).
2. Sort the remaining m p-values ascending.
3. q_i_raw = p_i * m / rank_i  (rank_i is 1-based after sort).
4. Enforce monotone non-decreasing q's by reverse cumulative-min.
5. Clip into [0, 1].
```

Ten lines in `_pairwise_mannwhitney_bh` of `src/tmelandscape/viz/dynamics.py`.

Reasoning:

- The Stream C contract forbids touching `pyproject.toml`; declaring
  `statsmodels` as a new dependency is therefore out of scope for this
  implementer wave.
- The procedure is short and well-known; the marginal cost of a heavy
  external dependency is not justified for one figure.
- If a future ticket wants to add Holm / Bonferroni / Storey-Tibshirani
  alternatives, the orchestrator can swap in statsmodels at that point
  and migrate the helper without breaking the figure's public API.

## Consequences

- **Code change applied:** `_pairwise_mannwhitney_bh` lives in
  `src/tmelandscape/viz/dynamics.py` as a module-private helper. No
  public re-export.
- **Downstream impact:** none on the public API. Tests in
  `tests/unit/test_viz_dynamics.py` exercise the helper indirectly via
  the smoke / save-round-trip tests of `plot_parameter_by_state`.
- **New work this implies:** if a reviewer in Wave 2 wants explicit
  unit tests on the BH-FDR helper itself, those can land at module-
  private import without breaking the figure API.
- **Reversibility:** trivial. Replace the helper body with a thin
  wrapper around `statsmodels.stats.multitest.multipletests` and add
  the dependency in a follow-up.

## References

- Task file: `tasks/07-visualisation-implementation.md` (Stream C —
  decision point on BH-FDR)
- ADR 0009: `docs/adr/0009-no-hardcoded-statistics-panel.md`
- Code: `src/tmelandscape/viz/dynamics.py::_pairwise_mannwhitney_bh`
- Benjamini & Hochberg (1995), J. Roy. Stat. Soc. B 57(1):289-300.
