"""Initial-condition replicate generation via ``tissue_simulator``.

Given a user-supplied typed source CSV, build a target spatial graph from it
and produce N replicate CSVs whose graph statistics (per-type proportions and
per-type-pair edge counts) match the source. Replicate-to-replicate variation
comes from a fresh scaffold packing (or jittered copy of the source); type
labels are assigned by simulated annealing in
:class:`tissue_simulator.GraphColorizer`.

The source CSV's columns are ``x, y, z, radius, cell_type, is_boundary`` —
the schema written by :meth:`tissue_simulator.TissueSection.export_to_csv`.

This module ingests; the upstream skill flow is responsible for producing the
typed CSV (whether by loading the user's own data or realizing a structured
description via PhysiCell ``place_initial_cells``).
"""

from __future__ import annotations

import hashlib
import sys
from contextlib import ExitStack, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from tmelandscape.config.sweep import SAParams

if TYPE_CHECKING:
    import networkx as nx


@dataclass(frozen=True)
class IcGenResult:
    """One replicate's output, with the diagnostics the manifest carries forward."""

    path: Path
    scaffold_seed: int
    sha256: str
    sa_final_cost: float
    achieved_proportions: dict[str, float] = field(default_factory=dict)


def generate_initial_conditions(
    *,
    n_replicates: int,
    output_dir: str | Path,
    seed: int,
    source_csv: str | Path,
    scaffold_strategy: Literal["uniform_random", "perturb_source"] = "uniform_random",
    sa_params: SAParams | None = None,
    network_mode: Literal["contact", "radius"] = "radius",
    network_radius_um: float | None = None,
) -> list[IcGenResult]:
    """Generate ``n_replicates`` typed IC CSVs matched to ``source_csv``.

    Each replicate has exactly the same number of cells as the source (a
    requirement for ``GraphColorizer`` to match proportions exactly: with
    mismatched N the initial-fill step dumps the extras into the majority
    type and distorts the statistics). The scaffold packing is regenerated
    per replicate; the type labels are assigned by simulated annealing
    against the source graph's per-type proportions and per-type-pair edge
    counts.

    Parameters
    ----------
    n_replicates
        Number of replicate CSVs to generate.
    output_dir
        Directory into which CSVs are written; created if it does not exist.
    seed
        RNG seed. Children are spawned via :class:`numpy.random.SeedSequence`,
        one per replicate, so each replicate is independently deterministic.
    source_csv
        Path to a typed-coordinate CSV (the
        :meth:`tissue_simulator.TissueSection.export_to_csv` schema).
    scaffold_strategy
        ``"uniform_random"`` packs N cells fresh in the source's bounding box
        per replicate; ``"perturb_source"`` copies the source positions and
        jitters each by ``Normal(0, 0.5 * min_radius)``. Use the latter when
        you want to preserve the source's morphology while still producing
        independent samples.
    sa_params
        Simulated-annealing schedule for
        :meth:`tissue_simulator.GraphColorizer.colorize`. Defaults to
        :class:`tmelandscape.config.sweep.SAParams` if None.
    network_mode
        ``"radius"`` (default) builds the spatial graph by Euclidean distance;
        ``"contact"`` uses touching-cell edges. ``"radius"`` is less sensitive
        to scaffold-vs-source packing-density variation.
    network_radius_um
        Edge-cutoff distance for ``network_mode="radius"``. When None
        (default), resolved to ``2.5 * max(source cell radius)``.

    Returns
    -------
    list[IcGenResult]
        One :class:`IcGenResult` per replicate, in replicate order. Files are
        named ``ic_0000.csv``, ``ic_0001.csv``, ... (zero-padded to four digits).
    """
    if n_replicates <= 0:
        raise ValueError(f"n_replicates must be positive, got {n_replicates}")

    # Defer the tissue_simulator imports so an upstream API change (renamed
    # submodule, missing symbol) raises an informative error from this function
    # rather than breaking `import tmelandscape` at module-load time.
    try:
        import networkx as nx
        from tissue_simulator import (
            Cell,
            GraphColorizer,
            SpatialNetworkAnalyzer,
            TissueSection,
            load_tissue_from_csv,
        )
    except ImportError as exc:  # pragma: no cover - exercised only on upstream drift
        raise ImportError(
            "tissue_simulator (>=v0.1.9) and networkx are required for "
            "generate_initial_conditions; install with `uv sync`. "
            f"Underlying error: {exc}"
        ) from exc

    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    resolved_sa = sa_params or SAParams()

    # tissue_simulator's GraphColorizer prints unconditional progress lines
    # in __init__ and during colorize. Redirect to stderr so CLI/MCP stdout
    # remains clean JSON.
    with ExitStack() as stack:
        stack.enter_context(redirect_stdout(sys.stderr))

        source = load_tissue_from_csv(str(source_csv))
        if not source.cells:
            raise ValueError(f"source CSV {source_csv!s} has no cells")

        n_target = len(source.cells)
        dims = source.get_bounds()
        all_radii = [c.radius for c in source.cells]
        min_r, max_r = min(all_radii), max(all_radii)
        colors = sorted({c.cell_type for c in source.cells})

        if network_mode == "radius":
            resolved_radius = network_radius_um if network_radius_um is not None else 2.5 * max_r
        else:
            resolved_radius = None  # ignored for contact mode

        src_graph = _build_source_graph(
            source,
            analyzer_cls=SpatialNetworkAnalyzer,
            nx_=nx,
            mode=network_mode,
            radius=resolved_radius,
        )

        results: list[IcGenResult] = []
        rep_seed_seq = np.random.SeedSequence(seed).spawn(n_replicates)

        for i in range(n_replicates):
            rep_seed = int(rep_seed_seq[i].generate_state(1, dtype=np.uint32)[0])

            if scaffold_strategy == "uniform_random":
                scaffold = _pack_scaffold_uniform(
                    dims=dims,
                    min_r=min_r,
                    max_r=max_r,
                    n_target=n_target,
                    rep_seed=rep_seed,
                    tissue_section_cls=TissueSection,
                )
            elif scaffold_strategy == "perturb_source":
                scaffold = _perturb_source(
                    source=source,
                    min_r=min_r,
                    dims=dims,
                    rep_seed=rep_seed,
                    cell_cls=Cell,
                    tissue_section_cls=TissueSection,
                )
            else:  # pragma: no cover - pydantic Literal blocks this upstream
                raise ValueError(f"unknown scaffold_strategy: {scaffold_strategy!r}")

            scaffold_analyzer = SpatialNetworkAnalyzer()
            scaffold_graph = scaffold_analyzer.build_network_from_tissue(
                scaffold,
                mode=network_mode,
                radius=resolved_radius,
            )

            gc = GraphColorizer(
                source_graph=src_graph,
                target_graph=scaffold_graph,
                colors=colors,
                seed=rep_seed,
            )
            coloring = gc.colorize(
                initial_temp=resolved_sa.initial_temp,
                final_temp=resolved_sa.final_temp,
                cooling_rate=resolved_sa.cooling_rate,
                max_iterations=resolved_sa.max_iterations,
                verbose=False,
            )
            # colorize returns the dict but not the cost. Recompute via the
            # documented internal helpers so the manifest can carry sa_final_cost
            # for diagnostics.
            final_stats, _ = gc._calculate_statistics(scaffold_graph, coloring)
            sa_final_cost = float(gc._calculate_cost(final_stats))

            for node_idx, cell in enumerate(scaffold.cells):
                cell.cell_type = coloring[node_idx]

            csv_path = out_dir / f"ic_{i:04d}.csv"
            scaffold.export_to_csv(str(csv_path))
            csv_sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()

            counts: dict[str, int] = {c: 0 for c in colors}
            for color in coloring.values():
                counts[color] = counts.get(color, 0) + 1
            achieved = {c: counts[c] / n_target for c in colors}

            results.append(
                IcGenResult(
                    path=csv_path,
                    scaffold_seed=rep_seed,
                    sha256=csv_sha,
                    sa_final_cost=sa_final_cost,
                    achieved_proportions=achieved,
                )
            )

    return results


