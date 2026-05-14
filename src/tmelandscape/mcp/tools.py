"""MCP tools that mirror the public :mod:`tmelandscape` API one-to-one.

Each function here is wrapped as an MCP tool in :mod:`tmelandscape.mcp.server`.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tmelandscape.cluster import cluster_ensemble
from tmelandscape.config.cluster import ClusterConfig
from tmelandscape.config.embedding import EmbeddingConfig
from tmelandscape.config.normalize import NormalizeConfig
from tmelandscape.config.summarize import SummarizeConfig
from tmelandscape.config.sweep import SweepConfig
from tmelandscape.embedding import embed_ensemble
from tmelandscape.normalize import normalize_ensemble
from tmelandscape.sampling import generate_sweep
from tmelandscape.sampling.manifest import SweepManifest
from tmelandscape.summarize import summarize_ensemble
from tmelandscape.summarize.registry import (
    describe_metric,
    list_available_statistics,
)
from tmelandscape.viz.dynamics import (
    plot_attractor_basins,
    plot_parameter_by_state,
    plot_phase_space_vector_field,
)
from tmelandscape.viz.embedding import (
    fit_umap,
    plot_feature_umap,
    plot_state_umap,
    plot_state_umap_with_vector_field,
    plot_time_umap,
    plot_trajectory_umap,
)
from tmelandscape.viz.model_schematic import (
    CellType,
    Interaction,
    plot_model_schematic,
)
from tmelandscape.viz.trajectories import (
    plot_state_feature_clustermap,
    plot_trajectory_clustergram,
)


def generate_sweep_tool(
    config: dict[str, Any],
    *,
    initial_conditions_dir: str,
    manifest_out: str,
    target_n_cells: int = 500,
    similarity_tolerance: float = 0.10,
) -> dict[str, Any]:
    """Generate a parameter-sweep manifest (step 1 of the pipeline).

    Parameters
    ----------
    config
        Serialised :class:`tmelandscape.config.sweep.SweepConfig` (JSON-like dict).
    initial_conditions_dir
        Directory to write initial-condition CSVs into. Created if missing.
    manifest_out
        Output manifest stem; ``.json`` and ``.parquet`` siblings are written.
    target_n_cells
        Soft target for cell count per replicate.
    similarity_tolerance
        Per-metric divergence tolerance between replicates (default 0.10 = 10%).

    Returns
    -------
    dict
        Summary including absolute paths of the written artefacts and row counts.
    """
    sweep_cfg = SweepConfig.model_validate(config)
    manifest = generate_sweep(
        sweep_cfg,
        initial_conditions_dir=initial_conditions_dir,
        target_n_cells=target_n_cells,
        similarity_tolerance=similarity_tolerance,
    )
    manifest.save(manifest_out)
    return {
        "manifest_json": str(Path(f"{manifest_out}.json").resolve()),
        "manifest_parquet": str(Path(f"{manifest_out}.parquet").resolve()),
        "initial_conditions_dir": manifest.initial_conditions_dir,
        "n_rows": len(manifest.rows),
        "n_parameter_combinations": sweep_cfg.n_parameter_samples,
        "n_initial_conditions": sweep_cfg.n_initial_conditions,
    }


def summarize_ensemble_tool(
    manifest_path: str,
    *,
    physicell_root: str,
    output_zarr: str,
    summarize_config: dict[str, Any],
    chunk_simulations: int = 32,
    chunk_timepoints: int = -1,
    chunk_statistics: int = -1,
) -> dict[str, Any]:
    """Run step 3: spatialtissuepy summarisation + ensemble Zarr aggregation.

    Parameters
    ----------
    manifest_path
        Path to a SweepManifest JSON (the artefact emitted by ``generate_sweep``).
    physicell_root
        Directory containing one PhysiCell output subdirectory per manifest row.
        The subdirectory name must match ``row.simulation_id``.
    output_zarr
        Path of the Zarr store to write.
    summarize_config
        Required serialised :class:`SummarizeConfig` dict. The ``statistics``
        field must be supplied — tmelandscape does not ship a default panel.
        Call :func:`list_available_statistics_tool` first to discover which
        metric names are available.
    chunk_simulations, chunk_timepoints, chunk_statistics
        Per-axis Zarr chunk size; ``-1`` means "one chunk for the whole axis".

    Returns
    -------
    dict
        Summary with the Zarr path and the panel that was applied.
    """
    manifest = SweepManifest.load(manifest_path)
    cfg = SummarizeConfig.model_validate(summarize_config)
    zarr_path = summarize_ensemble(
        manifest,
        physicell_root=physicell_root,
        output_zarr=output_zarr,
        config=cfg,
        chunk_simulations=chunk_simulations,
        chunk_timepoints=chunk_timepoints,
        chunk_statistics=chunk_statistics,
    )
    return {
        "zarr_path": str(zarr_path),
        "n_simulations": len({row.simulation_id for row in manifest.rows}),
        "statistics": [spec.name for spec in cfg.statistics],
    }


def list_available_statistics_tool() -> list[dict[str, Any]]:
    """List every spatial statistic registered in ``spatialtissuepy``.

    Returns a list of metric descriptions (name, category, description,
    parameter schema). Use this to discover legal values for the
    ``statistics`` field of :class:`SummarizeConfig` before calling
    :func:`summarize_ensemble_tool`.

    There is no default panel: the user (or agent) must explicitly choose
    which metrics to compute for their TME landscape. See ADR 0009.
    """
    return list_available_statistics()


def describe_statistic_tool(name: str) -> dict[str, Any]:
    """Return the full description of one spatial-statistic metric.

    Parameters
    ----------
    name
        Metric name. Must appear in :func:`list_available_statistics_tool`.

    Returns
    -------
    dict
        Keys: ``name``, ``category``, ``description``, ``custom``,
        ``parameters`` (map of parameter name to type name).
    """
    return describe_metric(name)


def normalize_ensemble_tool(
    input_zarr: str,
    output_zarr: str,
    *,
    normalize_config: dict[str, Any],
) -> dict[str, Any]:
    """Run step 3.5: within-timestep normalisation of the ensemble Zarr.

    Reads an input Zarr produced by :func:`summarize_ensemble_tool`, applies
    the chosen normalisation strategy, and writes a NEW Zarr at
    ``output_zarr`` containing both the raw ``value`` array and the new
    normalised array. The input store is never overwritten.

    Parameters
    ----------
    input_zarr
        Path to the input ensemble Zarr.
    output_zarr
        Path of the NEW Zarr store to write. Must not already exist; the
        orchestrator refuses to overwrite by design (ADR 0006).
    normalize_config
        Required serialised :class:`NormalizeConfig` dict. There is no
        default — call :func:`list_normalize_strategies_tool` to discover
        available strategies first.

    Returns
    -------
    dict
        Summary with the output Zarr path and the applied config.
    """
    cfg = NormalizeConfig.model_validate(normalize_config)
    out_path = normalize_ensemble(input_zarr, output_zarr, config=cfg)
    return {
        "output_zarr": str(out_path),
        "strategy": cfg.strategy,
        "preserve_time_effect": cfg.preserve_time_effect,
        "drop_columns": list(cfg.drop_columns),
        "output_variable": cfg.output_variable,
    }


def list_normalize_strategies_tool() -> list[dict[str, str]]:
    """List available normalisation strategies (name + description).

    There is one default strategy in v0.4.0 (``within_timestep``) plus
    ``identity`` as a passthrough baseline. New strategies in
    ``tmelandscape.normalize.alternatives`` will land here in lockstep.
    """
    return [
        {
            "name": "within_timestep",
            "description": (
                "Per-timestep Yeo-Johnson + z-score, optionally re-adding the "
                "pre-transform per-step mean to preserve temporal trend. "
                "Reference oracle: reference/00_abm_normalization.py."
            ),
            "module": "tmelandscape.normalize.within_timestep",
        },
        {
            "name": "identity",
            "description": (
                "Passthrough strategy: returns the input unchanged. Useful as "
                "a baseline / for diagnosing orchestrator plumbing."
            ),
            "module": "tmelandscape.normalize.alternatives",
        },
    ]


def embed_ensemble_tool(
    input_zarr: str,
    output_zarr: str,
    *,
    embedding_config: dict[str, Any],
) -> dict[str, Any]:
    """Run step 4: sliding-window embedding of the normalised ensemble Zarr.

    Reads an input Zarr produced by :func:`normalize_ensemble_tool` (or
    earlier in the pipeline if the user picks a different ``source_variable``)
    and writes a NEW Zarr at ``output_zarr`` containing the flattened
    embedding array plus per-window metadata. The input is never overwritten.

    Parameters
    ----------
    input_zarr
        Path to the input ensemble Zarr.
    output_zarr
        Path of the NEW Zarr store to write. Must not already exist; the
        orchestrator refuses to overwrite by design (ADR 0006).
    embedding_config
        Required serialised :class:`EmbeddingConfig` dict. ``window_size``
        is required (no default). Call
        :func:`list_embed_strategies_tool` to discover available
        strategies first.

    Returns
    -------
    dict
        Summary with the output Zarr path and the applied config.
    """
    cfg = EmbeddingConfig.model_validate(embedding_config)
    out_path = embed_ensemble(input_zarr, output_zarr, config=cfg)
    return {
        "output_zarr": str(out_path),
        "strategy": cfg.strategy,
        "window_size": cfg.window_size,
        "step_size": cfg.step_size,
        "source_variable": cfg.source_variable,
        "output_variable": cfg.output_variable,
        "averages_variable": cfg.averages_variable,
        "drop_statistics": list(cfg.drop_statistics),
    }


def list_embed_strategies_tool() -> list[dict[str, str]]:
    """List available embedding strategies (name + description).

    v0.5.0 ships ``sliding_window`` (the reference algorithm) plus
    ``identity`` as a passthrough baseline. Future strategies in
    ``tmelandscape.embedding.alternatives`` will land here.
    """
    return [
        {
            "name": "sliding_window",
            "description": (
                "Per-simulation sliding window of length `window_size` (step "
                "1 by default), flattening each window's `(window_size, "
                "n_stat)` submatrix into a row vector. Reference oracle: "
                "reference/utils.py::window_trajectory_data."
            ),
            "module": "tmelandscape.embedding.sliding_window",
        },
        {
            "name": "identity",
            "description": (
                "Passthrough strategy: returns the input unchanged. Useful "
                "as a baseline / for diagnosing orchestrator plumbing."
            ),
            "module": "tmelandscape.embedding.alternatives",
        },
    ]


def cluster_ensemble_tool(
    input_zarr: str,
    output_zarr: str,
    *,
    cluster_config: dict[str, Any],
) -> dict[str, Any]:
    """Run step 5: two-stage Leiden + Ward clustering of the embedding Zarr.

    Reads an input Zarr produced by :func:`embed_ensemble_tool` and writes a
    NEW Zarr at ``output_zarr`` containing the per-window cluster labels
    (Leiden and final), the per-Leiden-cluster mean embedding vectors, the
    Ward linkage matrix, and (when auto-selection was used) the per-candidate
    metric scores. The input store is never overwritten.

    Parameters
    ----------
    input_zarr
        Path to the input ensemble Zarr (the artefact from Phase 4).
    output_zarr
        Path of the NEW Zarr store to write. Must not already exist; the
        orchestrator refuses to overwrite by design (ADR 0006).
    cluster_config
        Required serialised :class:`ClusterConfig` dict. ``n_final_clusters``
        may be omitted (``null`` / absent) to trigger auto-selection via
        ``cluster_count_metric`` (default: WSS elbow). The package ships no
        silent default for the number of TME states — see ADR 0010. Call
        :func:`list_cluster_strategies_tool` to discover available algorithms.

    Returns
    -------
    dict
        Summary with the output Zarr path and the applied config.
    """
    cfg = ClusterConfig.model_validate(cluster_config)
    out_path = cluster_ensemble(input_zarr, output_zarr, config=cfg)
    return {
        "output_zarr": str(out_path),
        "strategy": cfg.strategy,
        "knn_neighbors": cfg.knn_neighbors,
        "leiden_partition": cfg.leiden_partition,
        "leiden_resolution": cfg.leiden_resolution,
        "leiden_seed": cfg.leiden_seed,
        "n_final_clusters": cfg.n_final_clusters,
        "cluster_count_metric": cfg.cluster_count_metric,
        "cluster_count_min": cfg.cluster_count_min,
        "cluster_count_max": cfg.cluster_count_max,
        "source_variable": cfg.source_variable,
        "leiden_labels_variable": cfg.leiden_labels_variable,
        "final_labels_variable": cfg.final_labels_variable,
        "cluster_means_variable": cfg.cluster_means_variable,
        "linkage_variable": cfg.linkage_variable,
        "cluster_count_scores_variable": cfg.cluster_count_scores_variable,
    }


def list_cluster_strategies_tool() -> list[dict[str, str]]:
    """List available clustering strategies (name + description).

    v0.6.0 ships ``leiden_ward`` (the reference two-stage algorithm) plus
    ``identity`` as a passthrough baseline. Future strategies in
    ``tmelandscape.cluster.alternatives`` will land here.
    """
    return [
        {
            "name": "leiden_ward",
            "description": (
                "Two-stage clustering: Leiden community detection on a kNN "
                "graph over the embedding (Stage 1), then Ward hierarchical "
                "clustering on the per-Leiden-community mean embedding "
                "vectors (Stage 2). The dendrogram is cut at "
                "`n_final_clusters` if supplied; otherwise auto-selected via "
                "`cluster_count_metric` (default: WSS elbow). Reference "
                "oracle: reference/01_abm_generate_embedding.py lines "
                "~519-720. See ADR 0007 and ADR 0010."
            ),
            "module": "tmelandscape.cluster.leiden_ward",
        },
        {
            "name": "identity",
            "description": (
                "Passthrough baseline: assigns every row to cluster 0. "
                "Useful for diagnosing orchestrator plumbing or as a "
                "no-op anchor in tests."
            ),
            "module": "tmelandscape.cluster.alternatives",
        },
    ]


# ---------------------------------------------------------------------------
# Phase 6 visualisation tools (one per figure function).
#
# Every figure tool **requires** `save_path` (string) — MCP cannot pass
# matplotlib Figure objects, so the only useful return value is the path
# of the saved image plus a small summary dict. Tools that depend on a
# UMAP projection fit it inline using the standard defaults
# (n_neighbors=15, min_dist=0.1, random_state=42); a future MCP-side
# caching layer could share fits across tools if call patterns demand it.
# ---------------------------------------------------------------------------


def _viz_summary(
    save_path: str,
    figure_tag: str,
    *,
    manuscript: str,
    description: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "save_path": str(Path(save_path).resolve()),
        "figure_tag": figure_tag,
        "manuscript": manuscript,
        "description": description,
    }
    if extra:
        out.update(extra)
    return out


def plot_state_umap_tool(
    cluster_zarr: str,
    save_path: str,
    *,
    n_neighbors: int = 15,
    min_dist: float = 0.1,
    random_state: int = 42,
) -> dict[str, Any]:
    """TNBC-2b — state-coloured UMAP scatter of the windowed embedding.

    Fits UMAP inline (parameters tunable via kwargs); writes the figure
    to ``save_path``. Returns the absolute resolved save path.
    """
    umap_result = fit_umap(
        cluster_zarr,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        random_state=random_state,
    )
    plot_state_umap(umap_result, cluster_zarr, save_path=save_path)
    return _viz_summary(
        save_path,
        "tnbc-2b",
        manuscript="TNBC",
        description="state-coloured UMAP scatter",
    )


def plot_time_umap_tool(
    cluster_zarr: str,
    save_path: str,
    *,
    n_neighbors: int = 15,
    min_dist: float = 0.1,
    random_state: int = 42,
) -> dict[str, Any]:
    """TNBC-2c — UMAP scatter coloured by per-window mean time (in
    timepoint-index units; see decision log
    2026-05-14-viz-time-umap-uses-window-bounds.md)."""
    umap_result = fit_umap(
        cluster_zarr,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        random_state=random_state,
    )
    plot_time_umap(umap_result, cluster_zarr, save_path=save_path)
    return _viz_summary(
        save_path,
        "tnbc-2c",
        manuscript="TNBC",
        description="UMAP scatter coloured by per-window mean time",
    )


def plot_feature_umap_tool(
    cluster_zarr: str,
    save_path: str,
    *,
    features: Sequence[str],
    n_neighbors: int = 15,
    min_dist: float = 0.1,
    random_state: int = 42,
) -> dict[str, Any]:
    """LCSS-4 / TNBC-2e — multi-panel UMAP scatter, one panel per
    feature in ``features`` (statistic names that appear in the
    ``window_averages`` coord of the cluster Zarr)."""
    umap_result = fit_umap(
        cluster_zarr,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        random_state=random_state,
    )
    plot_feature_umap(umap_result, cluster_zarr, features=list(features), save_path=save_path)
    return _viz_summary(
        save_path,
        "lcss-4/tnbc-2e",
        manuscript="LCSS/TNBC",
        description="multi-panel UMAP coloured by per-feature window averages",
        extra={"features": list(features)},
    )


def plot_trajectory_umap_tool(
    cluster_zarr: str,
    save_path: str,
    *,
    sim_ids: Sequence[str],
    n_neighbors: int = 15,
    min_dist: float = 0.1,
    random_state: int = 42,
) -> dict[str, Any]:
    """TNBC-2d — state-coloured UMAP scatter with named simulation
    trajectories overlaid as polylines."""
    umap_result = fit_umap(
        cluster_zarr,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        random_state=random_state,
    )
    plot_trajectory_umap(umap_result, cluster_zarr, sim_ids=list(sim_ids), save_path=save_path)
    return _viz_summary(
        save_path,
        "tnbc-2d",
        manuscript="TNBC",
        description="trajectory overlays on the state-coloured UMAP",
        extra={"sim_ids": list(sim_ids)},
    )


def plot_state_umap_with_vector_field_tool(
    cluster_zarr: str,
    save_path: str,
    *,
    grid_size: int = 20,
    show_density_contours: bool = True,
    n_neighbors: int = 15,
    min_dist: float = 0.1,
    random_state: int = 42,
) -> dict[str, Any]:
    """LCSS-3 — state-coloured UMAP + per-state vector field + (optional)
    per-state density contours. Vector-field inclusion criterion is "both
    endpoints in state s" — see decision log
    2026-05-14-viz-lcss3-vector-field-semantics.md."""
    umap_result = fit_umap(
        cluster_zarr,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        random_state=random_state,
    )
    plot_state_umap_with_vector_field(
        umap_result,
        cluster_zarr,
        grid_size=grid_size,
        show_density_contours=show_density_contours,
        save_path=save_path,
    )
    return _viz_summary(
        save_path,
        "lcss-3",
        manuscript="LCSS",
        description="state UMAP + per-state vector field + density contours",
    )


def plot_state_feature_clustermap_tool(
    cluster_zarr: str,
    save_path: str,
    *,
    z_score: int | None = 1,
    cmap: str = "viridis",
) -> dict[str, Any]:
    """TNBC-2a — seaborn clustermap of Leiden cluster means x spatial
    features. Row dendrogram comes from the cluster Zarr's
    ``linkage_matrix``; rows annotated by Ward-cluster colour bar."""
    plot_state_feature_clustermap(cluster_zarr, z_score=z_score, cmap=cmap, save_path=save_path)
    return _viz_summary(
        save_path,
        "tnbc-2a",
        manuscript="TNBC",
        description="clustermap of Leiden cluster means x spatial features",
    )


def plot_trajectory_clustergram_tool(
    cluster_zarr: str,
    save_path: str,
    *,
    metric: str = "euclidean",
    linkage_method: str = "average",
) -> dict[str, Any]:
    """TNBC-6a — (sim x window) heatmap of state labels with a row
    dendrogram (Ward / specified ``linkage_method`` on the per-sim
    trajectory vectors)."""
    plot_trajectory_clustergram(
        cluster_zarr,
        metric=metric,
        linkage_method=linkage_method,
        save_path=save_path,
    )
    return _viz_summary(
        save_path,
        "tnbc-6a",
        manuscript="TNBC",
        description="trajectory clustergram (sim x window state labels)",
    )


def plot_phase_space_vector_field_tool(
    cluster_zarr: str,
    save_path: str,
    *,
    x_feature: str,
    y_feature: str,
    states: Sequence[int],
    grid_size: int = 20,
) -> dict[str, Any]:
    """TNBC-6b — per-state vector field in ``(x_feature, y_feature)``
    phase space plus per-state 2D occupancy heatmap. Feature names must
    appear in the cluster Zarr's ``window_averages`` ``statistic`` coord.
    Per ADR 0009, feature names are user-supplied — no hardcoded
    ``(epithelial, T_eff)`` default."""
    plot_phase_space_vector_field(
        cluster_zarr,
        x_feature=x_feature,
        y_feature=y_feature,
        states=list(states),
        grid_size=grid_size,
        save_path=save_path,
    )
    return _viz_summary(
        save_path,
        "tnbc-6b",
        manuscript="TNBC",
        description="per-state vector field in 2D feature phase space",
        extra={"x_feature": x_feature, "y_feature": y_feature, "states": list(states)},
    )


def plot_parameter_by_state_tool(
    cluster_zarr: str,
    save_path: str,
    *,
    manifest_path: str,
    parameter: str,
) -> dict[str, Any]:
    """TNBC-6c — violin plot of a named sweep parameter by terminal TME
    state with pairwise Mann-Whitney + BH-FDR significance annotations
    (BH-FDR is hand-rolled — see decision log
    2026-05-14-bh-fdr-hand-rolled.md). Parameter name is user-supplied
    per ADR 0009."""
    plot_parameter_by_state(
        cluster_zarr,
        manifest_path,
        parameter=parameter,
        save_path=save_path,
    )
    return _viz_summary(
        save_path,
        "tnbc-6c",
        manuscript="TNBC",
        description="violin of a sweep parameter by terminal TME state",
        extra={"parameter": parameter, "manifest_path": str(manifest_path)},
    )


def plot_model_schematic_tool(
    cell_types: list[str | dict[str, Any]],
    interactions: list[dict[str, Any]],
    save_path: str,
    *,
    layout: str = "circular",
    color_palette: list[str] | None = None,
    node_radius: float = 0.15,
) -> dict[str, Any]:
    """LCSS-1 (generalised) — render a programmatic schematic of any
    user-supplied ABM.

    Nodes are cell types (coloured circles + labels); edges are typed
    interactions (``"promotes"``, ``"inhibits"``, ``"transitions_to"``,
    ``"secretes"``). Per `decision log
    2026-05-14-lcss-1-schematic-in-scope.md`, the figure is generic
    across any model — pass any cell-type list + interaction list, not
    just the LCSS paper's specific TME ABM.

    Parameters
    ----------
    cell_types
        List of cell-type descriptors. Each entry is either a string
        (bare name; auto-coloured) or a dict ``{"name": str, "color":
        str | None, "category": str | None}``.
    interactions
        List of interaction descriptors. Each entry is a dict
        ``{"source": str, "target": str, "kind": str, "label": str | None}``
        where ``kind`` is one of ``"promotes"``, ``"inhibits"``,
        ``"transitions_to"``, ``"secretes"``.
    save_path
        Output path. ``.svg`` ⇒ vector; ``.png`` ⇒ raster. matplotlib's
        extension dispatch selects the format.
    layout, color_palette, node_radius
        Forwarded to :func:`tmelandscape.viz.model_schematic.plot_model_schematic`.
    """
    cells: list[str | CellType] = [c if isinstance(c, str) else CellType(**c) for c in cell_types]
    edges = [Interaction(**i) for i in interactions]
    plot_model_schematic(
        cells,
        edges,
        layout=layout,  # type: ignore[arg-type]
        color_palette=color_palette,
        node_radius=node_radius,
        save_path=save_path,
    )
    return _viz_summary(
        save_path,
        "lcss-1",
        manuscript="LCSS",
        description=(
            "programmatic ABM model schematic — coloured nodes for cell "
            "types and typed arrows for interactions"
        ),
        extra={
            "n_cell_types": len(cell_types),
            "n_interactions": len(interactions),
            "layout": layout,
        },
    )


def plot_attractor_basins_tool(
    cluster_zarr: str,
    save_path: str,
    *,
    manifest_path: str,
    x_parameter: str,
    y_parameter: str,
    states: Sequence[int] | None = None,
    knn_neighbors: int = 2,
    grid_size: int = 200,
) -> dict[str, Any]:
    """LCSS-6 — 2D parameter-space scatter of simulations coloured by
    terminal cluster; ``knn_neighbors``-NN decision-boundary regions
    shaded as background. Parameter names are user-supplied per
    ADR 0009."""
    plot_attractor_basins(
        cluster_zarr,
        manifest_path,
        x_parameter=x_parameter,
        y_parameter=y_parameter,
        states=list(states) if states is not None else None,
        knn_neighbors=knn_neighbors,
        grid_size=grid_size,
        save_path=save_path,
    )
    return _viz_summary(
        save_path,
        "lcss-6",
        manuscript="LCSS",
        description="parameter-space attractor basins via kNN classifier",
        extra={
            "x_parameter": x_parameter,
            "y_parameter": y_parameter,
            "knn_neighbors": knn_neighbors,
            "manifest_path": str(manifest_path),
        },
    )


def list_viz_figures_tool() -> list[dict[str, str]]:
    """List every figure-producing MCP tool with its manuscript citation
    and a one-line description. Use this to discover which figures the
    package can reproduce before calling a specific ``plot_*_tool``.
    """
    return [
        {
            "tool_name": "plot_state_umap",
            "figure_tag": "tnbc-2b",
            "manuscript": "TNBC",
            "description": "state-coloured UMAP scatter",
        },
        {
            "tool_name": "plot_time_umap",
            "figure_tag": "tnbc-2c",
            "manuscript": "TNBC",
            "description": "UMAP scatter coloured by per-window mean time",
        },
        {
            "tool_name": "plot_feature_umap",
            "figure_tag": "lcss-4/tnbc-2e",
            "manuscript": "LCSS/TNBC",
            "description": (
                "multi-panel UMAP coloured by per-feature window averages "
                "(LCSS-4 uses 3 features: tumour cells, effector T cells, "
                "exhausted T cells; TNBC-2e additionally includes tumour-cell "
                "degree centrality)"
            ),
        },
        {
            "tool_name": "plot_trajectory_umap",
            "figure_tag": "tnbc-2d",
            "manuscript": "TNBC",
            "description": "trajectory overlays on the state-coloured UMAP",
        },
        {
            "tool_name": "plot_state_umap_with_vector_field",
            "figure_tag": "lcss-3",
            "manuscript": "LCSS",
            "description": (
                "state-coloured UMAP scatter + per-state vector field + per-state density contours"
            ),
        },
        {
            "tool_name": "plot_state_feature_clustermap",
            "figure_tag": "tnbc-2a",
            "manuscript": "TNBC",
            "description": (
                "seaborn clustermap of Leiden cluster means x spatial "
                "features with Ward-row dendrogram and state colour bar"
            ),
        },
        {
            "tool_name": "plot_trajectory_clustergram",
            "figure_tag": "tnbc-6a",
            "manuscript": "TNBC",
            "description": ("(sim x window) heatmap of state labels with row dendrogram"),
        },
        {
            "tool_name": "plot_phase_space_vector_field",
            "figure_tag": "tnbc-6b",
            "manuscript": "TNBC",
            "description": (
                "per-state vector field in (x_feature, y_feature) phase "
                "space with 2D occupancy histogram"
            ),
        },
        {
            "tool_name": "plot_parameter_by_state",
            "figure_tag": "tnbc-6c",
            "manuscript": "TNBC",
            "description": (
                "violin plot of a named sweep parameter by terminal TME "
                "state with pairwise Mann-Whitney + BH-FDR significance"
            ),
        },
        {
            "tool_name": "plot_attractor_basins",
            "figure_tag": "lcss-6",
            "manuscript": "LCSS",
            "description": (
                "2D parameter-space scatter coloured by terminal cluster "
                "with kNN decision-boundary regions"
            ),
        },
        {
            "tool_name": "plot_model_schematic",
            "figure_tag": "lcss-1",
            "manuscript": "LCSS",
            "description": (
                "programmatic ABM schematic: coloured nodes for cell types "
                "and typed arrows for interactions (promotes / inhibits / "
                "transitions_to / secretes). Generic across any user-supplied "
                "model, not just the LCSS paper's. Output supports both PNG "
                "and SVG via the save_path extension."
            ),
        },
    ]
