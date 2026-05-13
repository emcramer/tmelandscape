"""Pydantic configs for the spatial-statistic summarisation step.

The :class:`SummarizeConfig` is the public contract between the driver
(:mod:`tmelandscape.summarize.spatialtissuepy_driver`) and its callers. It
carries the user-chosen list of spatial statistics to compute per timepoint.

There is **no default statistics panel**. The user (or agent) must specify
which metrics to compute — the package neither restricts nor presupposes the
LCSS-paper panel or any other. The list of legal metric names is discovered
dynamically from ``spatialtissuepy``'s registry at validation time so the
contract automatically tracks upstream additions. See ADR 0009.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StatisticSpec(BaseModel):
    """One spatial-statistic to compute per timepoint.

    Attributes
    ----------
    name
        Metric name. Must match a metric registered in ``spatialtissuepy``'s
        global registry (queried at config-validation time).
    parameters
        Per-metric kwargs (e.g. ``radius`` for spatial metrics, ``type_a`` /
        ``type_b`` for pairwise colocalisation). Default ``{}`` falls back
        to the metric's own defaults.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)


class SummarizeConfig(BaseModel):
    """User-supplied configuration for ``summarize_ensemble``.

    Parameters
    ----------
    statistics
        Required list of :class:`StatisticSpec` (or plain string names, which
        are coerced into ``StatisticSpec(name=...)``). At least one entry.
    n_workers
        Number of Dask workers for ensemble aggregation. ``>= 1``.
    include_dead_cells
        Whether dead cells participate in the ``SpatialTissueData`` passed
        to each metric. Default ``False`` matches the LCSS convention but is
        otherwise neutral.
    rewrite_interaction_keys
        Whether to rewrite output keys of the shape
        ``interaction_<src>_<dst>`` to ``interaction_<src>|<dst>``. The ``|``
        delimiter disambiguates pair keys when cell-type names contain
        underscores (``M0_macrophage``, ``effector_T_cell``). Default
        ``True`` — turn off only if you need byte-for-byte compatibility
        with raw spatialtissuepy output.
    """

    statistics: list[StatisticSpec] = Field(
        ...,
        min_length=1,
        description=(
            "Required: the metrics to compute per timepoint. No defaults are "
            "supplied — call `tmelandscape.summarize.list_available_statistics()` "
            "to discover names, then pass them here."
        ),
    )
    n_workers: int = Field(default=1, ge=1)
    include_dead_cells: bool = False
    rewrite_interaction_keys: bool = True

    @field_validator("statistics", mode="before")
    @classmethod
    def _coerce_and_validate_statistics(cls, value: Any) -> list[StatisticSpec]:
        # Accept plain strings as shorthand for `StatisticSpec(name=..., parameters={})`.
        if not isinstance(value, list):
            raise ValueError("statistics must be a list")
        coerced: list[StatisticSpec] = []
        for item in value:
            if isinstance(item, str):
                coerced.append(StatisticSpec(name=item))
            elif isinstance(item, StatisticSpec):
                coerced.append(item)
            elif isinstance(item, dict):
                coerced.append(StatisticSpec.model_validate(item))
            else:
                raise ValueError(
                    f"statistics entries must be str, dict, or StatisticSpec; got {type(item)!r}"
                )

        # Validate metric names against spatialtissuepy's live registry. The
        # registry is populated by module-import side effects, so we import the
        # registering modules first. Lazy to keep `import tmelandscape` light.
        from tmelandscape.summarize.registry import (
            available_metric_names,
        )

        available = available_metric_names()
        unknown = [s.name for s in coerced if s.name not in available]
        if unknown:
            raise ValueError(
                f"Unknown statistic name(s): {unknown}. "
                f"Call tmelandscape.summarize.list_available_statistics() to "
                f"see the catalogue ({len(available)} metrics available)."
            )
        return coerced
