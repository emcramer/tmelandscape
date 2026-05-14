"""Step 3.5 — normalise spatial-statistic time series between summarise and embed.

The reference oracle is ``reference/00_abm_normalization.py``. The normalisation
preserves time-effect by re-adding the per-timestep mean after standard scaling.

Two binding invariants from the project owner (ADRs 0006 and 0009):

* **Never overwrite the raw ensemble.** Normalisation always writes to a new
  variable (or a new Zarr store), preserving the immutable raw output of
  step 3 for re-runs with different normalisation strategies.
* **Do not drop features by default.** Earlier iterations of the reference
  oracle stripped six cell-density columns; that choice was specific to one
  application of the method, not a property of the algorithm. The default
  behaviour is to normalise every column the user supplies; column dropping
  is an explicit opt-in.

Modules:

* :mod:`tmelandscape.normalize.within_timestep` — default reference algorithm
  (per-step mean -> power transform -> z-score -> +mean).
* :mod:`tmelandscape.normalize.feature_filter` — explicit, user-supplied
  column-drop helper. No built-in list.
* :mod:`tmelandscape.normalize.alternatives` — global / local-time variants.

This module's public entrypoint is :func:`normalize_ensemble`, the Zarr
orchestrator that reads an input ensemble store, applies the configured
strategy, and writes a *new* output Zarr with both the raw ``value`` array
and a derived ``value_normalized`` array side-by-side.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import xarray as xr

import tmelandscape
from tmelandscape.normalize.within_timestep import normalize_within_timestep

if TYPE_CHECKING:
    from tmelandscape.config.normalize import NormalizeConfig


def normalize_ensemble(
    input_zarr: str | Path,
    output_zarr: str | Path,
    *,
    config: NormalizeConfig,
) -> Path:
    """Read an ensemble Zarr produced by step 3, apply within-timestep
    normalisation, and write a NEW Zarr at ``output_zarr``.

    The input store is treated as read-only — we never write to it, and a
    companion test asserts byte-equality of every file inside it before and
    after this call. If ``output_zarr`` already exists this function raises
    :class:`FileExistsError` *before* opening the input store, so a failed
    pre-existence check leaves nothing on disk.

    Parameters
    ----------
    input_zarr
        Path to the input ensemble Zarr (produced by
        :func:`tmelandscape.summarize.aggregate.build_ensemble_zarr`). Must
        contain a ``value`` array dimensioned
        ``(simulation, timepoint, statistic)``.
    output_zarr
        Path where the new Zarr store should be written. Must not already
        exist — callers must delete an existing store explicitly if intentional
        overwrites are desired (the raw-ensemble immutability invariant means
        we refuse to clobber).
    config
        :class:`tmelandscape.config.normalize.NormalizeConfig` instance.
        Carries the strategy choice, preserve-time-effect flag, drop_columns
        list, fill_nan_with scalar, and output_variable name.

    Returns
    -------
    pathlib.Path
        Absolute path to the newly written Zarr store.

    Raises
    ------
    FileExistsError
        If ``output_zarr`` already exists.
    FileNotFoundError
        If ``input_zarr`` does not exist.
    ValueError
        If the input Zarr is missing the ``value`` data variable, or if any
        ``config.drop_columns`` entry is not present in the input's
        ``statistic`` coordinate.
    """
    input_path = Path(input_zarr).expanduser().resolve()
    output_path = Path(output_zarr).expanduser().resolve()
    output_variable = str(config.output_variable)

    # Defence in depth (Reviewer B2 RISK 6): `output_variable == "value"` would
    # silently shadow the raw passthrough column inside ``data_vars_out``'s
    # dict literal. Stream C's NormalizeConfig validator already forbids this,
    # but the orchestrator must not rely on caller hygiene for a data-loss
    # invariant.
    if output_variable == "value":
        raise ValueError(
            "config.output_variable must not equal 'value'; the raw input "
            "array is preserved under that name and would be silently "
            "overwritten. Choose a different name (default: 'value_normalized')."
        )

    # Fail fast on output pre-existence BEFORE touching the input. Both files
    # and directories count: a partially-written Zarr v3 store is a directory,
    # a stale v2 sentinel might be a file. Either way: refuse cleanly.
    if output_path.exists():
        raise FileExistsError(
            f"output_zarr already exists at {output_path!s}; refusing to overwrite. "
            "Delete it explicitly if you really want to replace it."
        )
    if not input_path.exists():
        raise FileNotFoundError(f"input_zarr does not exist: {input_path!s}")

    # Open the input store as a context manager so chunk-reader handles are
    # released even if `to_zarr` raises mid-write (Reviewer B2 RISK 9).
    with xr.open_zarr(input_path) as ds_in:
        if "value" not in ds_in.data_vars:
            raise ValueError(
                f"input Zarr at {input_path!s} has no 'value' data variable "
                f"(found: {list(ds_in.data_vars)})"
            )

        # Apply drop_columns BEFORE running the algorithm so the algorithm
        # operates on the post-filter array (the user's stated intent).
        drop_columns = list(config.drop_columns)
        if drop_columns:
            stat_values = [str(s) for s in ds_in.coords["statistic"].values.tolist()]
            missing = [c for c in drop_columns if c not in stat_values]
            if missing:
                raise ValueError(
                    f"config.drop_columns entries not present in input statistic coord: {missing}. "
                    f"Available: {stat_values}"
                )
            keep_mask = np.array([s not in set(drop_columns) for s in stat_values], dtype=bool)
            ds_filtered = ds_in.isel(statistic=np.where(keep_mask)[0])
        else:
            ds_filtered = ds_in

        # Materialise the raw value cube and run the normalisation algorithm.
        # `np.asarray` triggers any Dask compute the lazy open left in flight.
        raw_value = np.asarray(ds_filtered["value"].values, dtype=np.float64)
        value_normalized = normalize_within_timestep(
            raw_value,
            preserve_time_effect=config.preserve_time_effect,
            fill_nan_with=config.fill_nan_with,
        )
        value_normalized = np.asarray(value_normalized, dtype=np.float64)
        if value_normalized.shape != raw_value.shape:
            raise RuntimeError(
                f"normalize_within_timestep returned shape {value_normalized.shape}; "
                f"expected {raw_value.shape}"
            )

        # Build the output Dataset by cloning the filtered input's coords and
        # adding the new normalised data variable alongside the raw `value`.
        dims = tuple(ds_filtered["value"].dims)
        coords_out: dict[str, Any] = {}
        for name, coord in ds_filtered.coords.items():
            coords_out[str(name)] = (tuple(coord.dims), np.asarray(coord.values))

        data_vars_out: dict[str, Any] = {
            "value": (dims, raw_value),
            output_variable: (dims, value_normalized),
        }
        ds_out = xr.Dataset(data_vars=data_vars_out, coords=coords_out)

        # Inherit the input's chunk grid for the value data vars (Reviewer B2
        # SMELL 8): keeps the raw and normalised Zarr stores chunk-aligned so
        # downstream Dask reads don't read across mismatched chunk boundaries.
        chunk_spec = _inherit_chunks(ds_in.get("value"), dims)
        if chunk_spec is not None:
            ds_out = ds_out.chunk(chunk_spec)
            # xarray's ``to_zarr`` writes ``encoding['chunks']`` if set; on a
            # freshly-constructed numpy-backed Dataset, encoding inherits the
            # full-axis chunk shape from the source array, which then
            # disagrees with our newly-chunked Dask layout and trips
            # ``safe_chunks``. Clear encoding so the on-disk Zarr chunks
            # match the Dask chunks. Applies to both data vars and any
            # coord array that got rechunked as a side effect of
            # ``Dataset.chunk(...)``.
            for var_name in list(ds_out.data_vars) + list(ds_out.coords):
                ds_out[var_name].encoding = {}

        # Provenance .zattrs.
        attrs: dict[str, Any] = {
            "normalize_config": _serialise_config(config),
            "created_at_utc": datetime.now(UTC).isoformat(),
            "tmelandscape_version": tmelandscape.__version__,
        }
        source_hash = ds_in.attrs.get("manifest_hash")
        if source_hash is not None:
            attrs["source_manifest_hash"] = str(source_hash)
        ds_out.attrs.update(attrs)

        # Ensure parent dir exists; we already established `output_path` doesn't.
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # If `to_zarr` fails mid-write it can leave a partial directory behind,
        # which would then trip the pre-existence guard on the next call.
        # Clean up partial output before re-raising (Reviewer B2 RISK 9).
        try:
            ds_out.to_zarr(output_path, mode="w")
        except Exception:
            if output_path.exists():
                if output_path.is_dir():
                    shutil.rmtree(output_path)
                else:
                    output_path.unlink()
            raise

    return output_path


def _inherit_chunks(
    raw_var: xr.DataArray | None,
    dims: tuple[str, ...],
) -> dict[str, int] | None:
    """Return a `{dim: size}` chunk spec mirroring ``raw_var``'s first chunk
    along each dim, or ``None`` if the source is unchunked or unavailable.

    xarray exposes per-dim chunk tuples via ``.chunks`` (``None`` for
    unchunked dims). We take the first chunk size along each dim — this
    matches the aggregator's preference for a single dominant chunk size per
    axis.
    """
    if raw_var is None:
        return None
    chunks = getattr(raw_var, "chunks", None)
    if chunks is None:
        return None
    spec: dict[str, int] = {}
    for dim, dim_chunks in zip(dims, chunks, strict=False):
        if dim_chunks is None or len(dim_chunks) == 0:
            continue
        spec[dim] = int(dim_chunks[0])
    return spec or None


def _serialise_config(config: NormalizeConfig) -> str:
    """JSON-serialise a NormalizeConfig (or duck-typed stand-in) for .zattrs.

    Stream C's :class:`NormalizeConfig` is a Pydantic ``BaseModel`` and exposes
    ``model_dump_json``. This helper falls back to ``model_dump`` + ``json.dumps``
    so the orchestrator's tests can drive it with a duck-typed stand-in if
    Stream C has not yet landed when the test runs.
    """
    dump_json = getattr(config, "model_dump_json", None)
    if callable(dump_json):
        out = dump_json()
        return out if isinstance(out, str) else json.dumps(out)
    model_dump = getattr(config, "model_dump", None)
    if callable(model_dump):
        return json.dumps(model_dump())
    # Last resort: best-effort dict cast. The cast is unreachable when callers
    # follow the contract (which requires a Pydantic ``NormalizeConfig``); it
    # exists only so a partially-wired Stream C stand-in still serialises.
    return json.dumps(dict(config))


__all__ = ["normalize_ensemble"]
