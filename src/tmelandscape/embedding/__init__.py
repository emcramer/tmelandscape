"""Step 4 — time-delay (sliding-window) embedding of the normalised ensemble.

Public entrypoint: :func:`embed_ensemble`, a Zarr orchestrator that reads an
ensemble store produced by Phase 3.5 (`normalize_ensemble`) and writes a NEW
Zarr at ``output_zarr`` containing the flattened-window embedding and a
companion per-window per-statistic averages array.

The algorithm itself lives in :mod:`tmelandscape.embedding.sliding_window`;
this module focuses on the I/O contract: input immutability, output
pre-existence guard, chunk inheritance where applicable, partial-output
cleanup, provenance forwarding, and per-window coord broadcasting.

Binding invariants (mirrored from the Phase 3.5 orchestrator and ADR 0006):

* **Never overwrite raw data.** The input Zarr is opened lazily via
  ``xarray.open_zarr`` as a context manager; we never write to it. A
  companion test sha256-walks every file in the store before and after the
  call and asserts byte-equality.
* **Refuse to overwrite output.** If ``output_zarr`` already exists (as a
  directory or as a stale sentinel file), raise :class:`FileExistsError`
  before touching the input.
* **Defence-in-depth on variable-name collisions.** Even though Stream C's
  :class:`~tmelandscape.config.embedding.EmbeddingConfig` validator forbids
  ``output_variable == source_variable``, the orchestrator re-checks the
  invariant so a duck-typed config stand-in can never silently shadow the
  source array on dataset write.
* **Partial-output cleanup.** A mid-write ``to_zarr`` failure is caught,
  the partially-written directory is removed, and the original exception
  re-raised so callers see the real error.
"""

from __future__ import annotations

import json
import shutil
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import xarray as xr

import tmelandscape
from tmelandscape.embedding.sliding_window import (
    WindowedEnsemble,
    window_trajectory_ensemble,
)

if TYPE_CHECKING:
    from tmelandscape.config.embedding import EmbeddingConfig


