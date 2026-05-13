"""Canonical column / dimension names for the ensemble Zarr store.

Step 3 of the pipeline emits a chunked Zarr store with logical dimensions
``(simulation, timepoint, statistic)`` and a single ``value`` variable.
This module pins those names and provides a helper that materialises the
per-simulation coordinate arrays from a :class:`SweepManifest`, so the
aggregator and downstream consumers agree on coord shapes / dtypes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from tmelandscape.sampling.manifest import SweepManifest


#: Logical dimension names for the ensemble Zarr store. Order is contractual:
#: aggregators write ``value`` with this exact axis order so callers can rely
#: on positional reshapes without consulting the dataset metadata.
ENSEMBLE_DIMS: tuple[str, ...] = ("simulation", "timepoint", "statistic")

#: Coord-name prefix for per-simulation parameter columns lifted from the
#: manifest ``SweepRow.parameter_values`` dict.
PARAMETER_COORD_PREFIX: str = "parameter_"


def manifest_to_coords(manifest: SweepManifest) -> dict[str, np.ndarray]:
    """Materialise per-simulation coordinate arrays from a sweep manifest.

    The returned mapping is suitable for splatting into an
    ``xarray.Dataset(coords=...)`` call (each value is 1-D, aligned along the
    ``simulation`` dimension).

    Keys:

    - ``simulation``: ``simulation_id`` strings, one per manifest row.
    - ``ic_id`` / ``parameter_combination_id``: integer arrays aligned with
      ``simulation``.
    - ``parameter_<name>`` for each parameter declared in
      ``manifest.config.parameters``: float64 array of scaled values.

    Parameters
    ----------
    manifest
        The sweep manifest to derive coords from. May contain zero rows; in
        that case every returned array has length zero but the keys (and
        dtypes) are still present so a downstream zero-row Dataset has a
        stable schema.

    Returns
    -------
    dict[str, np.ndarray]
        Coordinate arrays keyed by coord name. Every array has length
        ``len(manifest.rows)``.
    """
    n_rows = len(manifest.rows)
    param_names = [p.name for p in manifest.config.parameters]

    simulation_ids = np.array([row.simulation_id for row in manifest.rows], dtype=np.str_)
    ic_ids = np.array([row.ic_id for row in manifest.rows], dtype=np.int64)
    pc_ids = np.array([row.parameter_combination_id for row in manifest.rows], dtype=np.int64)

    coords: dict[str, np.ndarray] = {
        "simulation": simulation_ids,
        "ic_id": ic_ids,
        "parameter_combination_id": pc_ids,
    }
    for name in param_names:
        # NaN-fill rather than KeyError if a row omits a parameter; the
        # manifest schema allows that and we want a stable column dtype.
        values = np.empty(n_rows, dtype=np.float64)
        for i, row in enumerate(manifest.rows):
            v = row.parameter_values.get(name)
            values[i] = float("nan") if v is None else float(v)
        coords[f"{PARAMETER_COORD_PREFIX}{name}"] = values

    return coords


__all__ = ["ENSEMBLE_DIMS", "PARAMETER_COORD_PREFIX", "manifest_to_coords"]
