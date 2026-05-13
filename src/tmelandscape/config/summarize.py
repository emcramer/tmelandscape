"""Pydantic config for the spatialtissuepy-driven summarisation step.

`SummarizeConfig` is the frozen public contract for Phase 3 (step 3 of the
pipeline). It is consumed by:

* ``tmelandscape.summarize.spatialtissuepy_driver.summarize_simulation``
  (Stream A) — per-simulation driver,
* ``tmelandscape.summarize.aggregate.build_ensemble_zarr`` (Stream B) —
  ensemble aggregator,
* ``tmelandscape.summarize.registry.compute_statistic`` (this stream) —
  the only module that knows how ``spatialtissuepy`` is organised.

The ``statistics`` list is validated at construction time against the
registry's ``KNOWN_STATISTICS`` set so callers learn about typos via a
``pydantic.ValidationError`` rather than a ``KeyError`` deep inside a
worker.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _default_statistics() -> list[str]:
    """Return the LCSS-paper default panel.

    Mirrors the panel listed in ``tasks/03-summarize-implementation.md``.
    Defined as a module-level helper rather than an inline ``lambda`` so the
    default is introspectable and reusable from tests.
    """
    return [
        # Cell-type composition
        "cell_counts",
        "cell_type_fractions",
        # Graph-based centrality (mean by cell type)
        "mean_degree_centrality_by_type",
        "mean_closeness_centrality_by_type",
        "mean_betweenness_centrality_by_type",
        # Cell-cell interactions
        "interaction_strength_matrix",
    ]


class SummarizeConfig(BaseModel):
    """Config for ``summarize_ensemble``. Frozen public contract.

    Parameters
    ----------
    statistics:
        Names of statistics to compute per timepoint. Each name must be in
        :data:`tmelandscape.summarize.registry.KNOWN_STATISTICS`. The default
        mirrors the LCSS paper's panel.
    graph_method:
        Cell-graph construction method passed through to
        ``spatialtissuepy.network.CellGraph.from_spatial_data``.
    graph_radius_um:
        Proximity / contact radius in micrometres. Used by the proximity
        graph and by all radius-based statistics (``interaction_strength_matrix``
        in particular). Must be strictly positive.
    n_workers:
        Number of Dask workers for ensemble aggregation. Must be ``>= 1``.
    include_dead_cells:
        Whether to include cells flagged as dead in the underlying PhysiCell
        output when building the ``SpatialTissueData``. Default ``False``
        mirrors the LCSS-paper convention.
    """

    statistics: list[str] = Field(
        default_factory=_default_statistics,
        description=(
            "StatisticsPanel keys to compute per timepoint. Default mirrors the LCSS paper's panel."
        ),
    )
    graph_method: Literal["proximity", "knn", "delaunay", "gabriel"] = "proximity"
    graph_radius_um: float = Field(
        default=30.0,
        gt=0.0,
        description=(
            "Radius in micrometres. Used (a) by graph construction when "
            "`graph_method='proximity'` (otherwise the graph builder may ignore it), "
            "AND (b) as the interaction-detection radius for `interaction_strength_matrix` "
            "regardless of `graph_method`. PhysiCell stores positions in micrometres; "
            "the value is passed through verbatim to spatialtissuepy as a unitless float."
        ),
    )
    n_workers: int = Field(
        default=1,
        ge=1,
        description="Dask workers for ensemble aggregation.",
    )
    include_dead_cells: bool = False

    @field_validator("statistics")
    @classmethod
    def _statistics_are_known(cls, value: list[str]) -> list[str]:
        # Lazy import to avoid a circular dependency: ``registry`` imports
        # ``SummarizeConfig`` for its ``compute_statistic`` type hint.
        from tmelandscape.summarize.registry import KNOWN_STATISTICS

        unknown = [name for name in value if name not in KNOWN_STATISTICS]
        if unknown:
            known_sorted = sorted(KNOWN_STATISTICS)
            raise ValueError(
                f"Unknown statistic name(s): {unknown}. Known statistics are: {known_sorted}."
            )
        return value