def embed_ensemble(
    input_zarr: str | Path,
    output_zarr: str | Path,
    *,
    config: EmbeddingConfig,
) -> Path:
    """Read a normalised ensemble Zarr, build the sliding-window embedding,
    and write a NEW Zarr at ``output_zarr``.

    Refuses to overwrite an existing ``output_zarr``. The input store is
    opened lazily and treated as read-only; a companion test asserts the
    input's byte contents are unchanged across the call.

    Parameters
    ----------
    input_zarr
        Path to the input ensemble Zarr (typically the Phase 3.5 output
        carrying a ``value_normalized`` array). Must contain the data
        variable named by ``config.source_variable``.
    output_zarr
        Destination path for the new Zarr store. Must not pre-exist. The
        parent directory is created if needed.
    config
        :class:`~tmelandscape.config.embedding.EmbeddingConfig` (or a
        duck-typed stand-in exposing the same attributes plus
        ``model_dump_json``). The orchestrator reads
        ``window_size``, ``step_size``, ``source_variable``,
        ``output_variable``, ``averages_variable``, and ``drop_statistics``
        off the config.

    Returns
    -------
    pathlib.Path
        Absolute resolved path to the newly written output Zarr store.

    Raises
    ------
    FileExistsError
        If ``output_zarr`` already exists.
    FileNotFoundError
        If ``input_zarr`` does not exist.
    ValueError
        If ``output_variable == source_variable``, if
        ``averages_variable`` collides with another data-var name, if the
        input Zarr is missing the named ``source_variable``, or if any
        entry in ``config.drop_statistics`` is not present in the input's
        ``statistic`` coordinate.
    """
    input_path = Path(input_zarr).expanduser().resolve()
    output_path = Path(output_zarr).expanduser().resolve()

    source_variable = str(config.source_variable)
    output_variable = str(config.output_variable)
    averages_variable = str(config.averages_variable)
    window_size = int(config.window_size)
    step_size = int(config.step_size)
    drop_statistics = list(config.drop_statistics)

    # Defence in depth (mirrors Phase 3.5 RISK 6): Stream C's validator
    # already forbids these collisions, but the orchestrator must not rely
    # on caller hygiene for a data-loss invariant. If a duck-typed config
    # bypasses Pydantic validation, we still refuse the write.
    if output_variable == source_variable:
        raise ValueError(
            f"config.output_variable must not equal config.source_variable "
            f"(both {output_variable!r}); the source array would be silently "
            "shadowed on dataset write. Choose a different output_variable "
            "(default: 'embedding')."
        )
    if averages_variable == source_variable:
        raise ValueError(
            f"config.averages_variable must not equal config.source_variable "
            f"(both {averages_variable!r}); the source array would be silently "
            "shadowed on dataset write."
        )
    if output_variable == averages_variable:
        raise ValueError(
            f"config.output_variable must not equal config.averages_variable "
            f"(both {output_variable!r}); one would silently shadow the other "
            "on dataset write."
        )

    # Fail fast on output pre-existence BEFORE opening the input. A
    # partially-written Zarr v3 store appears as a directory; an older
    # sentinel may be a file. Either way: refuse cleanly.
    if output_path.exists():
        raise FileExistsError(
            f"output_zarr already exists at {output_path!s}; refusing to overwrite. "
            "Delete it explicitly if you really want to replace it."
        )
    if not input_path.exists():
        raise FileNotFoundError(f"input_zarr does not exist: {input_path!s}")

    # Open the input store as a context manager so chunk-reader handles are
    # released even if `to_zarr` raises mid-write (Phase 3.5 RISK 9).
    with xr.open_zarr(input_path) as ds_in:
        if source_variable not in ds_in.data_vars:
            raise ValueError(
                f"input Zarr at {input_path!s} has no {source_variable!r} data "
                f"variable (found: {list(ds_in.data_vars)}). Pass "
                "config.source_variable to point at an available array."
            )

        # Apply drop_statistics BEFORE windowing so the embedding sees the
        # post-filter array, matching the user's stated intent.
        stat_values = [str(s) for s in ds_in.coords["statistic"].values.tolist()]
        if drop_statistics:
            missing = [s for s in drop_statistics if s not in stat_values]
            if missing:
                raise ValueError(
                    f"config.drop_statistics entries not present in input statistic "
                    f"coord: {missing}. Available: {stat_values}"
                )
            keep_mask = np.array([s not in set(drop_statistics) for s in stat_values], dtype=bool)
            ds_filtered = ds_in.isel(statistic=np.where(keep_mask)[0])
        else:
            ds_filtered = ds_in

        # Materialise the source cube. `np.asarray` forces any lazy Dask
        # compute to run now; we want a concrete numpy array because
        # `window_trajectory_ensemble` is a pure-numpy function.
        source_array = np.asarray(ds_filtered[source_variable].values, dtype=np.float64)
        if source_array.ndim != 3:
            raise ValueError(
                f"input {source_variable!r} must be a 3D "
                f"(simulation, timepoint, statistic) array; "
                f"got ndim={source_array.ndim} shape={source_array.shape}"
            )

        # Run the pure-function algorithm. Stream A's contract guarantees a
        # `WindowedEnsemble` dataclass with the per-window index arrays we
        # need for coord broadcasting below.
        result: WindowedEnsemble = window_trajectory_ensemble(
            source_array,
            window_size=window_size,
            step_size=step_size,
        )

        # Resolve the surviving statistic names (post-drop) for the
        # `statistic` coord on the averages variable.
        post_filter_stats = [str(s) for s in ds_filtered.coords["statistic"].values.tolist()]

        # Per-window coord broadcasting. Stream A returns
        # ``simulation_index`` mapping each window back to its source
        # simulation's position along the input ``simulation`` dim. We
        # broadcast every per-simulation coord by numpy-taking along that
        # index — cleaner than building per-sim chunks and concatenating,
        # and correct when sims contribute different numbers of windows.
        sim_index = np.asarray(result.simulation_index, dtype=np.int64)
        n_windows = int(sim_index.shape[0])

        # Build the per-window coord dict. We always emit `simulation_id`
        # so the human-readable sim name follows each window even if the
        # numeric `simulation_index` would be ambiguous after re-orderings.
        sim_ids_full = ds_filtered.coords["simulation"].values
        if n_windows == 0:
            simulation_id_per_window = np.array([], dtype=sim_ids_full.dtype)
        else:
            simulation_id_per_window = np.take(sim_ids_full, sim_index)

        per_window_coords: dict[str, Any] = {
            "simulation_id": ("window", simulation_id_per_window),
            "window_index_in_sim": (
                "window",
                np.asarray(result.window_index_in_sim, dtype=np.int64),
            ),
            "start_timepoint": (
                "window",
                np.asarray(result.start_timepoint, dtype=np.int64),
            ),
            "end_timepoint": (
                "window",
                np.asarray(result.end_timepoint, dtype=np.int64),
            ),
        }

        # Broadcast every other simulation-aligned coord along `window`.
        # We scan the filtered input's coords (not the raw input's) so any
        # `simulation`-axis coord the caller's Phase 3.5 step propagated
        # also flows through here unchanged.
        for coord_name in ds_filtered.coords:
            coord_da = ds_filtered.coords[coord_name]
            # Only broadcast 1D coords aligned to the `simulation` dim;
            # skip the `simulation` dim coord itself (we already emitted
            # `simulation_id` from it) and skip any multi-dim coords like
            # the 2D `time` coord — those are not per-window properties.
            if coord_da.dims != ("simulation",):
                continue
            if str(coord_name) == "simulation":
                continue
            values = np.asarray(coord_da.values)
            if n_windows == 0:
                broadcasted = np.array([], dtype=values.dtype)
            else:
                broadcasted = np.take(values, sim_index)
            per_window_coords[str(coord_name)] = ("window", broadcasted)

        # The `statistic` coord on the averages variable: surviving names
        # post-drop, indexed by the `statistic` dim.
        per_window_coords["statistic"] = ("statistic", np.array(post_filter_stats))

        # Embedding feature index — explicit so users can reconstruct the
        # (window_size, n_statistic) layout from a flat row if they want.
        if n_windows > 0:
            n_features = int(result.embedding.shape[1])
        else:
            n_features = window_size * len(post_filter_stats)
        per_window_coords["embedding_feature"] = (
            "embedding_feature",
            np.arange(n_features, dtype=np.int64),
        )

        # Assemble the output Dataset. We avoid relying on xarray's
        # broadcasting magic and pass explicit (dims, values) tuples so the
        # shape contract is visible at the call site.
        data_vars_out: dict[str, Any] = {
            output_variable: (
                ("window", "embedding_feature"),
                np.asarray(result.embedding, dtype=np.float64),
            ),
            averages_variable: (
                ("window", "statistic"),
                np.asarray(result.averages, dtype=np.float64),
            ),
        }
        ds_out = xr.Dataset(data_vars=data_vars_out, coords=per_window_coords)

        # Provenance .zattrs. We forward source_manifest_hash and
        # source_normalize_config from the input attrs when present so the
        # chain raw -> normalised -> embedding is auditable end-to-end.
        attrs: dict[str, Any] = {
            "embedding_config": _serialise_config(config),
            "source_input_zarr": str(input_path),
            "source_variable": source_variable,
            "window_size": int(window_size),
            "n_skipped_simulations": len(result.skipped_simulations),
            "created_at_utc": datetime.now(UTC).isoformat(),
            "tmelandscape_version": tmelandscape.__version__,
        }
        source_normalize_config = ds_in.attrs.get("normalize_config")
        if source_normalize_config is not None:
            attrs["source_normalize_config"] = str(source_normalize_config)
        source_manifest_hash = ds_in.attrs.get("manifest_hash")
        if source_manifest_hash is not None:
            attrs["source_manifest_hash"] = str(source_manifest_hash)
        else:
            # The Phase 3.5 orchestrator forwards the upstream hash under
            # `source_manifest_hash`; if we are reading from a Phase 3.5
            # output rather than directly from Phase 3, the hash lives
            # under that key already.
            forwarded_hash = ds_in.attrs.get("source_manifest_hash")
            if forwarded_hash is not None:
                attrs["source_manifest_hash"] = str(forwarded_hash)
        ds_out.attrs.update(attrs)

        # If any sims were skipped because they had fewer than
        # `window_size` timepoints, emit a warning naming them. Resolving
        # the name (not just the index) makes the warning actionable.
        skipped = list(result.skipped_simulations)
        if skipped:
            skipped_idx = np.asarray(skipped, dtype=np.int64)
            skipped_names = [str(s) for s in np.take(sim_ids_full, skipped_idx).tolist()]
            warnings.warn(
                "embed_ensemble: "
                f"{len(skipped_names)} simulation(s) had fewer than "
                f"window_size={window_size} timepoints and contributed zero "
                f"windows: {skipped_names}",
                stacklevel=2,
            )

        # Ensure parent dir exists; we already established `output_path` doesn't.
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Wrap to_zarr in try/except so a mid-write failure does not leave
        # a partial directory behind to trip the pre-existence guard on
        # retry (Phase 3.5 RISK 9).
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


def _serialise_config(config: EmbeddingConfig) -> str:
    """JSON-serialise an EmbeddingConfig (or duck-typed stand-in) for .zattrs.

    Stream C's :class:`EmbeddingConfig` is a Pydantic ``BaseModel`` and
    exposes ``model_dump_json``. This helper falls back to ``model_dump``
    + ``json.dumps`` so the orchestrator's tests can drive it with a
    duck-typed stand-in if Stream C has not yet landed when the test runs.
    """
    dump_json = getattr(config, "model_dump_json", None)
    if callable(dump_json):
        out = dump_json()
        return out if isinstance(out, str) else json.dumps(out)
    model_dump = getattr(config, "model_dump", None)
    if callable(model_dump):
        return json.dumps(model_dump())
    # Last resort for SimpleNamespace-style duck-typed stubs in tests
    # (real callers go through Pydantic and hit the branches above).
    # ``vars(...)`` works on SimpleNamespace; ``dict(...)`` does not.
    return json.dumps(vars(config))


__all__ = ["embed_ensemble"]
