"""Pydantic configs for the parameter sweep / sampling step.

These models are the frozen public contract between Stream A (this module),
the downstream sampling backends (``tmelandscape.sampling.lhs`` /
``tmelandscape.sampling.alternatives``), and the external step-2
(PhysiCell-running) agent that consumes the resulting ``SweepManifest``.
"""

from __future__ import annotations

from typing import Literal

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