def _build_source_graph(
    source: Any,
    *,
    analyzer_cls: Any,
    nx_: Any,
    mode: str,
    radius: float | None,
) -> nx.Graph:
    """Build the source graph and copy ``cell_type`` to a ``color`` node attribute.

    ``GraphColorizer`` reads ``color`` on every source node to derive target
    statistics; ``SpatialNetworkAnalyzer.build_network_from_tissue`` sets
    ``cell_type`` (not ``color``), so we mirror it here.
    """
    analyzer = analyzer_cls()
    g = analyzer.build_network_from_tissue(source, mode=mode, radius=radius)
    nx_.set_node_attributes(
        g,
        {node: data["cell_type"] for node, data in g.nodes(data=True)},
        "color",
    )
    return g


def _pack_scaffold_uniform(
    *,
    dims: tuple[float, float, float],
    min_r: float,
    max_r: float,
    n_target: int,
    rep_seed: int,
    tissue_section_cls: Any,
) -> Any:
    """Pack ~``n_target`` cells of a single generic type into ``dims``; matched-N out.

    If the packer overshoots, take a seeded subsample. If it undershoots, retry
    once with a larger budget; if that still fails, raise — the source
    bounding box is too small for the target count.
    """
    height, width, thickness = dims
    budget = 20 * n_target
    for attempt_budget in (budget, 5 * budget):
        scaffold = tissue_section_cls(
            height=height,
            width=width,
            thickness=thickness,
            cell_radii={"x": (min_r, max_r)},
            seed=rep_seed,
        )
        scaffold.generate_cells(
            max_attempts=attempt_budget,
            min_spacing=0.5,
            allow_boundary_cells=True,
        )
        if len(scaffold.cells) >= n_target:
            break
    else:  # pragma: no cover - reached only when packing fails twice
        raise RuntimeError(
            f"source domain too small for target N={n_target}: "
            f"packed only {len(scaffold.cells)} cells after {5 * budget} attempts. "
            "Increase source dimensions or reduce source cell count."
        )

    if len(scaffold.cells) > n_target:
        rng = np.random.default_rng(rep_seed)
        keep_idx = rng.choice(len(scaffold.cells), size=n_target, replace=False)
        scaffold.cells = [scaffold.cells[i] for i in sorted(keep_idx.tolist())]
    return scaffold


def _perturb_source(
    *,
    source: Any,
    min_r: float,
    dims: tuple[float, float, float],
    rep_seed: int,
    cell_cls: Any,
    tissue_section_cls: Any,
) -> Any:
    """Copy source positions, jitter each coord by Normal(0, 0.5 * min_radius)."""
    rng = np.random.default_rng(rep_seed)
    sigma = 0.5 * min_r
    height, width, thickness = dims

    jittered = []
    for cell in source.cells:
        cx, cy, cz = cell.center
        new_center = (
            float(cx + rng.normal(0.0, sigma)),
            float(cy + rng.normal(0.0, sigma)),
            float(cz + rng.normal(0.0, sigma)),
        )
        jittered.append(
            cell_cls(
                center=new_center,
                radius=cell.radius,
                cell_type=cell.cell_type,
                is_boundary=cell.is_boundary,
            )
        )
    return tissue_section_cls.from_cells(
        jittered,
        height=height,
        width=width,
        thickness=thickness,
    )
