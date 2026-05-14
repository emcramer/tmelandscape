"""Pydantic config for the step-4 sliding-window embedding step.

The :class:`EmbeddingConfig` is the frozen public contract between the driver
(:mod:`tmelandscape.embedding.embed_ensemble`) and its callers (Python API,
CLI verb, MCP tool). It carries the user-chosen embedding strategy plus the
per-strategy switches the reference oracle exposes.

Binding invariants (see ADR 0009 and ``tasks/05-embedding-implementation.md``):

* **No window-size default.** ``window_size`` is required. The reference uses
  50; the LCSS paper notes ``W in {30, 50, 80}``. There is no defensible
  "package default" — the user picks ``W`` explicitly.
* **No feature-drop default.** ``drop_statistics`` defaults to an empty list,
  matching the Phase 3.5 ``NormalizeConfig.drop_columns`` invariant.
* **No hidden hardcoded strategy panel.** ``strategy`` is a ``Literal`` with
  exactly one member in v0.5.0 (``"sliding_window"``). The literal shape is
  set up to admit future algorithm additions in v0.5.x without breaking the
  public surface.
* **Never collide on the output Dataset's data_vars dict.** Three named
  variables -- ``source_variable`` (read), ``output_variable`` (the flattened
  embedding), and ``averages_variable`` (the per-window per-statistic mean) --
  share the output Dataset's namespace. Any pairwise collision would silently
  shadow data, so all three are required to be distinct at config-construction
  time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EmbeddingConfig(BaseModel):
    """User-supplied configuration for ``embed_ensemble``.

    Attributes
    ----------
    strategy
        Which embedding algorithm to apply. Only ``"sliding_window"`` exists
        in v0.5.0 (the reference algorithm from
        ``reference/utils.py::window_trajectory_data``). The :class:`Literal`
        shape admits future strategy names without breaking the public
        contract.
    window_size
        **Required.** Length of the sliding window in timepoints. Must be
        ``>= 1``. The reference oracle uses 50; the LCSS paper says
        ``W in {30, 50, 80}``. The package supplies no default — the user
        must choose ``W`` explicitly.
    step_size
        Number of timepoints between consecutive window starts. Must be
        ``>= 1``. Default ``1`` matches the reference oracle.
    source_variable
        Name of the data variable in the input Zarr that carries the time
        series to be windowed. Defaults to ``"value_normalized"`` (the
        Phase 3.5 output) but any non-empty name is accepted.
    output_variable
        Name of the flattened-window data variable in the output Zarr.
        Defaults to ``"embedding"``. Must differ from both
        ``source_variable`` and ``averages_variable`` (see class docstring).
    averages_variable
        Name of the per-window per-statistic means data variable in the
        output Zarr. Defaults to ``"window_averages"``. Must differ from
        both ``source_variable`` and ``output_variable``.
    drop_statistics
        Explicit list of ``statistic`` coord values to remove *before*
        windowing. Defaults to ``[]`` per ADR 0009 — there is no built-in
        "always drop" list; users opt in by naming statistics.
    """

    model_config = ConfigDict(extra="forbid")

    strategy: Literal["sliding_window"] = Field(
        default="sliding_window",
        description=(
            "Embedding algorithm. Only 'sliding_window' is implemented in "
            "v0.5.0; the Literal accepts future strategies without a "
            "breaking change."
        ),
    )
    window_size: int = Field(
        ...,
        ge=1,
        description=(
            "Required: length of the sliding window in timepoints (>= 1). "
            "Reference uses 50; LCSS paper says W in {30, 50, 80}. No "
            "package default — the user picks W explicitly."
        ),
    )
    step_size: int = Field(
        default=1,
        ge=1,
        description=(
            "Number of timepoints between consecutive window starts (>= 1). "
            "Default 1 matches the reference oracle."
        ),
    )
    source_variable: str = Field(
        default="value_normalized",
        min_length=1,
        description=(
            "Name of the input Zarr data variable carrying the time series. "
            "Defaults to 'value_normalized' (the Phase 3.5 output) but "
            "any non-empty name is accepted."
        ),
    )
    output_variable: str = Field(
        default="embedding",
        min_length=1,
        description=(
            "Name of the flattened-window data variable in the output Zarr. "
            "Must differ from source_variable and averages_variable to "
            "avoid shadowing on dataset write."
        ),
    )
    averages_variable: str = Field(
        default="window_averages",
        min_length=1,
        description=(
            "Name of the per-window per-statistic means data variable in "
            "the output Zarr. Must differ from source_variable and "
            "output_variable to avoid shadowing on dataset write."
        ),
    )
    drop_statistics: list[str] = Field(
        default_factory=list,
        description=(
            "Explicit opt-in list of 'statistic' coord values to drop "
            "before windowing. Default [] per ADR 0009 — no built-in drops."
        ),
    )

    @model_validator(mode="after")
    def _variable_names_must_be_distinct(self) -> EmbeddingConfig:
        # All three variable names share the output Dataset's data_vars dict.
        # A collision would silently clobber one entry with another on write,
        # so reject any pairwise overlap at config-construction time. Failing
        # fast here is the defence-in-depth complement to the orchestrator's
        # own pre-write check.
        if self.output_variable == self.source_variable:
            raise ValueError(
                "output_variable must not equal source_variable "
                f"(both are {self.source_variable!r}): writing the embedding "
                "under the source's name would shadow the input array in "
                "the output Dataset. Choose a different output_variable "
                "(default 'embedding')."
            )
        if self.averages_variable == self.source_variable:
            raise ValueError(
                "averages_variable must not equal source_variable "
                f"(both are {self.source_variable!r}): writing the per-window "
                "means under the source's name would shadow the input array "
                "in the output Dataset. Choose a different averages_variable "
                "(default 'window_averages')."
            )
        if self.output_variable == self.averages_variable:
            raise ValueError(
                "output_variable must not equal averages_variable "
                f"(both are {self.output_variable!r}): the two arrays share "
                "the output Dataset's data_vars dict and would clobber each "
                "other. Choose distinct names (defaults are 'embedding' and "
                "'window_averages')."
            )
        return self
