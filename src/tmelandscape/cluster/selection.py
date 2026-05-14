"""Cluster-count auto-selection for the Ward-on-Leiden-means stage.

See ADR 0010 ("Cluster-count auto-selection") for the policy and the
motivating discussion. This module implements six supported metrics:

* ``"wss_elbow"`` *(default)*: minimise within-cluster sum of squares
  (WSS); the chosen ``k`` is the knee detected by
  ``kneed.KneeLocator(curve="convex", direction="decreasing")``. If
  kneed cannot detect a knee (e.g. monotonic-but-no-elbow curve), the
  function falls back to the k with the largest marginal decrease in
  WSS.
* ``"wss_lmethod"``: Salvador & Chan 2004 L-method — two-linear-fit
  knee detection on the WSS curve.
* ``"wss_asymptote_fit"``: fit ``WSS(k) = A·exp(-B·(k - k_min)) + C``
  and pick the smallest k whose remaining distance to the fitted
  asymptote falls below a threshold (90%-of-reduction default).
* ``"wss_variance_explained"``: pick the smallest k whose
  ``1 - WSS(k)/WSS(k_min)`` crosses a threshold (0.85 default).
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

import warnings
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import scipy.cluster.hierarchy as sch
from kneed import KneeLocator
from numpy.typing import NDArray
from scipy.optimize import OptimizeWarning, curve_fit
from sklearn.metrics import (
    calinski_harabasz_score,
    silhouette_score,
)

_VALID_METRICS = (
    "wss_elbow",
    "calinski_harabasz",
    "silhouette",
    "wss_lmethod",
    "wss_asymptote_fit",
    "wss_variance_explained",
)

# Default thresholds for the WSS-variance / asymptote-fit metrics. Per
# the 2026-05-14-wss-elbow-option-5-accepted decision log these are not
# exposed as ClusterConfig knobs in v0.7.1.
_WSS_VARIANCE_EXPLAINED_THRESHOLD = 0.85
_WSS_ASYMPTOTE_REMAINING_FRACTION = 0.1

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
        Which metric was used. One of ``"wss_elbow"``,
        ``"wss_lmethod"``, ``"wss_asymptote_fit"``,
        ``"wss_variance_explained"``, ``"calinski_harabasz"``, or
        ``"silhouette"`` (six options as of v0.7.1; see
        :func:`select_n_clusters` for behaviour summaries).
    k_candidates
        ``(n_candidates,)`` integer array of candidate k's evaluated,
        sorted ascending.
    k_scores
        ``(n_candidates,)`` float array of metric values at each k,
        aligned with ``k_candidates``. For the four WSS-based metrics
        this is the WSS curve itself (uniform across the WSS family);
        for ``"calinski_harabasz"`` / ``"silhouette"`` it is the
        sklearn score, with degenerate cuts (single unique label,
        making CH and silhouette undefined) appearing as ``-inf``.
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
        Which metric to optimise. One of ``"wss_elbow"`` (default;
        kneed-based knee with a k=1 anchor + marginal-decrease fallback),
        ``"wss_lmethod"`` (Salvador & Chan two-linear-fit knee detection),
        ``"wss_asymptote_fit"`` (exponential-decay fit; smallest k whose
        remaining distance to the fitted asymptote ≤ 0.1 — i.e.
        90%-of-reduction; falls back to ``wss_variance_explained`` at
        threshold 0.9 on fit failure), ``"wss_variance_explained"``
        (smallest k whose ``1 - WSS(k)/WSS(k_min)`` ≥ 0.85; returns
        ``k_candidates[-1]`` if no k satisfies the threshold),
        ``"calinski_harabasz"`` (argmax of sklearn's CH score), or
        ``"silhouette"`` (argmax of sklearn's silhouette score). The
        three ``wss_*`` non-elbow metrics return the WSS array as
        ``k_scores`` — uniform with ``wss_elbow``.
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
        ``k_min > n_leiden_clusters``, if the resolved candidate range
        is empty, or — for ``metric="wss_lmethod"`` — if fewer than
        four candidate ks are available (the L-method requires at
        least one interior split point with ≥2 points on each side).
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
    elif metric == "wss_lmethod":
        scores = _score_wss(arr, leiden_arr, linkage_matrix, k_candidates)
        chosen = _lmethod_knee(k_candidates, scores)
    elif metric == "wss_asymptote_fit":
        scores = _score_wss(arr, leiden_arr, linkage_matrix, k_candidates)
        chosen = _asymptote_fit_knee(k_candidates, scores)
    elif metric == "wss_variance_explained":
        scores = _score_wss(arr, leiden_arr, linkage_matrix, k_candidates)
        chosen = _variance_explained_knee(k_candidates, scores)
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


def _lmethod_knee(
    k_candidates: NDArray[np.int_],
    wss: NDArray[np.float64],
) -> int:
    """Salvador & Chan 2004 L-method knee on the WSS curve.

    For each interior candidate ``k_c`` (positions ``1..n-2`` of
    ``k_candidates``, i.e. ``k_min+1 ≤ k_c ≤ k_max-1``), fit two
    linear regressions: one to the left segment
    ``(k_candidates[:idx+1], wss[:idx+1])`` and one to the right
    segment ``(k_candidates[idx:], wss[idx:])``. Pick the split that
    minimises the sum of left+right residual SSE. The chosen knee is
    the candidate at the optimal split position.

    Requires ``k_candidates.size >= 4`` (≥1 interior split with ≥2
    points on each side). See decision log
    ``2026-05-14-wss-elbow-option-5-accepted.md``.

    Parameters
    ----------
    k_candidates
        ``(n,)`` integer array of candidate k values, sorted ascending.
    wss
        ``(n,)`` float array of WSS at each candidate k.

    Returns
    -------
    int
        The candidate k at the SSE-minimising split position.

    Raises
    ------
    ValueError
        If ``k_candidates.size < 4`` (no interior split available).
    """
    n = k_candidates.size
    if n < 4:
        raise ValueError(
            "wss_lmethod requires at least 4 candidate k values "
            "(k_max - k_min >= 3) to fit two linear segments with >=2 "
            f"points each; got {n} candidate(s)."
        )

    x = k_candidates.astype(np.float64)
    y = wss.astype(np.float64)

    best_sse = np.inf
    best_idx = 1
    # Iterate interior positions 1..n-2 (inclusive). Each side has at
    # least 2 points (positions 0..idx and idx..n-1 with idx in 1..n-2
    # gives left-size = idx+1 >= 2 and right-size = n-idx >= 2).
    for idx in range(1, n - 1):
        left_sse = _segment_sse(x[: idx + 1], y[: idx + 1])
        right_sse = _segment_sse(x[idx:], y[idx:])
        total = left_sse + right_sse
        if total < best_sse:
            best_sse = total
            best_idx = idx
    return int(k_candidates[best_idx])


def _segment_sse(x: NDArray[np.float64], y: NDArray[np.float64]) -> float:
    """Residual SSE of an OLS linear fit ``y ~ a*x + b``.

    Uses ``np.polyfit(deg=1)`` then evaluates the fitted line; returns
    ``sum((y - y_hat) ** 2)``. Helper for :func:`_lmethod_knee`.
    """
    coeffs = np.polyfit(x, y, deg=1)
    y_hat = np.polyval(coeffs, x)
    return float(np.sum((y - y_hat) ** 2))


def _asymptote_fit_knee(
    k_candidates: NDArray[np.int_],
    wss: NDArray[np.float64],
) -> int:
    """Exponential-decay asymptote-fit knee on the WSS curve.

    Fit ``WSS(k) = A · exp(-B · (k - k_min)) + C`` via
    ``scipy.optimize.curve_fit`` with non-negative bounds. The chosen
    k is the smallest candidate whose remaining distance to the fitted
    asymptote ``C`` falls below ``_WSS_ASYMPTOTE_REMAINING_FRACTION``
    (default 0.1, i.e. "90% of the total reduction achieved"):

        ``(wss[i] - C) / max(wss[0] - C, 1e-12) <= 0.1``

    On fit failure (``RuntimeError``, ``OptimizeWarning``, or
    non-finite parameters), fall back to
    :func:`_variance_explained_knee` with threshold
    ``1 - _WSS_ASYMPTOTE_REMAINING_FRACTION`` (0.9), matching the
    "1 - ε" convention. See decision log
    ``2026-05-14-wss-elbow-option-5-accepted.md``.

    Parameters
    ----------
    k_candidates
        ``(n,)`` integer array of candidate k values, sorted ascending.
    wss
        ``(n,)`` float array of WSS at each candidate k.

    Returns
    -------
    int
        The smallest k whose remaining-fraction-to-asymptote ≤ ε; or
        the variance-explained fallback if the fit fails.
    """
    eps_remaining = _WSS_ASYMPTOTE_REMAINING_FRACTION

    if k_candidates.size == 1:
        return int(k_candidates[0])

    k0 = float(k_candidates[0])
    x = k_candidates.astype(np.float64) - k0
    y = wss.astype(np.float64)

    a0 = max(float(y[0] - y[-1]), 0.0)
    span = float(k_candidates[-1] - k_candidates[0])
    b0 = 1.0 / max(1.0, span)
    c0 = max(float(y[-1]), 0.0)

    fit_ok = True
    a_hat: float = 0.0
    c_hat: float = 0.0
    try:
        # OptimizeWarning indicates a degenerate fit (e.g. covariance
        # estimation failed). Treat it as a fit failure and fall back.
        with warnings.catch_warnings():
            warnings.simplefilter("error", OptimizeWarning)
            popt, _ = curve_fit(
                _asymptote_model,
                x,
                y,
                p0=(a0, b0, c0),
                bounds=([0.0, 1e-12, 0.0], [np.inf, np.inf, np.inf]),
                maxfev=10_000,
            )
        a_hat, b_hat, c_hat = (float(v) for v in popt)
        if not (np.isfinite(a_hat) and np.isfinite(b_hat) and np.isfinite(c_hat)):
            fit_ok = False
    except (RuntimeError, OptimizeWarning, ValueError):
        fit_ok = False

    if not fit_ok:
        # Variance-explained fallback at threshold (1 - eps) matches the
        # "1 - eps" convention from the decision log.
        return _variance_explained_knee(
            k_candidates,
            wss,
            threshold=1.0 - eps_remaining,
        )

    # Floor `denom` away from zero (a degenerate fit where C >= WSS(k_min)
    # is itself a failure signal — making `remaining` negative for every k
    # would push the mask all-True and `argmax` returns 0, i.e. the
    # smallest user-requested k. This is a defensible "fit pinned at the
    # top of the curve; pick the smallest k" fallback. Reviewer A2 R2.
    denom = max(float(y[0] - c_hat), 1e-12)
    remaining = (y - c_hat) / denom
    mask = remaining <= eps_remaining
    if not np.any(mask):
        return int(k_candidates[-1])
    # Monotone-decreasing WSS ⇒ mask is a monotone-true-tail; argmax of a
    # boolean array returns the smallest True index. (For pathological
    # non-monotone WSS this would not equal "smallest True"; real Ward-WSS
    # curves are non-increasing so the equivalence holds.)
    return int(k_candidates[int(np.argmax(mask))])


def _asymptote_model(
    x: NDArray[np.float64],
    a: float,
    b: float,
    c: float,
) -> NDArray[np.float64]:
    """Three-parameter exponential decay used by :func:`_asymptote_fit_knee`."""
    return a * np.exp(-b * x) + c


def _variance_explained_knee(
    k_candidates: NDArray[np.int_],
    wss: NDArray[np.float64],
    *,
    threshold: float = _WSS_VARIANCE_EXPLAINED_THRESHOLD,
) -> int:
    """Smallest-k variance-explained knee on the WSS curve.

    Compute ``var_explained(k) = 1 - wss[i] / wss[0]`` for each
    candidate (``wss[0]`` is WSS at ``k_min``; the ``k=1`` anchor used
    by ``wss_elbow`` is local to that metric and not exposed here).
    Return the smallest ``k`` whose ``var_explained`` reaches
    ``threshold`` (default 0.85). If no k satisfies the threshold,
    return ``k_candidates[-1]`` as the asymptotic fallback. See
    decision log ``2026-05-14-wss-elbow-option-5-accepted.md``.

    Parameters
    ----------
    k_candidates
        ``(n,)`` integer array of candidate k values, sorted ascending.
    wss
        ``(n,)`` float array of WSS at each candidate k.
    threshold
        Variance-explained threshold in ``[0, 1]``. Default 0.85.

    Returns
    -------
    int
        Smallest k crossing the threshold; ``k_candidates[-1]`` if
        none do.
    """
    if k_candidates.size == 0:
        raise ValueError("k_candidates must be non-empty")
    wss0 = float(wss[0])
    # If the baseline WSS is zero (or non-positive), the partition at
    # k_min already explains everything — there is nothing to reduce.
    # Return k_min to preserve the "smallest k that satisfies the
    # threshold" semantics without dividing by zero.
    if wss0 <= 0.0:
        return int(k_candidates[0])
    var_explained = 1.0 - wss / wss0
    mask = var_explained >= threshold
    if not np.any(mask):
        return int(k_candidates[-1])
    return int(k_candidates[int(np.argmax(mask))])
