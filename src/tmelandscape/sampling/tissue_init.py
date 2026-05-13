"""Initial-condition replicate generation via ``tissue_simulator``.

Wraps :class:`tissue_simulator.ReplicateGenerator` so the rest of the package
can ask for *N* CSVs of cell starting positions in a single call, with one
explicit ``seed`` and a target spatial-similarity tolerance.

Reproducibility note
--------------------
``tissue_simulator`` instantiates its own ``numpy.random.default_rng()`` inside
:class:`SpherePacker` and :class:`TissueSection` with **no argument**, so it
ignores ``np.random.seed`` and is non-deterministic by default. To honour the
house-style invariant that all randomness flows through an explicit seed, we
patch ``tissue_simulator.packing.np.random.default_rng`` and
``tissue_simulator.tissue.np.random.default_rng`` for the duration of the call
with a wrapper that injects child seeds from a :class:`numpy.random.SeedSequence`
when invoked with no arguments. Calls that pass an explicit seed (e.g. inside
``ReplicateGenerator``) are forwarded unchanged.
"""

from __future__ import annotations

import sys
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np
import tissue_simulator  # type: ignore[import-untyped]
from tissue_simulator import (
    ReplicateGenerator,
    TissueSection,
    load_target_statistics_from_tissue,
)


def _seeded_default_rng_factory(
    seed: int,
) -> Any:
    """Return a drop-in replacement for ``np.random.default_rng``.

    When called with no arguments the replacement consumes the next child of a
    :class:`SeedSequence` derived from ``seed``; calls that pass a seed of any
    form are forwarded to the real ``default_rng`` untouched.
    """
    real_default_rng = np.random.default_rng
    # Capacity chosen to be larger than the number of unseeded default_rng
    # call-sites in tissue_simulator times the largest reasonable replicate
    # count; 4096 is comfortably more than enough.
    children = iter(np.random.SeedSequence(seed).spawn(4096))

    def patched(*args: Any, **kwargs: Any) -> np.random.Generator:
        if not args and not kwargs:
            return real_default_rng(next(children))
        return real_default_rng(*args, **kwargs)

    return patched


def generate_initial_conditions(
    *,
    n_replicates: int,
    output_dir: str | Path,
    seed: int,
    target_n_cells: int = 500,
    cell_radii_um: tuple[float, float] = (8.0, 12.0),
    tissue_dims_um: tuple[float, float, float] = (400.0, 400.0, 20.0),
    similarity_tolerance: float = 0.10,
) -> list[Path]:
    """Generate ``n_replicates`` CSVs of initial cell positions in ``output_dir``.

    Each replicate is produced by :class:`tissue_simulator.ReplicateGenerator`
    targeting the spatial-interaction statistics of a single bootstrap tissue
    drawn from the same seed. Replicates are accepted once their divergence
    from the bootstrap is below ``similarity_tolerance``.

    Parameters
    ----------
    n_replicates
        Number of replicate tissues to generate.
    output_dir
        Directory into which CSVs are written; created if it does not exist.
    seed
        RNG seed; the same seed yields byte-identical CSV output.
    target_n_cells
        Target total cell count for the bootstrap tissue. Passed through to
        :class:`tissue_simulator.TargetStatistics` as ``target_cell_count``;
        the packer does not strictly enforce it (it stops at the configured
        ``max_attempts``), so treat as a soft target.
    cell_radii_um
        ``(min, max)`` cell radius in micrometres. Used for the single
        ``"cell"`` type the wrapper exposes.
    tissue_dims_um
        ``(height, width, thickness)`` in micrometres.
    similarity_tolerance
        Acceptable per-metric divergence from the bootstrap statistics. Wired
        through to ``ReplicateGenerator.generate_replicates(tolerance=...)``,
        which the upstream package compares against the mean relative
        divergence in *normalised interaction counts*. There is no separate
        upstream parameter named ``similarity_tolerance``.

    Returns
    -------
    list[pathlib.Path]
        Absolute paths of the written CSVs in replicate order. Files are named
        ``ic_0000.csv``, ``ic_0001.csv``, ... (zero-padded to four digits).

    Notes
    -----
    Output CSV columns are exactly those written by
    :meth:`tissue_simulator.TissueSection.export_to_csv`:
    ``x, y, z, radius, cell_type, is_boundary``.
    """
    if n_replicates <= 0:
        raise ValueError(f"n_replicates must be positive, got {n_replicates}")

    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    base_cell_radii = {"cell": cell_radii_um}
    # Generous bootstrap budget: roughly target_n_cells placements per attempt
    # batch is fine; tissue_simulator already retries up to max_attempts.
    max_attempts = max(1000, 10 * target_n_cells)

    with ExitStack() as stack:
        patched_rng = _seeded_default_rng_factory(seed)
        stack.enter_context(
            patch.object(tissue_simulator.packing.np.random, "default_rng", patched_rng)
        )
        stack.enter_context(
            patch.object(tissue_simulator.tissue.np.random, "default_rng", patched_rng)
        )
        # tissue_simulator prints progress to stdout. Route to stderr so callers
        # consuming structured stdout (CLI JSON output, MCP tools) get clean data.
        stack.enter_context(redirect_stdout(sys.stderr))

        bootstrap = TissueSection(
            height=tissue_dims_um[0],
            width=tissue_dims_um[1],
            thickness=tissue_dims_um[2],
            cell_radii=base_cell_radii,
        )
        bootstrap.generate_cells(
            max_attempts=max_attempts,
            min_spacing=0.5,
            allow_boundary_cells=True,
        )
        target = load_target_statistics_from_tissue(bootstrap, network_mode="contact")
        target.target_cell_count = target_n_cells
        # The upstream density estimate counts boundary cells as fully inside
        # the tissue, which can push the value above 1.0 and trip
        # `TargetStatistics.validate()`. We rely on the interaction-statistics
        # divergence instead, so clear the density target.
        target.target_density = None

        generator = ReplicateGenerator(
            target_stats=target,
            tissue_dimensions=tissue_dims_um,
            base_cell_radii=base_cell_radii,
            network_mode="contact",
            seed=seed,
        )
        replicates = generator.generate_replicates(
            num_replicates=n_replicates,
            max_attempts=max_attempts,
            min_spacing=0.5,
            allow_boundary=True,
            max_iterations=5,
            tolerance=similarity_tolerance,
        )

        paths: list[Path] = []
        for i, (tissue, _stats) in enumerate(replicates):
            csv_path = out / f"ic_{i:04d}.csv"
            tissue.export_to_csv(str(csv_path))
            paths.append(csv_path)

    return paths
