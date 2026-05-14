"""Cluster-count auto-selection for the Ward-on-Leiden-means stage.

See ADR 0010 ("Cluster-count auto-selection") for the policy and the
motivating discussion. This module implements the three supported
metrics:

* ``"wss_elbow"`` *(default)*: minimise within-cluster sum of squares
  (WSS); the chosen ``k`` is the knee detected by
  ``kneed.KneeLocator(curve="convex", direction="decreasing")``. If
  kneed cannot detect a knee (e.g. monotonic-but-no-elbow curve), the
  function falls back to the k with the largest marginal decrease in
  WSS.
* ``"calinski_harabasz"``: argmax of
  ``sklearn.metrics.calinski_harabasz_score`` over the candidate range.
* ``"silhouette"``: argmax of ``sklearn.metrics.silhouette_score``
  (Euclidean). For ``n_window > 5000`` the sample is capped at 5000
  with a fixed ``random_state=42`` to keep the call O(n).

The function evaluates each candidate ``k`` by cutting the Ward
``linkage_matrix`` at ``t=k`` (``criterion="maxclust"``), broadcasting
the resulting Leiden→final mapping back to per-window labels via
``leiden_labels``, and scoring the partition.

Pure function: no I/O, no global RNG, no mutation of inputs. All
randomness is plumbed through fixed ``random_state`` seeds inside the
silhouette path.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import scipy.cluster.hierarchy as sch
from kneed import KneeLocator
from numpy.typing import NDArray
from sklearn.metrics import (
    calinski_harabasz_score,
    silhouette_score,
)

_VALID_METRICS = ("wss_elbow", "calinski_harabasz", "silhouette")

# Default cap on the candidate-k upper bound when the caller passes
# `k_max=None`. The biological motivation (owner directive, 2026-05-14):
# anything past ~8-10 final TME states becomes biologically less
# interpretable. The cap of 12 leaves a small buffer above that range
# while still respecting interpretability. A caller who needs more can
# always pass `k_max=N` explicitly. See decision log
# 2026-05-14-cluster-count-max-default.md.
_DEFAULT_K_MAX_CAP = 12

# Silhouette is O(n^2) in the number of samples. For ensembles much
# larger than this the cost dominates the rest of clustering; cap at
# a fixed deterministic subsample.
_SILHOUETTE_SAMPLE_CAP = 5000
_SILHOUETTE_RANDOM_STATE = 42


@dataclass
class SelectionResult:
    """Result of auto-selecting ``n_final_clusters``.

    Attributes
    ----------
    n_clusters
        The chosen ``k`` (>= 2).
    metric
        Which metric was used: ``"wss_elbow"``,
        ``"calinski_harabasz"``, or ``"silhouette"``.
    k_candidates
        ``(n_candidates,)`` integer array of candidate k's evaluated,
        sorted ascending.
    k_scores
        ``(n_candidates,)`` float array of metric values at each k,
        aligned with ``k_candidates``. Degenerate cuts (a single unique
        label, which makes CH and silhouette undefined) appear as
        ``-inf``.
    """

    n_clusters: int
    metric: str
    k_candidates: NDArray[np.int_]
    k_scores: NDArray[np.float64]


def select_n_clusters(
    embedding: np.ndarray,
    leiden_labels: np.ndarray,
    linkage_matrix: np.ndarray,
    *,
    metric: str = "wss_elbow",
    k_min: int = 2,
    k_max: int | None = None,
) -> SelectionResult:
    """Pick an optimal ``n_final_clusters`` for Ward cuts of the dendrogram.

    Parameters
    ----------
    embedding
        ``(n_window, n_feature)`` float array — the same array passed to
        :func:`tmelandscape.cluster.leiden_ward.cluster_leiden_ward`.
    leiden_labels
        ``(n_window,)`` integer array — Leiden community id for each row
        of ``embedding`` (Stage-1 output).
    linkage_matrix
        ``((n_leiden_clusters - 1), 4)`` float array — scipy Ward
        linkage matrix from Stage 2.
    metric
        Which metric to optimise. One of ``"wss_elbow"`` (default),
        ``"calinski_harabasz"``, ``"silhouette"``.
    k_min
        Inclusive lower bound on the candidate range. Must be ``>= 2``
        and ``<= n_leiden_clusters``.
    k_max
        Inclusive upper bound. ``None`` ⇒
        ``min(_DEFAULT_K_MAX_CAP, n_leiden_clusters)`` (the cap is 12 —
        the biologically interpretable upper bound for TME states; see
        decision log 2026-05-14-cluster-count-max-default.md).
        Internally clamped to ``n_leiden_clusters``.

    Returns
    -------
    SelectionResult
        See dataclass docstring.

    Raises
    ------
    ValueError
        If ``metric`` is not one of the supported literals, if
        ``k_min > n_leiden_clusters``, or if the resolved candidate
        range is empty.
    """
    if metric not in _VALID_METRICS:
        raise ValueError(f"unsupported `metric`={metric!r}; expected one of {list(_VALID_METRICS)}")

    n_leiden_clusters = int(np.unique(leiden_labels).size)
    if k_min > n_leiden_clusters:
        raise ValueError(
            f"`k_min` ({k_min}) exceeds the number of Leiden communities "
            f"({n_leiden_clusters}); cannot evaluate any candidate k."
        )

    upper = (
        min(_DEFAULT_K_MAX_CAP, n_leiden_clusters)
        if k_max is None
        else min(k_max, n_leiden_clusters)
    )
    if upper < k_min:
        raise ValueError(
            f"resolved candidate-k range is empty: k_min={k_min}, "
            f"k_max (resolved)={upper}, n_leiden_clusters={n_leiden_clusters}"
        )

    k_candidates = np.arange(k_min, upper + 1, dtype=np.int_)

    # Promote without aliasing concerns: nothing here writes into ``arr``.
    arr = np.asarray(embedding, dtype=np.float64)
    leiden_arr = np.asarray(leiden_labels)

    if metric == "wss_elbow":
        scores = _score_wss(arr, leiden_arr, linkage_matrix, k_candidates)
        # kneed needs to see a strongly convex shape; for well-separated
        # clusters the WSS drop from k=1 to k=2 dominates the rest of the
        # curve and makes the elbow unambiguous. Evaluate WSS at k=1 as a
        # private anchor (not reported on the result) so the knee detector
        # has the full convex curve to work with. The anchor doesn't widen
        # the candidate range — only candidates in ``[k_min, k_max]`` are
        # ever returned as the chosen k.
        wss_k1 = _wss_at_k(arr, leiden_arr, linkage_matrix, 1)
        anchored_k = np.concatenate(([1], k_candidates)).astype(np.int_)
        anchored_wss = np.concatenate(([wss_k1], scores)).astype(np.float64)
        chosen = _knee_or_marginal(anchored_k, anchored_wss, k_min=int(k_candidates[0]))
    elif metric == "calinski_harabasz":
        scores = _score_metric(
            arr,
            leiden_arr,
            linkage_matrix,
            k_candidates,
            scorer=_ch_score,
        )
        chosen = int(k_candidates[int(np.argmax(scores))])
    else:  # silhouette
        scores = _score_metric(
            arr,
            leiden_arr,
            linkage_matrix,
            k_candidates,
            scorer=_silhouette,
        )
        chosen = int(k_candidates[int(np.argmax(scores))])

    return SelectionResult(
        n_clusters=int(chosen),
        metric=metric,
        k_candidates=k_candidates,
        k_scores=scores,
    )


# ---------------------------------------------------------------------------
# Per-metric helpers
# ---------------------------------------------------------------------------


def _final_labels_for_k(
    leiden_labels: np.ndarray, linkage_matrix: np.ndarray, k: int
) -> NDArray[np.int_]:
    """Cut the Ward dendrogram at ``k`` and broadcast to per-window labels."""
    leiden_to_final = sch.fcluster(linkage_matrix, t=int(k), criterion="maxclust").astype(
        np.int_, copy=False
    )
    return np.asarray(leiden_to_final[leiden_labels], dtype=np.int_)


def _score_wss(
    embedding: NDArray[np.float64],
    leiden_labels: np.ndarray,
    linkage_matrix: np.ndarray,
    k_candidates: NDArray[np.int_],
) -> NDArray[np.float64]:
    """Compute WSS for each candidate k.

    WSS_k = sum over final clusters c of sum_{x in c} ||x - mu_c||**2,
    where mu_c is the centroid of cluster ``c`` in the embedding space.
    """
    scores = np.empty(k_candidates.size, dtype=np.float64)
    for i, k in enumerate(k_candidates):
        scores[i] = _wss_at_k(embedding, leiden_labels, linkage_matrix, int(k))
    return scores


def _wss_at_k(
    embedding: NDArray[np.float64],
    leiden_labels: np.ndarray,
    linkage_matrix: np.ndarray,
    k: int,
) -> float:
    """Compute WSS at a single ``k``.

    For ``k == 1`` the partition is a single cluster, and WSS reduces to
    the total sum of squared deviations from the global centroid. We
    handle this branch explicitly because ``fcluster(Z, t=1,
    criterion="maxclust")`` does the same thing but goes through scipy.
    """
    if k <= 1:
        centroid = embedding.mean(axis=0)
        return float(np.sum((embedding - centroid) ** 2))
    labels = _final_labels_for_k(leiden_labels, linkage_matrix, k)
    wss = 0.0
    for c in np.unique(labels):
        members = embedding[labels == c]
        centroid = members.mean(axis=0)
        wss += float(np.sum((members - centroid) ** 2))
    return wss


def _ch_score(embedding: NDArray[np.float64], labels: NDArray[np.int_]) -> float:
    return float(calinski_harabasz_score(embedding, labels))


def _silhouette(embedding: NDArray[np.float64], labels: NDArray[np.int_]) -> float:
    n = embedding.shape[0]
    sample_size: int | None = _SILHOUETTE_SAMPLE_CAP if n > _SILHOUETTE_SAMPLE_CAP else None
    return float(
        silhouette_score(
            embedding,
            labels,
            metric="euclidean",
            sample_size=sample_size,
            random_state=_SILHOUETTE_RANDOM_STATE,
        )
    )


def _score_metric(
    embedding: NDArray[np.float64],
    leiden_labels: np.ndarray,
    linkage_matrix: np.ndarray,
    k_candidates: NDArray[np.int_],
    *,
    scorer: Callable[[NDArray[np.float64], NDArray[np.int_]], float],
) -> NDArray[np.float64]:
    """Compute a per-candidate score, marking degenerate cuts as ``-inf``.

    sklearn's Calinski-Harabasz and silhouette implementations both
    raise ``ValueError`` when the partition collapses to a single
    cluster. Treat those candidates as ``-inf`` so argmax-based
    selection skips them naturally.
    """
    scores = np.empty(k_candidates.size, dtype=np.float64)
    for i, k in enumerate(k_candidates):
        labels = _final_labels_for_k(leiden_labels, linkage_matrix, int(k))
        if np.unique(labels).size < 2:
            scores[i] = -np.inf
            continue
        scores[i] = scorer(embedding, labels)
    return scores


def _knee_or_marginal(
    k_candidates: NDArray[np.int_],
    wss_values: NDArray[np.float64],
    *,
    k_min: int | None = None,
) -> int:
    """Return the elbow of a decreasing-convex WSS curve.

    Prefers ``kneed.KneeLocator``; falls back to the candidate ``k`` at
    the position with the largest marginal decrease in WSS when
    kneed returns ``None`` (e.g. the curve is monotonic without a
    distinguishable knee).

    ``k_min`` clamps the returned k from below. The caller may pass a
    ``k_candidates`` array that begins below the user-requested range
    (e.g. an anchor at ``k=1``) to help kneed; ``k_min`` ensures the
    final answer still sits inside the user's range.
    """
    if k_candidates.size == 1:
        return int(k_candidates[0])

    locator = KneeLocator(
        x=k_candidates.tolist(),
        y=wss_values.tolist(),
        curve="convex",
        direction="decreasing",
    )
    if locator.knee is not None:
        chosen = int(locator.knee)
    else:
        # Fallback: pick the k with the largest marginal-decrease slope.
        # ``np.diff`` returns ``wss[i+1] - wss[i]``; for a decreasing WSS the
        # most negative entry is the biggest drop; the k associated with that
        # drop is ``k_candidates[i+1]`` (the larger-k side, where the gain has
        # just been realised). This is the canonical "elbow" heuristic.
        deltas = np.diff(wss_values)
        if deltas.size == 0:  # pragma: no cover - guarded by the size==1 check above
            chosen = int(k_candidates[0])
        else:
            chosen = int(k_candidates[int(np.argmin(deltas)) + 1])

    if k_min is not None and chosen < k_min:
        chosen = k_min
    return chosen
