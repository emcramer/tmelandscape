"""Pydantic config for the step-3.5 normalisation step.

The :class:`NormalizeConfig` is the frozen public contract between the driver
(:mod:`tmelandscape.normalize.normalize_ensemble`) and its callers (Python
API, CLI verb, MCP tool). It carries the user-chosen normalisation strategy
plus the per-strategy switches the reference oracle exposes.

Binding invariants (see ADR 0009 and ``tasks/04-normalize-implementation.md``):

* **No feature-drop default.** ``drop_columns`` defaults to an empty list.
  Users who want to remove statistic columns before normalisation must list
  them explicitly. Earlier iterations of the reference oracle hardcoded six
  cell-density columns; that choice was specific to one application of the
  method, not a property of the algorithm.
* **No hidden hardcoded strategy panel.** ``strategy`` is a ``Literal`` with
  exactly one member in v0.4.0 (``"within_timestep"``). The literal shape is
  set up to accept future algorithm additions in v0.4.x without a breaking
  change to the public surface.
* **Never collide with the raw value array.** ``output_variable`` is the name
  of the *new* variable to write into the output Zarr alongside the raw
  ``value`` array (which is copied verbatim so downstream consumers can
  compare raw vs normalised). ``"value"`` is therefore disallowed — it would
  shadow the preserved raw data.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class NormalizeConfig(BaseModel):
    """User-supplied configuration for ``normalize_ensemble``.

    Attributes
    ----------
    strategy
        Which normalisation algorithm to apply. Only ``"within_timestep"``
        exists in v0.4.0 (the reference algorithm from
        ``reference/00_abm_normalization.py``). The :class:`Literal` shape
        admits future strategy names without breaking the public contract.
    preserve_time_effect
        If ``True`` (default, reference behaviour), the per-timepoint,
        per-statistic mean computed from the raw input is re-added after
        standard scaling so the temporal trend survives into the embedding
        step.
    drop_columns
        Explicit list of ``statistic`` coord values to remove *before*
        normalisation. Defaults to ``[]`` per ADR 0009 — there is no
        built-in "always drop" list; users opt in by naming columns.
    fill_nan_with
        Scalar substituted for NaN values that emerge from the transform
        (e.g. a statistic with all-zero variance at a timepoint, or an
        all-NaN column). Default ``0.0`` matches the reference oracle.
    output_variable
        Name of the new data variable written into the output Zarr.
        Defaults to ``"value_normalized"``; must be a non-empty string and
        must not equal ``"value"`` (the raw data array, preserved verbatim
        in the output Zarr for raw-vs-normalised comparison).
    """

    model_config = ConfigDict(extra="forbid")

    strategy: Literal["within_timestep"] = Field(
        default="within_timestep",
        description=(
            "Normalisation algorithm. Only 'within_timestep' is implemented "
            "in v0.4.0; the Literal accepts future strategies without a "
            "breaking change."
        ),
    )
    preserve_time_effect: bool = Field(
        default=True,
        description=(
            "Re-add the pre-transform per-(timepoint, statistic) mean after "
            "standard scaling so the temporal trend survives into embedding. "
            "Default True (reference behaviour)."
        ),
    )
    drop_columns: list[str] = Field(
        default_factory=list,
        description=(
            "Explicit opt-in list of 'statistic' coord values to drop before "
            "normalisation. Default [] per ADR 0009 — no built-in drops."
        ),
    )
    fill_nan_with: float = Field(
        default=0.0,
        description=(
            "Scalar substituted for NaN values emerging from the transform. "
            "Default 0.0 (reference behaviour)."
        ),
    )
    output_variable: str = Field(
        default="value_normalized",
        min_length=1,
        description=(
            "Name of the new data variable in the output Zarr. Must be "
            "non-empty and must not equal 'value' (the raw array is copied "
            "verbatim under that name for raw-vs-normalised comparison)."
        ),
    )

    @field_validator("output_variable")
    @classmethod
    def _output_variable_not_value(cls, v: str) -> str:
        # The orchestrator preserves the input's raw ``value`` array verbatim
        # alongside the normalised output so downstream consumers can compare
        # raw vs normalised. Allowing ``output_variable="value"`` would shadow
        # (and effectively overwrite) the preserved raw data — fail fast at
        # config-construction time.
        if v == "value":
            raise ValueError(
                "output_variable must not equal 'value': the raw input array "
                "is preserved under that name in the output Zarr for "
                "raw-vs-normalised comparison. Choose a different name "
                "(default 'value_normalized')."
            )
        return v

    @field_validator("fill_nan_with")
    @classmethod
    def _fill_nan_with_must_be_finite(cls, v: float) -> float:
        # Pydantic accepts ``float('nan')`` for a ``float`` field, but
        # ``model_dump_json()`` then serialises NaN as the JSON literal
        # ``null`` and ``model_validate_json`` rejects null on reparse.
        # That silently breaks the lossless JSON round-trip invariant and
        # corrupts any persisted config. Reject NaN at validation time so
        # the failure surfaces at the API boundary rather than during a
        # later reload.
        if math.isnan(v):
            raise ValueError(
                "fill_nan_with=NaN breaks the lossless JSON round-trip "
                "(Pydantic serialises NaN as null and rejects null on "
                "reparse). Choose a finite sentinel (default 0.0)."
            )
        return v
