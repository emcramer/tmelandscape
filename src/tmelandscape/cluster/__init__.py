"""Step 5 — two-stage Leiden + Ward clustering of the windowed embedding.

Public entrypoint: :func:`cluster_ensemble`, a Zarr orchestrator that reads a
windowed-embedding store produced by Phase 4 (``embed_ensemble``) and writes a
NEW Zarr at ``output_zarr`` carrying the per-window cluster labels plus the
intermediate Leiden community labels, cluster-mean vectors, Ward linkage
matrix, and (optionally) the per-candidate metric scores from the
auto-selection sweep.

The algorithm itself lives in :mod:`tmelandscape.cluster.leiden_ward`; the
candidate-k auto-selection lives in :mod:`tmelandscape.cluster.selection`;
:mod:`tmelandscape.cluster.alternatives` carries passthrough / baseline
strategies. This module focuses on the I/O contract: input immutability,
output pre-existence guard, defence-in-depth variable-name collision check,
provenance forwarding, and partial-output cleanup.

Binding invariants (mirrored from the Phase 3.5 / 4 orchestrators and ADRs
0006, 0007, 0010):

* **Never overwrite the windowed-embedding Zarr.** The input is opened lazily
  via :func:`xarray.open_zarr` as a context manager; we never write to it. A
  companion test sha256-walks every file in the store before and after the
  call and asserts byte-equality.
* **Refuse to overwrite output.** If ``output_zarr`` already exists (as a
  directory or as a stale sentinel file), raise :class:`FileExistsError`
  before touching the input.
* **Defence-in-depth on variable-name collisions.** Stream C's
  :class:`~tmelandscape.config.cluster.ClusterConfig` validator already
  forbids duplicate variable names, but the orchestrator re-checks the
  invariant so a duck-typed config stand-in cannot silently shadow data on
  dataset write.
* **No silent ``n_final_clusters`` default.** When the config leaves
  ``n_final_clusters=None`` the algorithm auto-selects ``k`` via
  ``cluster_count_metric``; the per-candidate scores land in the output
  Zarr so a re-runner can audit the choice (ADR 0010).
* **Partial-output cleanup.** A mid-write ``to_zarr`` failure is caught, the
  partially-written directory is removed, and the original exception
  re-raised so callers see the real error.
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
from tmelandscape.cluster.leiden_ward import ClusterResult, cluster_leiden_ward
from tmelandscape.utils.logging import get_logger

if TYPE_CHECKING:
    from tmelandscape.config.cluster import ClusterConfig

_log = get_logger(__name__)


def cluster_ensemble(
    input_zarr: str | Path,
    output_zarr: str | Path,
    *,
    config: ClusterConfig,
) -> Path:
    """Read a windowed-embedding Zarr (from Phase 4), run two-stage Leiden +
    Ward clustering, and write a NEW Zarr at ``output_zarr``.

    Refuses to overwrite an existing ``output_zarr``. The input store is
    opened lazily and treated as read-only; a companion test asserts the
    input's byte contents are unchanged across the call.

    Parameters
    ----------
    input_zarr
        Path to the input windowed-embedding Zarr (typically the Phase 4
        output carrying an ``embedding`` array of shape
        ``(window, embedding_feature)`` plus optionally
        ``window_averages``). Must contain the data variable named by
        ``config.source_variable``.
    output_zarr
        Destination path for the new Zarr store. Must not pre-exist. The
        parent directory is created if needed.
    config
        :class:`~tmelandscape.config.cluster.ClusterConfig` (or a
        duck-typed stand-in exposing the same attributes plus
        ``model_dump_json``). The orchestrator reads all algorithm knobs
        and output variable names off this object.

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
        If any pair of the six output data-var names collides with another
        (including ``source_variable``), if the input Zarr is missing the
        named ``source_variable``, or if the named source array is not 2D.
    """
    input_path = Path(input_zarr).expanduser().resolve()
    output_path = Path(output_zarr).expanduser().resolve()

    source_variable = str(config.source_variable)
    leiden_labels_variable = str(config.leiden_labels_variable)
    final_labels_variable = str(config.final_labels_variable)
    cluster_means_variable = str(config.cluster_means_variable)
    linkage_variable = str(config.linkage_variable)
    cluster_count_scores_variable = str(config.cluster_count_scores_variable)

    # Defence in depth: Stream C's ClusterConfig validator forbids duplicate
    # variable names across the six-way set, but the orchestrator must not
    # rely on caller hygiene for a data-loss invariant. A duck-typed config
    # bypassing Pydantic must still be caught here.
    _check_variable_collisions(
        source_variable=source_variable,
        leiden_labels_variable=leiden_labels_variable,
        final_labels_variable=final_labels_variable,
        cluster_means_variable=cluster_means_variable,
        linkage_variable=linkage_variable,
        cluster_count_scores_variable=cluster_count_scores_variable,
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

    knn_neighbors = config.knn_neighbors
    leiden_partition = str(config.leiden_partition)
    leiden_resolution = float(config.leiden_resolution)
    leiden_seed = int(config.leiden_seed)
    n_final_clusters = config.n_final_clusters
    cluster_count_metric = str(config.cluster_count_metric)
    cluster_count_min = int(config.cluster_count_min)
    cluster_count_max = config.cluster_count_max

    _log.info(
        "cluster_ensemble.start",
        input_zarr=str(input_path),
        output_zarr=str(output_path),
        source_variable=source_variable,
        leiden_partition=leiden_partition,
        leiden_resolution=leiden_resolution,
        leiden_seed=leiden_seed,
        n_final_clusters=n_final_clusters,
        cluster_count_metric=cluster_count_metric,
    )

    # Open the input store as a context manager so chunk-reader handles are
    # released even if `to_zarr` raises mid-write.
    with xr.open_zarr(input_path) as ds_in:
        if source_variable not in ds_in.data_vars:
            raise ValueError(
                f"input Zarr at {input_path!s} has no {source_variable!r} data "
                f"variable (available variables: {list(ds_in.data_vars)}). Pass "
                "config.source_variable to point at an available array."
            )

        embedding_da = ds_in[source_variable]
        if embedding_da.ndim != 2:
            raise ValueError(
                f"input {source_variable!r} must be a 2D "
                f"(window, embedding_feature) array; "
                f"got ndim={embedding_da.ndim} shape={embedding_da.shape}"
            )

        # Materialise the embedding to a concrete numpy array — the pure
        # algorithm in leiden_ward expects a numpy buffer, and we want any
        # lazy Dask compute to run now rather than during to_zarr. Float64
        # is the algorithm's working dtype; a float32 input upstream is
        # upcast both for the algorithm call and for the output passthrough
        # (the output `embedding` variable is float64 regardless of input
        # dtype). Input bytes on disk are untouched — the upcast lives only
        # in the new output store.
        embedding_array = np.asarray(embedding_da.values, dtype=np.float64)

        result: ClusterResult = cluster_leiden_ward(
            embedding_array,
            knn_neighbors=knn_neighbors,
            leiden_partition=leiden_partition,
            leiden_resolution=leiden_resolution,
            leiden_seed=leiden_seed,
            n_final_clusters=n_final_clusters,
            cluster_count_metric=cluster_count_metric,
            cluster_count_min=cluster_count_min,
            cluster_count_max=cluster_count_max,
        )

        if result.linkage_matrix.ndim != 2 or result.linkage_matrix.shape[1] != 4:
            raise RuntimeError(
                "algorithm returned an unexpected linkage_matrix shape "
                f"{result.linkage_matrix.shape}; expected (n_leiden_clusters-1, 4) "
                "from scipy.cluster.hierarchy.linkage. Please file a bug."
            )

        # leiden_to_final is intentionally not surfaced in the output Zarr:
        # the mapping is already collapsed into per-window `final_labels`
        # via `leiden_to_final[leiden_labels]` inside the algorithm. Reading
        # it back out post-hoc would require recomputing the dendrogram cut.

        ds_out = _build_output_dataset(
            ds_in=ds_in,
            result=result,
            source_variable=source_variable,
            leiden_labels_variable=leiden_labels_variable,
            final_labels_variable=final_labels_variable,
            cluster_means_variable=cluster_means_variable,
            linkage_variable=linkage_variable,
            cluster_count_scores_variable=cluster_count_scores_variable,
        )

        # Provenance .zattrs. Forward source_embedding_config /
        # source_normalize_config / source_manifest_hash from the input attrs
        # when present so the chain raw -> normalised -> embedding ->
        # clustering is auditable end-to-end.
        attrs: dict[str, Any] = {
            "cluster_config": _serialise_config(config),
            "n_leiden_clusters": int(result.n_leiden_clusters),
            "knn_neighbors_used": int(result.knn_neighbors_used),
            "n_final_clusters_used": int(result.n_final_clusters_used),
            "cluster_count_metric_used": str(result.cluster_count_metric_used),
            "source_input_zarr": str(input_path),
            "source_variable": source_variable,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "tmelandscape_version": tmelandscape.__version__,
        }
        for forwarded in (
            "source_embedding_config",
            "source_normalize_config",
            "source_manifest_hash",
        ):
            forwarded_value = ds_in.attrs.get(forwarded)
            if forwarded_value is not None:
                attrs[forwarded] = str(forwarded_value)
        # If the upstream embedding Zarr stored its own config under
        # ``embedding_config`` rather than ``source_embedding_config``, lift
        # it under the forwarded-name key so the chain stays auditable.
        if "source_embedding_config" not in attrs:
            upstream_embed_cfg = ds_in.attrs.get("embedding_config")
            if upstream_embed_cfg is not None:
                attrs["source_embedding_config"] = str(upstream_embed_cfg)

        ds_out.attrs.update(attrs)

        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            ds_out.to_zarr(output_path, mode="w")
        except Exception:
            if output_path.exists():
                if output_path.is_dir():
                    shutil.rmtree(output_path)
                else:
                    output_path.unlink()
            raise

    _log.info(
        "cluster_ensemble.done",
        output_zarr=str(output_path),
        n_leiden_clusters=int(result.n_leiden_clusters),
        n_final_clusters_used=int(result.n_final_clusters_used),
        cluster_count_metric_used=str(result.cluster_count_metric_used),
    )

    return output_path


def _check_variable_collisions(
    *,
    source_variable: str,
    leiden_labels_variable: str,
    final_labels_variable: str,
    cluster_means_variable: str,
    linkage_variable: str,
    cluster_count_scores_variable: str,
) -> None:
    """Raise ``ValueError`` if any of the six variable names collide.

    Mirrors the Pydantic validator on ``ClusterConfig`` so duck-typed configs
    cannot bypass the check. All six names share the output Dataset's
    ``data_vars`` dict; a collision would silently drop one entry on write.
    """
    names = [
        source_variable,
        leiden_labels_variable,
        final_labels_variable,
        cluster_means_variable,
        linkage_variable,
        cluster_count_scores_variable,
    ]
    if len(set(names)) != len(names):
        duplicates = sorted({n for n in names if names.count(n) > 1})
        raise ValueError(
            "cluster_ensemble: variable names must all be distinct across "
            "source_variable, leiden_labels_variable, final_labels_variable, "
            "cluster_means_variable, linkage_variable, and "
            f"cluster_count_scores_variable; duplicates: {duplicates}. "
            "Any collision would silently shadow an output array on "
            "dataset write."
        )


def _build_output_dataset(
    *,
    ds_in: xr.Dataset,
    result: ClusterResult,
    source_variable: str,
    leiden_labels_variable: str,
    final_labels_variable: str,
    cluster_means_variable: str,
    linkage_variable: str,
    cluster_count_scores_variable: str,
) -> xr.Dataset:
    """Assemble the output ``xr.Dataset`` from the input passthroughs plus
    the new cluster arrays.

    The embedding array is copied through verbatim so downstream consumers
    can compare raw-vs-clustered without re-opening the upstream Zarr.
    ``window_averages``, when present in the input, is also passed through.
    Per-``window`` coords from the input flow into the output unchanged.
    """
    embedding_da = ds_in[source_variable]
    embedding_dims: tuple[str, ...] = tuple(str(d) for d in embedding_da.dims)

    # Coordinates: keep every input coord aligned to a passthrough dim
    # (``window`` and ``embedding_feature``, plus ``statistic`` when the
    # input carries window_averages). New coord for cluster_count_candidate.
    coords_out: dict[str, Any] = {}
    passthrough_dims: set[str] = set(embedding_dims)
    has_window_averages = "window_averages" in ds_in.data_vars
    if has_window_averages:
        passthrough_dims.update(str(d) for d in ds_in["window_averages"].dims)

    for name, coord in ds_in.coords.items():
        coord_dims = tuple(str(d) for d in coord.dims)
        if not set(coord_dims).issubset(passthrough_dims):
            continue
        coords_out[str(name)] = (coord_dims, np.asarray(coord.values))

    coords_out["cluster_count_candidate"] = (
        "cluster_count_candidate",
        np.asarray(result.cluster_count_candidates, dtype=np.int64),
    )

    data_vars_out: dict[str, Any] = {
        source_variable: (
            embedding_dims,
            np.asarray(embedding_da.values, dtype=np.float64),
        ),
        leiden_labels_variable: (
            ("window",),
            np.asarray(result.leiden_labels, dtype=np.int64),
        ),
        final_labels_variable: (
            ("window",),
            np.asarray(result.final_labels, dtype=np.int64),
        ),
        cluster_means_variable: (
            ("leiden_cluster", "embedding_feature"),
            np.asarray(result.leiden_cluster_means, dtype=np.float64),
        ),
        linkage_variable: (
            ("linkage_step", "linkage_field"),
            np.asarray(result.linkage_matrix, dtype=np.float64),
        ),
        cluster_count_scores_variable: (
            ("cluster_count_candidate",),
            np.asarray(result.cluster_count_scores, dtype=np.float64),
        ),
    }

    if has_window_averages:
        wa = ds_in["window_averages"]
        data_vars_out["window_averages"] = (
            tuple(str(d) for d in wa.dims),
            np.asarray(wa.values),
        )

    return xr.Dataset(data_vars=data_vars_out, coords=coords_out)


def _serialise_config(config: ClusterConfig) -> str:
    """JSON-serialise a ClusterConfig (or duck-typed stand-in) for .zattrs.

    Stream C's :class:`ClusterConfig` is a Pydantic ``BaseModel`` and
    exposes ``model_dump_json``. This helper falls back to ``model_dump`` +
    ``json.dumps`` so the orchestrator's tests can drive it with a
    duck-typed stand-in if Stream C has not yet landed when the test runs.
    """
    dump_json = getattr(config, "model_dump_json", None)
    if callable(dump_json):
        out = dump_json()
        return out if isinstance(out, str) else json.dumps(out)
    model_dump = getattr(config, "model_dump", None)
    if callable(model_dump):
        return json.dumps(model_dump())
    # Last resort: best-effort dict cast. Real callers go through Pydantic
    # and hit one of the branches above; this exists so a partially-wired
    # Stream C stand-in (e.g. SimpleNamespace) still serialises.
    return json.dumps(vars(config))


__all__ = ["cluster_ensemble"]
