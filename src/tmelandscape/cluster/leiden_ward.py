"""Two-stage Leiden + Ward clustering on a time-delay-embedding matrix.

Reference oracle: ``reference/01_abm_generate_embedding.py`` lines ~519-720.
See ADR 0007 (two-stage Leiden + Ward) and ADR 0010 (auto-selection of
``n_final_clusters``).

Algorithm summary
-----------------

1. **Stage 1 — kNN graph + Leiden community detection.**

   * Build an undirected kNN graph over ``embedding`` rows with
     ``sklearn.neighbors.kneighbors_graph(metric="euclidean",
     mode="connectivity", include_self=False)``.
   * Convert the sparse adjacency to an ``igraph.Graph`` (undirected),
     then set every edge weight to ``1.0`` so leidenalg runs on the
     unweighted graph — mirroring the reference.
   * Run ``leidenalg.find_partition`` with the user-selected partition
     class (``CPM`` by default, matching the reference) at
     ``resolution_parameter=leiden_resolution`` and ``seed=leiden_seed``.
   * Membership ids are the Stage-1 per-row labels (Leiden community
     ids, sorted ascending starting at 0).

2. **Stage 2 — Ward hierarchical clustering on Leiden cluster means.**

   * Compute one mean embedding vector per Leiden community (ordered by
     ascending community id).
   * ``pdist(means, metric="euclidean")`` ⇒
     ``linkage(D, method="ward")``.
   * Cut at ``k = n_final_clusters`` via
     ``fcluster(Z, t=k, criterion="maxclust")``; the resulting integer
     labels (1..k) are the Leiden → final mapping. Per-window final
     labels are derived via ``leiden_to_final[leiden_labels]``.

3. **Auto-selection of ``n_final_clusters`` (new in v0.6.0).**

   When the caller passes ``n_final_clusters=None`` the function
   delegates to :func:`tmelandscape.cluster.selection.select_n_clusters`
   over the requested candidate range, then cuts the dendrogram at the
   chosen ``k``. The per-candidate metric scores and the chosen ``k``
   are recorded on the result for provenance.

The Leiden + Ward core matches the reference exactly. The auto-selection
layer is a tmelandscape addition that sits on top of the reference.

This module is **pure**: no I/O, no global RNG, no mutation of the input
``embedding`` array. All randomness is plumbed through ``leiden_seed``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import igraph as ig
import leidenalg as la
import numpy as np
import scipy.cluster.hierarchy as sch
import scipy.spatial.distance as spd
from numpy.typing import NDArray
from sklearn.neighbors import kneighbors_graph

from tmelandscape.cluster.selection import select_n_clusters

_PARTITION_CLASSES: dict[str, type[Any]] = {
    "CPM": la.CPMVertexPartition,
    "Modularity": la.ModularityVertexPartition,
    "RBConfiguration": la.RBConfigurationVertexPartition,
}


@dataclass
class ClusterResult:
    """Result of two-stage Leiden + Ward clustering.

    Attributes
    ----------
    leiden_labels
        ``(n_window,)`` integer array — Leiden community id for each
        row of ``embedding``. Ids are 0-based and contiguous.
    final_labels
        ``(n_window,)`` integer array — Ward-cut final cluster label for
        each row. Labels are 1-based (``1..n_final_clusters_used``) to
        match ``scipy.cluster.hierarchy.fcluster`` semantics.
    leiden_cluster_means
        ``(n_leiden_clusters, n_feature)`` float64 array — one row per
        Leiden community (ordered by ascending community id), holding
        that community's mean embedding vector.
    linkage_matrix
        ``((n_leiden_clusters - 1), 4)`` float64 array — the Ward
        linkage matrix in scipy's standard format.
    leiden_to_final
        ``(n_leiden_clusters,)`` integer array — for each Leiden
        community id ``c``, ``leiden_to_final[c]`` is the final-cluster
        label assigned by the Ward cut.
    n_leiden_clusters
        Number of distinct Leiden communities found in Stage 1.
    knn_neighbors_used
        The ``k`` actually used for the kNN graph (after applying the
        ``int(sqrt(n_window))`` heuristic when ``knn_neighbors=None``).
    n_final_clusters_used
        The ``k`` actually used to cut the Ward dendrogram — either the
        caller-supplied value or the value chosen by auto-selection.
    cluster_count_metric_used
        ``"user_supplied"`` when the caller supplied ``n_final_clusters``
        explicitly; otherwise the metric name (``"wss_elbow"``,
        ``"calinski_harabasz"``, or ``"silhouette"``).
    cluster_count_candidates
        ``(n_candidates,)`` integer array of the candidate k's evaluated
        during auto-selection. Empty length-0 array when the caller
        supplied ``n_final_clusters`` explicitly.
    cluster_count_scores
        ``(n_candidates,)`` float array of metric values at each
        candidate k. Empty length-0 array when the caller supplied
        ``n_final_clusters`` explicitly. Aligned with
        ``cluster_count_candidates``.
    """

    leiden_labels: NDArray[np.int_]
    final_labels: NDArray[np.int_]
    leiden_cluster_means: NDArray[np.float64]
    linkage_matrix: NDArray[np.float64]
    leiden_to_final: NDArray[np.int_]
    n_leiden_clusters: int
    knn_neighbors_used: int
    n_final_clusters_used: int
    cluster_count_metric_used: str
    cluster_count_candidates: NDArray[np.int_]
    cluster_count_scores: NDArray[np.float64]


def cluster_leiden_ward(
    embedding: np.ndarray,
    *,
    knn_neighbors: int | None,
    leiden_partition: str = "CPM",
    leiden_resolution: float = 1.0,
    leiden_seed: int = 42,
    n_final_clusters: int | None,
    cluster_count_metric: str = "wss_elbow",
    cluster_count_min: int = 2,
    cluster_count_max: int | None = None,
) -> ClusterResult:
    """Two-stage Leiden + Ward clustering of an embedding matrix.

    Parameters
    ----------
    embedding
        ``(n_window, n_feature)`` float array. Each row is one window
        in the time-delay embedding from Phase 4.
    knn_neighbors
        ``k`` for the kNN graph. ``None`` ⇒ ``int(sqrt(n_window))`` per
        the reference heuristic. Stored on the result as
        ``knn_neighbors_used`` so callers can introspect what the
        heuristic chose.
    leiden_partition
        Which leidenalg partition type to use. One of:

        - ``"CPM"`` → ``leidenalg.CPMVertexPartition`` (reference).
        - ``"Modularity"`` → ``leidenalg.ModularityVertexPartition``.
        - ``"RBConfiguration"`` → ``leidenalg.RBConfigurationVertexPartition``.

        Any other value raises ``ValueError``.
    leiden_resolution
        ``resolution_parameter`` passed to ``leidenalg.find_partition``.
        Default ``1.0`` matches the reference.
    leiden_seed
        Seed passed to ``leidenalg.find_partition``. The reference uses
        ``42``.
    n_final_clusters
        Number of final clusters to cut the Ward dendrogram into. If an
        integer, must satisfy ``2 <= n_final_clusters <= n_leiden_clusters``;
        otherwise ``ValueError`` is raised. If ``None``, the value is
        auto-selected via ``cluster_count_metric`` over the candidate
        range ``[cluster_count_min, min(cluster_count_max or 20,
        n_leiden_clusters)]``.
    cluster_count_metric
        Selection metric used when ``n_final_clusters is None``. One of
        ``"wss_elbow"`` (default), ``"calinski_harabasz"``, or
        ``"silhouette"``. See
        :func:`tmelandscape.cluster.selection.select_n_clusters`.
    cluster_count_min, cluster_count_max
        Inclusive bounds for the candidate-k range used by
        auto-selection. ``cluster_count_max=None`` ⇒
        ``min(12, n_leiden_clusters)`` (the biologically interpretable
        upper bound for TME states; the cap lives in
        :func:`tmelandscape.cluster.selection.select_n_clusters` as
        ``_DEFAULT_K_MAX_CAP``).

    Returns
    -------
    ClusterResult
        See the dataclass docstring.

    Raises
    ------
    ValueError
        If ``embedding`` is not 2D, if ``leiden_partition`` is not one
        of the supported literals, or if ``n_final_clusters`` is outside
        ``[2, n_leiden_clusters]``.

    Notes
    -----
    Pure function: ``embedding`` is never mutated and no global RNG is
    touched. All randomness is plumbed through ``leiden_seed`` (and the
    deterministic ``random_state`` baked into
    :func:`select_n_clusters`).
    """
    if embedding.ndim != 2:
        raise ValueError(
            f"`embedding` must be a 2D (n_window, n_feature) array; got ndim={embedding.ndim}"
        )
    if leiden_partition not in _PARTITION_CLASSES:
        supported = sorted(_PARTITION_CLASSES)
        raise ValueError(
            f"unsupported `leiden_partition`={leiden_partition!r}; expected one of {supported}"
        )

    # Promote to float64 without aliasing the caller's buffer. We never write
    # into ``arr``; ``np.asarray`` would alias if ``embedding`` is already
    # float64, but the algorithm below performs no in-place writes.
    arr = np.asarray(embedding, dtype=np.float64)
    n_window = arr.shape[0]

    knn_neighbors_used = int(np.sqrt(n_window)) if knn_neighbors is None else int(knn_neighbors)

    # ----- Stage 1 — kNN graph + Leiden ------------------------------------
    knn_sparse = kneighbors_graph(
        arr,
        n_neighbors=knn_neighbors_used,
        metric="euclidean",
        mode="connectivity",
        include_self=False,
    )
    sources, targets = knn_sparse.nonzero()
    edges = list(zip(sources.tolist(), targets.tolist(), strict=True))
    graph = ig.Graph(n=n_window, edges=edges, directed=False)
    # Reference sets all weights to 1.0 and then passes the graph as
    # unweighted. We omit the `weights=` argument when invoking leidenalg, but
    # keep the explicit weight assignment so the graph object faithfully
    # mirrors the reference's intermediate state.
    graph.es["weight"] = 1.0

    partition_class = _PARTITION_CLASSES[leiden_partition]
    # ``ModularityVertexPartition`` is parameterless; only CPM and
    # RBConfiguration accept ``resolution_parameter``. Branch here rather than
    # tolerating a leidenalg TypeError.
    partition_kwargs: dict[str, Any] = {"seed": leiden_seed}
    if leiden_partition != "Modularity":
        partition_kwargs["resolution_parameter"] = leiden_resolution
    partition = la.find_partition(graph, partition_class, **partition_kwargs)
    leiden_labels = np.asarray(partition.membership, dtype=np.int_)
    unique_leiden = np.unique(leiden_labels)
    n_leiden_clusters = int(unique_leiden.size)

    # ----- Stage 2 — Ward on Leiden cluster means --------------------------
    # ``unique_leiden`` is already sorted ascending by np.unique; iterate in
    # that order so ``leiden_to_final[c]`` indexes by community id directly.
    leiden_cluster_means = np.stack(
        [arr[leiden_labels == c].mean(axis=0) for c in unique_leiden]
    ).astype(np.float64, copy=False)

    # Ward requires at least 2 observations to produce a non-empty linkage.
    if n_leiden_clusters < 2:
        raise ValueError(
            f"Leiden found only {n_leiden_clusters} community/communities; "
            "need at least 2 to run Ward. Lower `leiden_resolution` or check "
            "the embedding."
        )

    distance_matrix = spd.pdist(leiden_cluster_means, metric="euclidean")
    linkage_matrix = sch.linkage(distance_matrix, method="ward").astype(np.float64, copy=False)

    if n_final_clusters is None:
        selection = select_n_clusters(
            arr,
            leiden_labels,
            linkage_matrix,
            metric=cluster_count_metric,
            k_min=cluster_count_min,
            k_max=cluster_count_max,
        )
        n_final_clusters_used = selection.n_clusters
        cluster_count_metric_used = selection.metric
        cluster_count_candidates = selection.k_candidates
        cluster_count_scores = selection.k_scores
    else:
        n_final_clusters_used = int(n_final_clusters)
        if n_final_clusters_used < 2:
            raise ValueError(f"`n_final_clusters` must be >= 2; got {n_final_clusters_used}")
        if n_final_clusters_used > n_leiden_clusters:
            raise ValueError(
                f"`n_final_clusters` ({n_final_clusters_used}) must be <= the "
                f"number of Leiden communities ({n_leiden_clusters}). Lower "
                "`n_final_clusters` or `leiden_resolution`."
            )
        cluster_count_metric_used = "user_supplied"
        cluster_count_candidates = np.empty(0, dtype=np.int_)
        cluster_count_scores = np.empty(0, dtype=np.float64)

    leiden_to_final = sch.fcluster(
        linkage_matrix, t=n_final_clusters_used, criterion="maxclust"
    ).astype(np.int_, copy=False)
    final_labels = leiden_to_final[leiden_labels]

    return ClusterResult(
        leiden_labels=leiden_labels,
        final_labels=final_labels,
        leiden_cluster_means=leiden_cluster_means,
        linkage_matrix=linkage_matrix,
        leiden_to_final=leiden_to_final,
        n_leiden_clusters=n_leiden_clusters,
        knn_neighbors_used=knn_neighbors_used,
        n_final_clusters_used=n_final_clusters_used,
        cluster_count_metric_used=cluster_count_metric_used,
        cluster_count_candidates=cluster_count_candidates,
        cluster_count_scores=cluster_count_scores,
    )
