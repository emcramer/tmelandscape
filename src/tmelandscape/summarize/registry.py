"""Registry of per-timepoint statistics callable from ``SummarizeConfig``.

This module is the **only** place in ``tmelandscape`` that knows how
``spatialtissuepy`` is organised. The driver (``spatialtissuepy_driver``) and
the aggregator (``aggregate``) only ever call :func:`compute_statistic`.

Design notes
------------
* The set of legal statistic names is exposed via :data:`KNOWN_STATISTICS`
  so :class:`tmelandscape.config.summarize.SummarizeConfig` can validate
  user-supplied names *at config-construction time* (i.e. before any
  expensive work).
* All ``spatialtissuepy`` imports happen lazily inside
  :func:`compute_statistic`. If the upstream package is missing or partially
  broken, the user gets a clear ``ImportError`` at call time rather than
  losing the ability to import this module entirely.
* :func:`compute_statistic` consumes a *prebuilt* ``CellGraph`` rather than
  building one itself. Graph construction is the driver's job (one graph per
  timepoint, reused across all graph-based statistics).
* Every statistic returns a ``dict[str, float]``. Matrix-valued statistics
  (e.g. ``interaction_strength_matrix``) are flattened into one key per pair
  using a deterministic ``<stat>_<src>_<dst>`` naming scheme; the keys
  produced for a given statistic name are *not* themselves listed in
  :data:`KNOWN_STATISTICS` (those are *input* names, not *output* names).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tmelandscape.config.summarize import SummarizeConfig


# Frozen set of statistic names users are allowed to put in
# ``SummarizeConfig.statistics``. Keep this in sync with the dispatch table
# in :func:`compute_statistic`.
KNOWN_STATISTICS: frozenset[str] = frozenset(
    {
        # Cell-type composition (population-level, no graph required)
        "cell_counts",
        "cell_type_fractions",
        # Graph-based centrality (mean by cell type)
        "mean_degree_centrality_by_type",
        "mean_closeness_centrality_by_type",
        "mean_betweenness_centrality_by_type",
        # Cell-cell interaction matrix
        "interaction_strength_matrix",
    }
)


def _to_float(value: Any) -> float:
    """Coerce a numeric value to ``float`` without surprises.

    ``spatialtissuepy`` returns ``numpy`` scalars for several statistics;
    downstream code (Zarr, pandas) prefers Python floats. ``NaN`` is
    preserved.
    """
    return float(value)


def _compute_cell_counts(*, spatial_data: Any) -> dict[str, float]:
    from spatialtissuepy.summary.population import cell_counts

    return {key: _to_float(val) for key, val in cell_counts(spatial_data).items()}


def _compute_cell_type_fractions(*, spatial_data: Any) -> dict[str, float]:
    # ``cell_type_fractions`` is the LCSS-paper name; upstream calls it
    # ``cell_proportions`` and emits keys like ``prop_<type>``. We rename the
    # output keys to ``fraction_<type>`` so the output schema matches the
    # user-facing statistic name.
    from spatialtissuepy.summary.population import cell_proportions

    raw = cell_proportions(spatial_data)
    out: dict[str, float] = {}
    for key, val in raw.items():
        new_key = ("fraction_" + key[len("prop_") :]) if key.startswith("prop_") else key
        out[new_key] = _to_float(val)
    return out


def _compute_mean_centrality_by_type(
    *,
    graph: Any,
    metric: str,
    out_prefix: str,
) -> dict[str, float]:
    from spatialtissuepy.network.centrality import mean_centrality_by_type

    stats: dict[str, float] = mean_centrality_by_type(graph, metric=metric)
    return {f"{out_prefix}_{cell_type}": _to_float(val) for cell_type, val in stats.items()}


def _compute_interaction_strength_matrix(
    *,
    spatial_data: Any,
    radius: float,
) -> dict[str, float]:
    # Upstream is a coords-based metric: it builds its own KDTree against
    # `radius` and ignores any prebuilt graph (i.e. ignores
    # ``SummarizeConfig.graph_method``). Upstream output keys look like
    # ``interaction_{type_a}_{type_b}``; cell type names often contain
    # underscores (``M0_macrophage``, ``effector_T_cell``), making the key
    # ambiguous when split. We recover ``(type_a, type_b)`` from the same
    # iteration order upstream uses (upper triangle of
    # ``spatial_data.cell_types_unique``) and rekey with a ``|`` separator
    # which no cell type name will ever contain.
    from spatialtissuepy.summary.neighborhood import interaction_strength_matrix

    raw = interaction_strength_matrix(spatial_data, radius=radius)
    unique_types = list(spatial_data.cell_types_unique)
    out: dict[str, float] = {}
    for i, type_a in enumerate(unique_types):
        for type_b in unique_types[i:]:
            raw_key = f"interaction_{type_a}_{type_b}"
            new_key = f"interaction_{type_a}|{type_b}"
            if raw_key in raw:
                out[new_key] = _to_float(raw[raw_key])
    return out


# Internal dispatch table. Each entry is a callable that takes the keyword
# arguments ``spatial_data``, ``graph``, ``config`` and returns
# ``dict[str, float]``. We use a small adapter layer (above) so the entries
# stay one-line and easy to audit.
_Dispatch = Callable[..., dict[str, float]]


def _build_dispatch() -> dict[str, _Dispatch]:
    """Return the name -> handler dispatch table.

    Defined as a function (rather than a module-level dict) so the inner
    handlers can close over ``compute_statistic``'s call-site arguments via
    keyword forwarding without needing to import ``spatialtissuepy`` at
    module load time.
    """

    def cell_counts_handler(
        *, spatial_data: Any, graph: Any, config: SummarizeConfig
    ) -> dict[str, float]:
        del graph, config  # unused
        return _compute_cell_counts(spatial_data=spatial_data)

    def cell_type_fractions_handler(
        *, spatial_data: Any, graph: Any, config: SummarizeConfig
    ) -> dict[str, float]:
        del graph, config  # unused
        return _compute_cell_type_fractions(spatial_data=spatial_data)

    def mean_degree_handler(
        *, spatial_data: Any, graph: Any, config: SummarizeConfig
    ) -> dict[str, float]:
        del spatial_data, config  # unused
        return _compute_mean_centrality_by_type(
            graph=graph, metric="degree", out_prefix="degree_centrality"
        )

    def mean_closeness_handler(
        *, spatial_data: Any, graph: Any, config: SummarizeConfig
    ) -> dict[str, float]:
        del spatial_data, config  # unused
        return _compute_mean_centrality_by_type(
            graph=graph, metric="closeness", out_prefix="closeness_centrality"
        )

    def mean_betweenness_handler(
        *, spatial_data: Any, graph: Any, config: SummarizeConfig
    ) -> dict[str, float]:
        del spatial_data, config  # unused
        return _compute_mean_centrality_by_type(
            graph=graph, metric="betweenness", out_prefix="betweenness_centrality"
        )

    def interaction_matrix_handler(
        *, spatial_data: Any, graph: Any, config: SummarizeConfig
    ) -> dict[str, float]:
        del graph  # unused; this is a coords-based metric
        return _compute_interaction_strength_matrix(
            spatial_data=spatial_data,
            radius=config.graph_radius_um,
        )

    return {
        "cell_counts": cell_counts_handler,
        "cell_type_fractions": cell_type_fractions_handler,
        "mean_degree_centrality_by_type": mean_degree_handler,
        "mean_closeness_centrality_by_type": mean_closeness_handler,
        "mean_betweenness_centrality_by_type": mean_betweenness_handler,
        "interaction_strength_matrix": interaction_matrix_handler,
    }


def compute_statistic(
    name: str,
    *,
    spatial_data: Any,
    graph: Any,
    config: SummarizeConfig,
) -> dict[str, float]:
    """Compute a single named statistic for one timepoint.

    Parameters
    ----------
    name:
        One of :data:`KNOWN_STATISTICS`. Unknown names raise ``KeyError``.
    spatial_data:
        A ``spatialtissuepy.core.spatial_data.SpatialTissueData`` instance
        for the timepoint. Typed as ``Any`` to keep this module importable
        even if ``spatialtissuepy`` is unavailable.
    graph:
        A prebuilt ``spatialtissuepy.network.CellGraph`` for the same
        timepoint. Construction (which depends on ``config.graph_method``
        and ``config.graph_radius_um``) is the *driver's* responsibility so
        a single graph can be reused across all graph-based statistics.
    config:
        The :class:`SummarizeConfig` driving this run. Used by radius-based
        statistics (e.g. ``interaction_strength_matrix``).

    Returns
    -------
    dict[str, float]
        Output-statistic name -> scalar value. Matrix-valued statistics are
        flattened (e.g. ``interaction_strength_matrix`` yields keys like
        ``interaction_tumor_effector_T_cell``).

    Raises
    ------
    KeyError
        If ``name`` is not in :data:`KNOWN_STATISTICS`. Callers that build
        ``SummarizeConfig`` via Pydantic will not hit this in practice
        because the config-level validator rejects unknown names first.
    ImportError
        If the relevant ``spatialtissuepy`` submodule is missing or broken.
        The error message identifies the failing statistic so users can
        triage missing optional extras.
    """
    dispatch = _build_dispatch()
    if name not in dispatch:
        raise KeyError(
            f"Unknown statistic name {name!r}. Known statistics: {sorted(KNOWN_STATISTICS)}."
        )
    try:
        return dispatch[name](spatial_data=spatial_data, graph=graph, config=config)
    except ImportError as exc:  # pragma: no cover - surfaced verbatim
        raise ImportError(
            f"Failed to import spatialtissuepy submodule required by statistic "
            f"{name!r}: {exc}. Install/repair spatialtissuepy or drop this "
            f"statistic from SummarizeConfig.statistics."
        ) from exc
