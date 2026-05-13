"""Step 1 — parameter sampling + initial-condition replicate generation.

The public entry point is :func:`generate_sweep`, which combines:

* a Latin Hypercube (or alternative) draw over the unit hypercube,
* per-parameter scaling into ``[low, high]`` with ``"linear"`` or ``"log10"``
  spacing,
* ``tissue_simulator``-driven generation of ``n_initial_conditions`` cell-position
  replicates,

into a single :class:`SweepManifest` that the external step-2 (PhysiCell-running)
agent consumes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import numpy as np

from tmelandscape import __version__
from tmelandscape.config.sweep import ParameterSpec, SweepConfig
from tmelandscape.sampling.alternatives import (
    halton_unit_hypercube,
    scipy_lhs_unit_hypercube,
    sobol_unit_hypercube,
)
from tmelandscape.sampling.lhs import lhs_unit_hypercube
from tmelandscape.sampling.manifest import SweepManifest, SweepRow
from tmelandscape.sampling.tissue_init import generate_initial_conditions

__all__ = [
    "ParameterSpec",
    "SweepConfig",
    "SweepManifest",
    "SweepRow",
    "draw_unit_hypercube",
    "generate_initial_conditions",
    "generate_sweep",
]

SamplerName = Literal["pyDOE3", "scipy-lhs", "scipy-sobol", "scipy-halton"]


def draw_unit_hypercube(
    *, sampler: SamplerName, n_samples: int, n_dims: int, seed: int
) -> np.ndarray:
    """Dispatch to the correct backend by ``sampler`` name."""
    if sampler == "pyDOE3":
        return lhs_unit_hypercube(n_samples=n_samples, n_dims=n_dims, seed=seed)
    if sampler == "scipy-lhs":
        return scipy_lhs_unit_hypercube(n_samples=n_samples, n_dims=n_dims, seed=seed)
    if sampler == "scipy-sobol":
        return sobol_unit_hypercube(n_samples=n_samples, n_dims=n_dims, seed=seed)
    if sampler == "scipy-halton":
        return halton_unit_hypercube(n_samples=n_samples, n_dims=n_dims, seed=seed)
    raise ValueError(f"unknown sampler: {sampler!r}")


def _scale(unit: np.ndarray, params: list[ParameterSpec]) -> np.ndarray:
    """Scale a unit-hypercube draw into per-parameter bounds (linear or log10)."""
    out = np.empty_like(unit, dtype=np.float64)
    for j, spec in enumerate(params):
        col = unit[:, j]
        if spec.scale == "linear":
            out[:, j] = spec.low + col * (spec.high - spec.low)
        else:
            low_log = np.log10(spec.low)
            high_log = np.log10(spec.high)
            out[:, j] = 10.0 ** (low_log + col * (high_log - low_log))
    return out


def generate_sweep(
    config: SweepConfig,
    *,
    initial_conditions_dir: str | Path,
    target_n_cells: int = 500,
    cell_radii_um: tuple[float, float] = (8.0, 12.0),
    tissue_dims_um: tuple[float, float, float] = (400.0, 400.0, 20.0),
    similarity_tolerance: float = 0.10,
) -> SweepManifest:
    """Produce a :class:`SweepManifest` from a :class:`SweepConfig`.

    Steps:

    1. Draw ``config.n_parameter_samples`` points in ``[0,1]^d`` with
       :func:`draw_unit_hypercube` (default backend: pyDOE3).
    2. Scale each column into ``[low, high]`` per the matching
       :class:`ParameterSpec` (``linear`` or ``log10`` scale).
    3. Generate ``config.n_initial_conditions`` replicate cell-position CSVs in
       ``initial_conditions_dir`` via :func:`generate_initial_conditions`.
    4. Form the Cartesian product (parameter_combination, initial_condition) of
       size ``n_parameter_samples * n_initial_conditions`` and emit one
       :class:`SweepRow` per combination.

    Parameters
    ----------
    config
        Frozen sweep configuration.
    initial_conditions_dir
        Directory to write IC CSVs into. Created if missing.
    target_n_cells, cell_radii_um, tissue_dims_um, similarity_tolerance
        Passed through to :func:`generate_initial_conditions`.

    Returns
    -------
    SweepManifest
        In-memory manifest. Persist via :meth:`SweepManifest.save`.
    """
    ic_dir = Path(initial_conditions_dir).resolve()

    n_dims = len(config.parameters)
    unit = draw_unit_hypercube(
        sampler=config.sampler,
        n_samples=config.n_parameter_samples,
        n_dims=n_dims,
        seed=config.seed,
    )
    scaled = _scale(unit, config.parameters)

    ic_paths = generate_initial_conditions(
        n_replicates=config.n_initial_conditions,
        output_dir=ic_dir,
        seed=config.seed,
        target_n_cells=target_n_cells,
        cell_radii_um=cell_radii_um,
        tissue_dims_um=tissue_dims_um,
        similarity_tolerance=similarity_tolerance,
    )

    rows: list[SweepRow] = []
    param_names = [p.name for p in config.parameters]
    for combo_id in range(config.n_parameter_samples):
        values = dict(zip(param_names, scaled[combo_id].tolist(), strict=True))
        for ic_id, ic_path in enumerate(ic_paths):
            rows.append(
                SweepRow(
                    simulation_id=f"sim_{combo_id:06d}_ic_{ic_id:03d}",
                    parameter_combination_id=combo_id,
                    ic_id=ic_id,
                    parameter_values=values,
                    ic_path=ic_path.name,
                )
            )

    return SweepManifest(
        config=config,
        initial_conditions_dir=str(ic_dir),
        rows=rows,
        created_at=datetime.now(UTC),
        tmelandscape_version=__version__,
    )
