"""Phase 6 end-to-end: Python API and MCP tool produce equivalent PNGs.

There is intentionally no CLI verb per figure (the task file's "MCP
surface" section), so this integration test exercises **two** surfaces
per figure: the Python API and the matching MCP tool. Each MCP tool
wraps the same Python function, so equivalence is expected by
construction; the test guards against drift (e.g. someone edits the MCP
wrapper to silently swap kwargs).

The synthetic fixture is a deterministic cluster Zarr built inline:
6 sims x 8 windows x 5 final states, 3D embedding, two-statistic
`window_averages` companion, and a sweep manifest carrying two
parameters.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import scipy.cluster.hierarchy as sch
import scipy.spatial.distance as spd
import xarray as xr
from typer.testing import CliRunner

from tmelandscape.cli.main import app
from tmelandscape.config.sweep import ParameterSpec, SweepConfig
from tmelandscape.mcp.tools import (
    list_viz_figures_tool,
    plot_attractor_basins_tool,
    plot_feature_umap_tool,
    plot_parameter_by_state_tool,
    plot_phase_space_vector_field_tool,
    plot_state_feature_clustermap_tool,
    plot_state_umap_tool,
    plot_state_umap_with_vector_field_tool,
    plot_time_umap_tool,
    plot_trajectory_clustergram_tool,
    plot_trajectory_umap_tool,
)
from tmelandscape.sampling.manifest import SweepManifest, SweepRow
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
from tmelandscape.viz.trajectories import (
    plot_state_feature_clustermap,
    plot_trajectory_clustergram,
)

# `n_embedding_feature` must equal `window_size * n_statistic` so that
# `plot_state_feature_clustermap`'s repeated-measure collapse can recover
# the per-statistic axis (window_size = 2, n_statistic = 2 ⇒ 4 features).
_N_SIMS = 6
_N_WINDOWS = 8
_N_FINAL_STATES = 5
_N_LEIDEN = 6
_WINDOW_SIZE = 2
_N_STAT = 2
_N_FEATURE = _WINDOW_SIZE * _N_STAT  # 4
_STAT_NAMES = ["stat_a", "stat_b"]
_PARAM_NAMES = ["alpha", "beta"]


def _build_cluster_zarr(path: Path, *, seed: int = 0) -> None:
    rng = np.random.default_rng(seed)

    sim_ids = np.array([f"sim_{i:02d}" for i in range(_N_SIMS)], dtype="U16")
    n_window_total = _N_SIMS * _N_WINDOWS

    rows_sim = np.repeat(sim_ids, _N_WINDOWS)
    rows_win = np.tile(np.arange(_N_WINDOWS, dtype=np.int64), _N_SIMS)
    rows_start = rows_win.astype(np.int64)
    rows_end = (rows_win + 3).astype(np.int64)
    parameter_alpha = np.repeat(np.linspace(0.1, 1.0, _N_SIMS, dtype=np.float64), _N_WINDOWS)
    parameter_beta = np.repeat(np.linspace(0.2, 0.9, _N_SIMS, dtype=np.float64), _N_WINDOWS)

    # Cluster labels: assign each sim to a final state via the per-sim
    # index modulo n_final_states; final-state labels are 1-based.
    final_labels = ((np.repeat(np.arange(_N_SIMS), _N_WINDOWS) % _N_FINAL_STATES) + 1).astype(
        np.int64
    )
    leiden_labels = (np.repeat(np.arange(_N_SIMS), _N_WINDOWS) % _N_LEIDEN).astype(np.int64)

    embedding = rng.standard_normal((n_window_total, _N_FEATURE)).astype(np.float64)
    # Separate the per-state centroids slightly so UMAP / clustermap have
    # signal to recover. Offset vector length matches `_N_FEATURE`.
    base_offset = np.array(
        [0.6, -0.4, 0.2, 0.3, -0.5, 0.1, -0.2, 0.4][:_N_FEATURE], dtype=np.float64
    )
    for state in range(1, _N_FINAL_STATES + 1):
        mask = final_labels == state
        embedding[mask] += state * base_offset

    window_averages = rng.standard_normal((n_window_total, _N_STAT)).astype(np.float64)
    window_averages[:, 0] += parameter_alpha
    window_averages[:, 1] += parameter_beta

    leiden_cluster_means = np.zeros((_N_LEIDEN, _N_FEATURE), dtype=np.float64)
    for c in range(_N_LEIDEN):
        leiden_cluster_means[c] = embedding[leiden_labels == c].mean(axis=0)
    d = spd.pdist(leiden_cluster_means, metric="euclidean")
    linkage_matrix = sch.linkage(d, method="ward").astype(np.float64)

    cluster_count_scores = np.empty(0, dtype=np.float64)

    ds = xr.Dataset(
        data_vars={
            "embedding": (("window", "embedding_feature"), embedding),
            "window_averages": (("window", "statistic"), window_averages),
            "leiden_labels": (("window",), leiden_labels),
            "cluster_labels": (("window",), final_labels),
            "leiden_cluster_means": (
                ("leiden_cluster", "embedding_feature"),
                leiden_cluster_means,
            ),
            "linkage_matrix": (
                ("linkage_step", "linkage_field"),
                linkage_matrix,
            ),
            "cluster_count_scores": (("cluster_count_candidate",), cluster_count_scores),
        },
        coords={
            "window": np.arange(n_window_total, dtype=np.int64),
            "embedding_feature": np.arange(_N_FEATURE, dtype=np.int64),
            "statistic": np.asarray(_STAT_NAMES, dtype="U16"),
            "leiden_cluster": np.arange(_N_LEIDEN, dtype=np.int64),
            "linkage_step": np.arange(linkage_matrix.shape[0], dtype=np.int64),
            "linkage_field": np.arange(4, dtype=np.int64),
            "cluster_count_candidate": np.empty(0, dtype=np.int64),
            "simulation_id": (("window",), rows_sim),
            "window_index_in_sim": (("window",), rows_win),
            "start_timepoint": (("window",), rows_start),
            "end_timepoint": (("window",), rows_end),
            "parameter_alpha": (("window",), parameter_alpha),
            "parameter_beta": (("window",), parameter_beta),
        },
        attrs={
            "n_final_clusters_used": _N_FINAL_STATES,
            "cluster_count_metric_used": "user_supplied",
        },
    )
    ds.to_zarr(path, mode="w")


def _build_manifest(path: Path, *, seed: int = 0) -> None:
    config = SweepConfig(
        parameters=[ParameterSpec(name=name, low=0.0, high=1.0) for name in _PARAM_NAMES],
        n_parameter_samples=_N_SIMS,
        n_initial_conditions=1,
        seed=seed,
    )
    rows = []
    for i in range(_N_SIMS):
        rows.append(
            SweepRow(
                simulation_id=f"sim_{i:02d}",
                parameter_combination_id=i,
                ic_id=0,
                parameter_values={
                    "alpha": float(np.linspace(0.1, 1.0, _N_SIMS)[i]),
                    "beta": float(np.linspace(0.2, 0.9, _N_SIMS)[i]),
                },
                ic_path=f"sim_{i:02d}.csv",
            )
        )
    manifest = SweepManifest(
        config=config,
        rows=rows,
        initial_conditions_dir=str(path.parent.resolve()),
    )
    manifest.save(str(path.with_suffix("")))


def _png_sha256(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def cluster_zarr(tmp_path: Path) -> Path:
    p = tmp_path / "cluster.zarr"
    _build_cluster_zarr(p)
    return p


@pytest.fixture
def manifest_path(tmp_path: Path) -> Path:
    stem = tmp_path / "manifest"
    _build_manifest(stem)
    return stem.with_suffix(".json")


def _api_state_umap(cluster_zarr: Path, save_path: Path) -> None:
    umap_result = fit_umap(cluster_zarr)
    plot_state_umap(umap_result, cluster_zarr, save_path=save_path)


def _api_time_umap(cluster_zarr: Path, save_path: Path) -> None:
    umap_result = fit_umap(cluster_zarr)
    plot_time_umap(umap_result, cluster_zarr, save_path=save_path)


def _api_feature_umap(cluster_zarr: Path, save_path: Path) -> None:
    umap_result = fit_umap(cluster_zarr)
    plot_feature_umap(umap_result, cluster_zarr, features=_STAT_NAMES, save_path=save_path)


def _api_trajectory_umap(cluster_zarr: Path, save_path: Path) -> None:
    umap_result = fit_umap(cluster_zarr)
    plot_trajectory_umap(
        umap_result, cluster_zarr, sim_ids=["sim_00", "sim_01"], save_path=save_path
    )


def _api_state_umap_vfield(cluster_zarr: Path, save_path: Path) -> None:
    umap_result = fit_umap(cluster_zarr)
    plot_state_umap_with_vector_field(umap_result, cluster_zarr, grid_size=5, save_path=save_path)


@pytest.mark.parametrize(
    ("tag", "api_fn", "mcp_tool", "mcp_kwargs"),
    [
        ("plot_state_umap", _api_state_umap, plot_state_umap_tool, {}),
        ("plot_time_umap", _api_time_umap, plot_time_umap_tool, {}),
        (
            "plot_feature_umap",
            _api_feature_umap,
            plot_feature_umap_tool,
            {"features": _STAT_NAMES},
        ),
        (
            "plot_trajectory_umap",
            _api_trajectory_umap,
            plot_trajectory_umap_tool,
            {"sim_ids": ["sim_00", "sim_01"]},
        ),
        (
            "plot_state_umap_with_vector_field",
            _api_state_umap_vfield,
            plot_state_umap_with_vector_field_tool,
            {"grid_size": 5, "show_density_contours": True},
        ),
    ],
)
def test_umap_family_api_matches_mcp_tool(
    cluster_zarr: Path,
    tmp_path: Path,
    tag: str,
    api_fn: object,
    mcp_tool: object,
    mcp_kwargs: dict[str, object],
) -> None:
    api_out = tmp_path / f"api_{tag}.png"
    mcp_out = tmp_path / f"mcp_{tag}.png"

    api_fn(cluster_zarr, api_out)
    result = mcp_tool(str(cluster_zarr), str(mcp_out), **mcp_kwargs)

    assert api_out.is_file()
    assert mcp_out.is_file()
    assert Path(result["save_path"]) == mcp_out.resolve()
    # Both surfaces use the same UMAP seed + same plot path; PNG bytes match.
    assert _png_sha256(api_out) == _png_sha256(mcp_out)


def test_state_feature_clustermap_api_matches_mcp_tool(cluster_zarr: Path, tmp_path: Path) -> None:
    api_out = tmp_path / "api.png"
    mcp_out = tmp_path / "mcp.png"

    plot_state_feature_clustermap(cluster_zarr, save_path=api_out)
    plot_state_feature_clustermap_tool(str(cluster_zarr), str(mcp_out))

    assert _png_sha256(api_out) == _png_sha256(mcp_out)


def test_trajectory_clustergram_api_matches_mcp_tool(cluster_zarr: Path, tmp_path: Path) -> None:
    api_out = tmp_path / "api.png"
    mcp_out = tmp_path / "mcp.png"

    plot_trajectory_clustergram(cluster_zarr, save_path=api_out)
    plot_trajectory_clustergram_tool(str(cluster_zarr), str(mcp_out))

    assert _png_sha256(api_out) == _png_sha256(mcp_out)


def test_phase_space_vector_field_api_matches_mcp_tool(cluster_zarr: Path, tmp_path: Path) -> None:
    api_out = tmp_path / "api.png"
    mcp_out = tmp_path / "mcp.png"

    plot_phase_space_vector_field(
        cluster_zarr,
        x_feature="stat_a",
        y_feature="stat_b",
        states=[1, 2, 3],
        grid_size=5,
        save_path=api_out,
    )
    plot_phase_space_vector_field_tool(
        str(cluster_zarr),
        str(mcp_out),
        x_feature="stat_a",
        y_feature="stat_b",
        states=[1, 2, 3],
        grid_size=5,
    )

    assert _png_sha256(api_out) == _png_sha256(mcp_out)


def test_parameter_by_state_api_matches_mcp_tool(
    cluster_zarr: Path, manifest_path: Path, tmp_path: Path
) -> None:
    api_out = tmp_path / "api.png"
    mcp_out = tmp_path / "mcp.png"

    plot_parameter_by_state(
        cluster_zarr,
        manifest_path,
        parameter="parameter_alpha",
        save_path=api_out,
    )
    plot_parameter_by_state_tool(
        str(cluster_zarr),
        str(mcp_out),
        manifest_path=str(manifest_path),
        parameter="parameter_alpha",
    )

    assert _png_sha256(api_out) == _png_sha256(mcp_out)


def test_attractor_basins_api_matches_mcp_tool(
    cluster_zarr: Path, manifest_path: Path, tmp_path: Path
) -> None:
    api_out = tmp_path / "api.png"
    mcp_out = tmp_path / "mcp.png"

    plot_attractor_basins(
        cluster_zarr,
        manifest_path,
        x_parameter="parameter_alpha",
        y_parameter="parameter_beta",
        grid_size=20,
        save_path=api_out,
    )
    plot_attractor_basins_tool(
        str(cluster_zarr),
        str(mcp_out),
        manifest_path=str(manifest_path),
        x_parameter="parameter_alpha",
        y_parameter="parameter_beta",
        grid_size=20,
    )

    assert _png_sha256(api_out) == _png_sha256(mcp_out)


# ---------------------------------------------------------------------------
# Discovery surfaces
# ---------------------------------------------------------------------------


def test_cli_viz_figures_list_matches_mcp_tool() -> None:
    """CLI ``viz-figures list`` produces the same catalogue as the MCP
    ``list_viz_figures`` tool."""
    runner = CliRunner()
    result = runner.invoke(app, ["viz-figures", "list"])
    assert result.exit_code == 0, result.stdout
    cli_catalogue = json.loads(result.stdout)
    mcp_catalogue = list_viz_figures_tool()
    assert cli_catalogue == mcp_catalogue


def test_list_viz_figures_covers_all_figure_tools() -> None:
    """Catalogue covers every figure-producing MCP tool by name.

    11 tools as of v0.7.1: the 10 from v0.7.0 plus the LCSS-1
    schematic generator added in v0.7.1.
    """
    catalogue = list_viz_figures_tool()
    names = {entry["tool_name"] for entry in catalogue}
    assert names == {
        "plot_state_umap",
        "plot_time_umap",
        "plot_feature_umap",
        "plot_trajectory_umap",
        "plot_state_umap_with_vector_field",
        "plot_state_feature_clustermap",
        "plot_trajectory_clustergram",
        "plot_phase_space_vector_field",
        "plot_parameter_by_state",
        "plot_attractor_basins",
        "plot_model_schematic",
    }


def test_plot_model_schematic_api_matches_mcp_tool(tmp_path: Path) -> None:
    """LCSS-1 — Python API and MCP tool produce equivalent PNG bytes.

    The schematic generator takes a model description (cell types +
    interactions) rather than a cluster Zarr, so this test is
    self-contained (no fixture dependency).
    """
    from tmelandscape.mcp.tools import plot_model_schematic_tool
    from tmelandscape.viz.model_schematic import (
        CellType,
        Interaction,
        plot_model_schematic,
    )

    cells = [
        CellType(name="tumour", color="#d62728", category="malignant"),
        CellType(name="CD8_Teff", color="#2ca02c", category="immune"),
        CellType(name="CD8_Tex", color="#7f7f7f", category="immune"),
    ]
    interactions = [
        Interaction(source="CD8_Teff", target="tumour", kind="inhibits"),
        Interaction(source="tumour", target="CD8_Teff", kind="inhibits"),
        Interaction(source="CD8_Teff", target="CD8_Tex", kind="transitions_to"),
    ]

    api_out = tmp_path / "api.png"
    mcp_out = tmp_path / "mcp.png"

    plot_model_schematic(cells, interactions, save_path=api_out)

    cell_dicts = [{"name": c.name, "color": c.color, "category": c.category} for c in cells]
    interaction_dicts = [
        {"source": i.source, "target": i.target, "kind": i.kind, "label": i.label}
        for i in interactions
    ]
    result = plot_model_schematic_tool(
        cell_dicts,
        interaction_dicts,
        str(mcp_out),
    )

    assert api_out.is_file()
    assert mcp_out.is_file()
    assert Path(result["save_path"]) == mcp_out.resolve()
    assert result["figure_tag"] == "lcss-1"
    assert _png_sha256(api_out) == _png_sha256(mcp_out)


def test_plot_model_schematic_svg_round_trip(tmp_path: Path) -> None:
    """The schematic supports SVG output via matplotlib's extension dispatch."""
    from tmelandscape.viz.model_schematic import (
        CellType,
        Interaction,
        plot_model_schematic,
    )

    cells = [CellType(name="A"), CellType(name="B")]
    interactions = [Interaction(source="A", target="B", kind="promotes")]
    out = tmp_path / "schematic.svg"
    plot_model_schematic(cells, interactions, save_path=out)
    assert out.is_file()
    head = out.read_bytes()[:64].lstrip()
    assert head.startswith(b"<?xml") or head.startswith(b"<svg ")
