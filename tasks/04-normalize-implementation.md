# 04 — Phase 3.5 normalisation implementation

- **slug:** 04-normalize-implementation
- **status:** done (2026-05-13)
- **owner:** Claude Code orchestrator + 3 buddy-pair (Implementer / Reviewer) teams
- **opened:** 2026-05-13
- **closed:** 2026-05-13
- **roadmap link:** Phase 3.5 — Step 3.5 normalisation (v0.4.0)

## Context

Implement step 3.5 of the pipeline: within-time-step normalisation of the ensemble Zarr produced by step 3. Reference oracle is `reference/00_abm_normalization.py` (already in repo).

**Binding invariants** (from ADRs 0006 + 0009 + the project owner's directives):

1. **Never overwrite the raw ensemble.** The input Zarr is read-only. Normalisation always writes a *new* Zarr file at a user-supplied path. Tests must verify byte-equality of the input store before/after a normalise run.
2. **No feature-drop default.** `NormalizeConfig.drop_columns` defaults to `[]`. Users who want to drop columns must list them explicitly.
3. **No hidden hardcoded behaviour.** Strategy names live in a small literal type; `NormalizeConfig.strategy` defaults to `"within_timestep"` (the reference algorithm) — that's a reasonable default for the only currently-implemented strategy, not a panel of "blessed" choices.

Reference algorithm summary (from `reference/00_abm_normalization.py`):

For each `(timepoint,)` slab of the `(n_sim, n_stat)` value matrix:

1. Compute per-statistic mean across simulations (the *time-step mean*, denoted `m_t`).
2. For each statistic column with non-zero std: apply `scipy.stats.yeojohnson` (returns `(transformed, lmbda)`; we want `[0]`).
3. Apply `scipy.stats.zscore` per column (standard scaling). Columns with zero std pass through.
4. NaN values that arise (e.g. a fraction of a cell type that is absent for the whole timestep) are filled with 0.
5. Re-add `m_t` to each column to preserve the temporal trend (`preserve_time_effect=True` default).

This step makes the embedding step see "normalised-around-the-trend" signal rather than zero-mean noise.

## Public API (frozen — every Implementer must match these signatures exactly)

### Config — `tmelandscape.config.normalize`

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class NormalizeConfig(BaseModel):
    """User-supplied configuration for `normalize_ensemble`."""

    model_config = ConfigDict(extra="forbid")

    strategy: Literal["within_timestep"] = "within_timestep"
    preserve_time_effect: bool = True
    drop_columns: list[str] = Field(default_factory=list)
    fill_nan_with: float = 0.0
    output_variable: str = "value_normalized"
```

- `strategy`: which algorithm to apply. Only `"within_timestep"` exists in v0.4.0; the Literal is set up to accept future additions without a breaking change.
- `preserve_time_effect`: re-add per-step means (the reference behaviour).
- `drop_columns`: explicit list of `statistic` coord values to remove **before** normalisation. Default `[]` per ADR 0009.
- `fill_nan_with`: scalar to substitute for NaN after the transform; the reference uses `0.0`.
- `output_variable`: name of the new variable to write in the output Zarr.

### Algorithm — `tmelandscape.normalize.within_timestep`

```python
import numpy as np

def normalize_within_timestep(
    value: np.ndarray,
    *,
    preserve_time_effect: bool = True,
    fill_nan_with: float = 0.0,
) -> np.ndarray:
    """Apply per-time-step Yeo-Johnson + z-score, optionally re-adding the
    pre-transform per-step mean.

    Parameters
    ----------
    value
        ``(n_sim, n_timepoint, n_stat)`` float64 array. NaN entries (ragged
        timepoints, all-NaN columns) are tolerated.
    preserve_time_effect
        If True, the per-timepoint, per-statistic mean computed from the raw
        input is added back after standard scaling so the temporal trend
        survives into the embedding step. Default True (reference behaviour).
    fill_nan_with
        Scalar substituted for NaN values that emerge from the transform
        (e.g. a statistic with all-zero variance at a timepoint after the
        power transform). Default 0.0 (reference behaviour).

    Returns
    -------
    np.ndarray
        Same-shape float64 array. Deterministic for the same input.
    """
```

Implementation notes:

- For each `(t, s)` slab, work in 1D over the `n_sim` axis.
- Use `scipy.stats.yeojohnson` for the power transform. Columns with effective zero std (after masking NaN) pass through unchanged.
- Use `scipy.stats.zscore` with `nan_policy='omit'` if applicable, then re-NaN appropriately.
- The function must be a pure function — no I/O, no global RNG, no `np.random.*`.

### Alternatives — `tmelandscape.normalize.alternatives`

Stub for now. Add one function `normalize_identity(value, ...)` that returns its input unchanged, to confirm the "swap strategies" path works. This anchors the registry pattern for future v0.4.x algorithm additions.

```python
def normalize_identity(value: np.ndarray, **_: object) -> np.ndarray:
    """Passthrough strategy. Useful as a baseline / for debugging."""
```

### Zarr orchestrator — `tmelandscape.normalize.__init__`

```python
from pathlib import Path
from tmelandscape.config.normalize import NormalizeConfig

def normalize_ensemble(
    input_zarr: str | Path,
    output_zarr: str | Path,
    *,
    config: NormalizeConfig,
) -> Path:
    """Read an ensemble Zarr produced by step 3, apply the chosen
    normalisation, and write a NEW Zarr at ``output_zarr``.

    The input store is read-only — never overwritten or mutated. The
    function fails fast if ``output_zarr`` already exists (callers can
    delete it first if intentional overwrites are desired).

    Returns the absolute path of the written Zarr store.
    """
```

The output Zarr's shape and coords mirror the input's, except:

- The `statistic` coord drops any names listed in `config.drop_columns`.
- The data variable is named `config.output_variable` (default `value_normalized`); the input's `value` array name is preserved alongside it (copied verbatim) so downstream consumers can compare raw vs normalised.
- `.zattrs` gain `normalize_config` (JSON-serialised NormalizeConfig), `source_manifest_hash` (copied from input), `created_at_utc`, and `tmelandscape_version`.

## Stream allocation (3 buddy pairs)

### Pair A — algorithm

**Implementer A1** writes:

- `src/tmelandscape/normalize/within_timestep.py` — `normalize_within_timestep` per the contract.
- `tests/unit/test_normalize_within_timestep.py` — covers:
  - Same seed / same input → same output (deterministic).
  - Output shape == input shape.
  - With `preserve_time_effect=True`, the per-(timepoint, statistic) mean of the output ≈ per-(timepoint, statistic) mean of the input (within numeric tolerance).
  - With `preserve_time_effect=False`, the per-(timepoint, statistic) mean of the output ≈ 0 (within numeric tolerance).
  - With `preserve_time_effect=False`, per-(timepoint, statistic) std of the output ≈ 1 (within tolerance) for non-degenerate inputs.
  - Zero-std column passes through unchanged.
  - All-NaN column comes out as the configured `fill_nan_with` value (or NaN if user passes NaN as fill).
  - Mixed NaN: a few NaN entries in an otherwise-valid column are filled per `fill_nan_with`.

**Reviewer A2** audits A1's work read-only:

- Does the algorithm match the reference oracle `reference/00_abm_normalization.py` line-by-line? Note any divergences (e.g. `scipy.stats.yeojohnson` vs the manuscript's `PowerTransformer`).
- NaN handling correctness: does zscore/yeojohnson behave consistently when input has NaN?
- Zero-variance edge case: divide-by-zero in zscore?
- Per-stat axis: is the function processing each `statistic` column independently per timepoint (not mixing columns)?
- Property test for: linearity of `preserve_time_effect` (mean shift property).
- House-style: pure function, no I/O, no global RNG, mypy strict-clean.

### Pair B — Zarr orchestrator

**Implementer B1** writes:

- `src/tmelandscape/normalize/__init__.py` — `normalize_ensemble`.
- `tests/unit/test_normalize_ensemble.py` — covers:
  - Round trip: build a tiny `(n_sim=2, n_tp=3, n_stat=4)` Zarr in tmp_path; call `normalize_ensemble`; reopen output via `xarray.open_zarr` and confirm dims/coords/values.
  - **Input immutability**: hash every file in the input Zarr store before & after — must match byte-for-byte.
  - Output file does not pre-exist precondition (refuses to overwrite — `FileExistsError` raised cleanly).
  - `drop_columns` actually removes those entries from the `statistic` coord and from the value array.
  - Provenance .zattrs present: `normalize_config`, `source_manifest_hash`, `created_at_utc`, `tmelandscape_version`.
  - Both the raw `value` array and the new `value_normalized` array are present in the output.
  - The `simulation` and `timepoint` coords (and their per-simulation aligned `parameter_*`, `ic_id`, etc.) survive unchanged.
  - With `strategy="within_timestep"` + `preserve_time_effect=True`, the output's per-(timepoint, statistic) mean matches the input's (within tolerance).

**Reviewer B2** audits B1's work read-only:

- Input-immutability proof: re-run the byte-hash assertion against a non-trivial fixture.
- Coord alignment: do the per-simulation `parameter_*` coords still align with the right rows after the drop_columns filter?
- NaN propagation: does the output preserve NaN where the input was NaN (modulo the `fill_nan_with` substitution)?
- `output_zarr.exists()` check: race condition? What about a Zarr v3 directory that was partially written and aborted?
- Provenance hash: is `source_manifest_hash` actually present in the input — if not, the orchestrator should still work (with that field absent).
- `value_normalized` vs `value` naming: are both stored, and are downstream consumers able to disambiguate?

### Pair C — config + alternatives

**Implementer C1** writes:

- `src/tmelandscape/config/normalize.py` — `NormalizeConfig`.
- `src/tmelandscape/normalize/alternatives.py` — at least `normalize_identity`.
- `tests/unit/test_normalize_config.py` — covers:
  - Default construction succeeds with the documented defaults.
  - `extra="forbid"` rejects unknown kwargs.
  - `drop_columns` defaults to `[]` and accepts arbitrary lists.
  - `output_variable` is a non-empty string.
  - JSON round-trip via `model_dump_json()` / `model_validate_json()`.
  - Strategy literal rejects unknown values (e.g. `"foo"`).
- `tests/unit/test_normalize_alternatives.py` — `normalize_identity` is a true passthrough (output equals input).

**Reviewer C2** audits C1's work read-only:

- ADR alignment: does `drop_columns` truly default to `[]`? Does the config say "explicit opt-in" in the docstring?
- `output_variable` validation: enforce `min_length=1`? Disallow `value` (collides with raw)? Latter is a design call — note it.
- Pydantic style match against `SummarizeConfig` and `SweepConfig`: `model_config = ConfigDict(extra="forbid")`, `field_validator` placement, descriptions.
- Test coverage: any branch in the Pydantic model not exercised?

## Integration (orchestrator, after all three pairs return)

After Implementer + Reviewer for all three streams report:

1. Apply review findings (orchestrator).
2. Write CLI: `src/tmelandscape/cli/normalize.py` (verb `tmelandscape normalize`).
3. Write CLI for strategy discovery: `tmelandscape normalize strategies list` (mirrors `tmelandscape statistics list`).
4. Write MCP tools: `normalize_ensemble_tool` and `list_normalize_strategies_tool` in `src/tmelandscape/mcp/tools.py`; register on the MCP server.
5. Write `tests/integration/test_normalize_end_to_end.py` — Python API + CLI + MCP all produce equivalent output Zarrs (byte-equal hashes of the value arrays).
6. Fill out `docs/concepts/normalize.md` (new page; nav update in `mkdocs.yml`).
7. Update STATUS.md + ROADMAP.md.
8. Verify all 107+ existing tests still pass, plus the new normalize tests.
9. Tag `v0.4.0` if everything is green; commit; push.

## House-style invariants (binding on every Implementer)

- Pydantic configs for public surfaces.
- mypy strict-clean on every new file.
- No global numpy random.
- No silent network I/O.
- Tests run in <2s each (mark `@pytest.mark.slow` otherwise).
- No modifications to `pyproject.toml` (orchestrator only).
- Existing public API surfaces (sampling, summarize, CLI verbs, MCP tools) must remain green.

## Buddy-pair workflow (mirrors Phase 3)

Round 1 (parallel): Implementers A1 / B1 / C1 each produce a report listing files created, test counts, and any contract deviations.

Round 2 (parallel): Reviewers A2 / B2 / C2 each audit their partner's diff read-only. **Reviewers may NOT edit code.** Each emits a findings report tagged BUG / RISK / SMELL / OK + a "verdict" (safe to integrate / minor fixes / send back).

Round 3 (orchestrator):

- Apply SMELL fixes directly.
- For BUG / RISK items, either fix directly or `SendMessage` back to the Implementer with a targeted prompt.
- Integrate per the list above.

## Session log

- 2026-05-13 (Claude Code orchestrator): Task file frozen with API contracts; reference oracle re-read for algorithm confirmation; ready to spawn Round 1 Implementers.
