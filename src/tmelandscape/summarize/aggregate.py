"""Aggregate per-simulation summary frames into a chunked Zarr store.

Public entrypoint: :func:`build_ensemble_zarr`. Stacks the long-form
DataFrames returned by ``summarize_simulation`` into a single
``(simulation, timepoint, statistic)`` Dataset and writes it as a Zarr store
that round-trips cleanly through :func:`xarray.open_zarr`.

Implementation notes
--------------------

We build an :class:`xarray.Dataset` and call its ``to_zarr`` method (rather
than driving raw ``zarr`` arrays) because xarray handles the dimension-scale
metadata, coordinate variables, and NaN fill semantics needed for the
round-trip contract. Chunking is applied via ``Dataset.chunk`` immediately
before writing so the on-disk chunk grid matches the caller's
``chunk_simulations`` / ``chunk_timepoints`` / ``chunk_statistics`` args.

Provenance is attached as Dataset attributes (``.zattrs`` on the resulting
store): ``tmelandscape_version``, ``manifest_hash`` (sha256 over
``manifest.model_dump_json()``), ``created_at_utc``, and the serialised
``SummarizeConfig``.

The contract intentionally uses a forward reference to ``SummarizeConfig``
so this module can be imported before Stream C's ``config/summarize.py``
lands.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import xarray as xr

import tmelandscape
from tmelandscape.summarize.schema import ENSEMBLE_DIMS, manifest_to_coords

if TYPE_CHECKING:
    from tmelandscape.config.summarize import SummarizeConfig
    from tmelandscape.sampling.manifest import SweepManifest


def _resolve_chunk(value: int, axis_len: int) -> int:
    """Translate a user-facing chunk arg into a concrete chunk size.

    A value of ``-1`` (the contract sentinel for "one chunk along this axis")
    is translated to ``axis_len``. A value of ``0`` is undefined and rejected
    eagerly. Otherwise, the chunk size is clamped to ``axis_len`` so callers
    can pass e.g. ``chunk_simulations=32`` on a 4-sim manifest without ending
    up with an empty trailing chunk.

    For a zero-length axis we still return at least ``1`` because Zarr does
    not accept chunk size 0 even when the array itself is empty.
    """
    if value == 0:
        raise ValueError("chunk size must be a positive integer or -1 (full axis)")
    if value == -1:
        return max(axis_len, 1)
    if value < -1:
        raise ValueError("chunk size must be a positive integer or -1 (full axis)")
    return max(min(value, axis_len), 1)


def _collect_timepoints(summary_frames: dict[str, pd.DataFrame]) -> np.ndarray:
    """Union of ``time_index`` values across every summary frame.

    Sorted ascending. Returned as int64. Empty frames / empty dict produce a
    zero-length array.
    """
    seen: set[int] = set()
    for df in summary_frames.values():
        if df.empty or "time_index" not in df.columns:
            continue
        seen.update(int(t) for t in df["time_index"].to_numpy())
    return np.array(sorted(seen), dtype=np.int64)


def _collect_statistics(summary_frames: dict[str, pd.DataFrame]) -> np.ndarray:
    """Union of ``statistic`` names across every summary frame.

    Sorted lexicographically for determinism. Returned as numpy unicode.
    """
    seen: set[str] = set()
    for df in summary_frames.values():
        if df.empty or "statistic" not in df.columns:
            continue
        seen.update(str(s) for s in df["statistic"].to_numpy())
    return np.array(sorted(seen), dtype=np.str_)


def _frame_to_slab(
    df: pd.DataFrame,
    timepoints: np.ndarray,
    statistics: np.ndarray,
) -> np.ndarray:
    """Pivot one long-form summary frame to a ``(timepoint, statistic)`` slab.

    Missing ``(time_index, statistic)`` combinations are filled with NaN, so a
    "ragged" simulation (e.g. one that didn't reach the last few timepoints)
    contributes NaN rows along ``timepoint`` without crashing the aggregator.
    """
    slab = np.full((len(timepoints), len(statistics)), np.nan, dtype=np.float64)
    if df.empty:
        return slab

    tp_index = {int(t): i for i, t in enumerate(timepoints)}
    stat_index = {str(s): i for i, s in enumerate(statistics)}

    # Vectorised lookup beats df.pivot here because the long-form frame may
    # contain duplicate (time_index, statistic) pairs only across simulations
    # — never within a single sim — so a plain assignment is correct.
    tp_idx = df["time_index"].map(tp_index).to_numpy()
    stat_idx = df["statistic"].map(stat_index).to_numpy()
    values = df["value"].to_numpy(dtype=np.float64)
    slab[tp_idx, stat_idx] = values
    return slab


def _serialise_config(config: SummarizeConfig | None) -> str | None:
    """Best-effort JSON dump of the SummarizeConfig for the provenance attrs.

    The aggregator must keep working before Stream C lands ``SummarizeConfig``,
    so the parameter is optional. When provided, we prefer the Pydantic
    ``model_dump_json`` API but fall back to ``json.dumps`` on the model's
    dict representation if the caller hands us something with a ``model_dump``
    method (e.g. a subclass).
    """
    if config is None:
        return None
    dump_json = getattr(config, "model_dump_json", None)
    if callable(dump_json):
        out = dump_json()
        return out if isinstance(out, str) else json.dumps(out)
    model_dump = getattr(config, "model_dump", None)
    if callable(model_dump):
        return json.dumps(model_dump())
    return json.dumps(dict(config))


def build_ensemble_zarr(
    manifest: SweepManifest,
    summary_frames: dict[str, pd.DataFrame],
    output_zarr: str | Path,
    *,
    chunk_simulations: int = 32,
    chunk_timepoints: int = -1,
    chunk_statistics: int = -1,
    config: SummarizeConfig | None = None,
) -> Path:
    """Aggregate per-simulation summary DataFrames into one chunked Zarr store.

    Parameters
    ----------
    manifest
        The :class:`SweepManifest` that drove the simulations. Its rows
        define the ``simulation`` axis order and the per-simulation
        coordinate arrays (``ic_id``, ``parameter_combination_id``,
        ``parameter_<name>`` values).
    summary_frames
        Mapping ``simulation_id -> long-form DataFrame`` as returned by
        :func:`tmelandscape.summarize.spatialtissuepy_driver.summarize_simulation`.
        Required columns: ``time_index`` (int), ``statistic`` (str),
        ``value`` (float). A ``time`` column may be present and is
        propagated as the ``time`` coord (taking the first frame that
        carries it as the source-of-truth); it is not required.
        Frames may be omitted or empty; the corresponding simulation row
        contributes all-NaN along its ``timepoint x statistic`` slab.
    output_zarr
        Destination directory for the Zarr store. Parent dirs are created
        as needed. An existing store at this path is overwritten.
    chunk_simulations, chunk_timepoints, chunk_statistics
        Chunk sizes along each axis. Use ``-1`` (default for timepoint /
        statistic) to make that axis a single chunk; otherwise the value is
        clamped to the axis length so users can pass ``32`` on a 4-sim
        manifest without producing an empty trailing chunk.
    config
        Optional :class:`SummarizeConfig`. When provided, its JSON dump is
        recorded under ``.zattrs['summarize_config']`` for provenance.

    Returns
    -------
    pathlib.Path
        Absolute path to the written Zarr store.
    """
    coords = manifest_to_coords(manifest)
    simulation_ids = coords["simulation"]
    timepoints = _collect_timepoints(summary_frames)
    statistics = _collect_statistics(summary_frames)

    n_sim = len(simulation_ids)
    n_tp = len(timepoints)
    n_stat = len(statistics)

    # Build the (simulation, timepoint, statistic) value cube. NaN by default
    # so simulations that lack a frame, or that didn't reach a given
    # timepoint, surface as NaN rather than silently zero.
    value = np.full((n_sim, n_tp, n_stat), np.nan, dtype=np.float64)
    for i, sim_id in enumerate(simulation_ids):
        df = summary_frames.get(str(sim_id))
        if df is None or df.empty:
            continue
        value[i] = _frame_to_slab(df, timepoints, statistics)

    # 2D ``time`` coord aligned to ``(simulation, timepoint)``. Different
    # simulations may emit different wall-clock times for the same
    # ``time_index`` (e.g. different PhysiCell ``dt`` settings); storing
    # ``time`` as a 2D coord preserves the per-sim trajectory truthfully
    # rather than silently picking the first frame.
    time_coord: np.ndarray | None = None
    if n_tp > 0 and n_sim > 0:
        any_time_data = False
        time_coord = np.full((n_sim, n_tp), np.nan, dtype=np.float64)
        tp_index = {int(t): i for i, t in enumerate(timepoints)}
        for i, sim_id in enumerate(simulation_ids):
            df = summary_frames.get(str(sim_id))
            if df is None or df.empty or "time" not in df.columns:
                continue
            any_time_data = True
            for t_idx, t_val in zip(
                df["time_index"].to_numpy(), df["time"].to_numpy(), strict=True
            ):
                slot = tp_index.get(int(t_idx))
                if slot is not None:
                    time_coord[i, slot] = float(t_val)
        if not any_time_data:
            time_coord = None

    # Assemble the xarray Dataset. The simulation-aligned coords from the
    # manifest (parameter_<name>, ic_id, parameter_combination_id) are added
    # as non-dim coords on the `simulation` axis.
    sim_coord_keys = [k for k in coords if k != "simulation"]
    ds_coords: dict[str, Any] = {
        "simulation": simulation_ids,
        "timepoint": timepoints,
        "statistic": statistics,
    }
    for k in sim_coord_keys:
        ds_coords[k] = ("simulation", coords[k])
    if time_coord is not None:
        ds_coords["time"] = (("simulation", "timepoint"), time_coord)

    ds = xr.Dataset(
        data_vars={"value": (ENSEMBLE_DIMS, value)},
        coords=ds_coords,
    )

    # Provenance attrs. manifest_hash is computed over the canonical Pydantic
    # JSON dump so re-loading the manifest from disk and re-hashing it
    # yields the same digest.
    manifest_json = manifest.model_dump_json()
    manifest_hash = hashlib.sha256(manifest_json.encode("utf-8")).hexdigest()
    config_json = _serialise_config(config)
    attrs: dict[str, Any] = {
        "tmelandscape_version": tmelandscape.__version__,
        "manifest_hash": manifest_hash,
        "created_at_utc": datetime.now(UTC).isoformat(),
    }
    if config_json is not None:
        attrs["summarize_config"] = config_json
    ds.attrs.update(attrs)

    # Resolve chunks. Each axis is at least 1 wide so Zarr accepts the spec
    # even when the corresponding axis is empty.
    chunks = {
        "simulation": _resolve_chunk(chunk_simulations, n_sim),
        "timepoint": _resolve_chunk(chunk_timepoints, n_tp),
        "statistic": _resolve_chunk(chunk_statistics, n_stat),
    }
    ds = ds.chunk(chunks)

    output_path = Path(output_zarr).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_zarr(output_path, mode="w")

    return output_path


__all__ = ["build_ensemble_zarr"]
