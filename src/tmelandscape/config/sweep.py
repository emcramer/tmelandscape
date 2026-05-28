"""Pydantic configs for the parameter sweep / sampling step.

These models are the frozen public contract between Stream A (this module),
the downstream sampling backends (``tmelandscape.sampling.lhs`` /
``tmelandscape.sampling.alternatives``), and the external step-2
(PhysiCell-running) agent that consumes the resulting ``SweepManifest``.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator


class ParameterSpec(BaseModel):
    """One ABM parameter to sweep over."""

    name: str = Field(
        ...,
        description="Parameter name. Free-form; e.g. a PhysiCell XML dotted path.",
    )
    low: float
    high: float
    scale: Literal["linear", "log10"] = "linear"

    @field_validator("high")
    @classmethod
    def _high_above_low(cls, v: float, info: ValidationInfo) -> float:
        if "low" in info.data and v <= info.data["low"]:
            raise ValueError("high must be strictly greater than low")
        return v

    @model_validator(mode="after")
    def _log10_bounds_positive(self) -> ParameterSpec:
        # log10 of a non-positive number is -inf / NaN and silently corrupts the
        # scaled samples downstream in `tmelandscape.sampling._scale`.
        if self.scale == "log10" and (self.low <= 0 or self.high <= 0):
            raise ValueError(
                f"scale='log10' requires low > 0 and high > 0; got low={self.low}, high={self.high}"
            )
        return self


class SAParams(BaseModel):
    """Simulated-annealing parameters forwarded to ``GraphColorizer.colorize``.

    Defaults are tuned for the ~250-2000 node graphs produced by typical TME
    source tissues; they converge in seconds to a minute on those scales.
    """

    initial_temp: float = 10.0
    final_temp: float = 0.01
    cooling_rate: float = 0.9997
    max_iterations: int = 60_000


class IcSourceOwnData(BaseModel):
    """Mode A — target statistics from a user-supplied tissue."""

    mode: Literal["own_data"] = "own_data"
    source_csv: str = Field(
        ...,
        description=(
            "Path to a typed-coordinate CSV with columns "
            "``x, y, z, radius, cell_type, is_boundary`` (the schema produced "
            "by ``tissue_simulator.TissueSection.export_to_csv``)."
        ),
    )


class IcSourceStructured(BaseModel):
    """Mode B — target statistics from a user-described structured tissue.

    The skill / agent realizes the description into a typed-coordinate CSV
    upstream (e.g. via PhysiCell ``place_initial_cells``); the wrapper sees the
    same shape as Mode A — just a typed CSV — and records the mode and the
    user's description for manifest provenance.
    """

    mode: Literal["structured"] = "structured"
    source_csv: str = Field(
        ...,
        description=(
            "Path to a typed-coordinate CSV with columns "
            "``x, y, z, radius, cell_type, is_boundary``. The agent generates "
            "this upstream from a user-supplied spatial description."
        ),
    )
    description: str = Field(
        default="",
        description=(
            "Free-text spatial-configuration description provided by the user "
            "upstream. Stored for manifest provenance; not interpreted here."
        ),
    )


IcSource = Annotated[
    IcSourceOwnData | IcSourceStructured,
    Field(discriminator="mode"),
]


class SweepConfig(BaseModel):
    """Top-level config for ``generate_sweep``."""

    parameters: list[ParameterSpec] = Field(..., min_length=1)
    n_parameter_samples: int = Field(
        ...,
        gt=0,
        description="N parameter combinations to draw.",
    )
    n_initial_conditions: int = Field(
        ...,
        gt=0,
        description="N replicate ICs per parameter combination.",
    )
    sampler: Literal["pyDOE3", "scipy-lhs", "scipy-sobol", "scipy-halton"] = "pyDOE3"
    seed: int = Field(
        ...,
        description="RNG seed. Drives both parameter sampling and IC replicate generation.",
    )
    ic_source: IcSource = Field(
        ...,
        description=(
            "Source of target statistics for IC generation. Discriminated by "
            "``mode``: ``own_data`` (user-supplied typed CSV) or "
            "``structured`` (agent-described structured tissue realized to a "
            "typed CSV upstream)."
        ),
    )
    ic_scaffold_strategy: Literal["uniform_random", "perturb_source"] = "uniform_random"
    ic_sa_params: SAParams = Field(default_factory=SAParams)
    ic_network_mode: Literal["contact", "radius"] = "radius"
    ic_network_radius_um: float | None = Field(
        default=None,
        description=(
            "Edge-cutoff distance in micrometres for ``ic_network_mode='radius'``. "
            "When None (default), resolved at call time to "
            "``2.5 * max(source cell radius)`` — less sensitive to scaffold-vs-"
            "source packing-density variation than ``contact`` mode."
        ),
    )
