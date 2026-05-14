"""Unit tests for :func:`tmelandscape.cluster.selection.select_n_clusters`.

Covers the Stream A Phase 5 checklist from
``tasks/06-clustering-implementation.md``:

* WSS-elbow on a synthetic 3-blob dataset selects a k in ``[2, 4]``.
* Calinski-Harabasz argmax matches argmax of the per-k CH array.
* Silhouette argmax matches argmax of the per-k silhouette array.
* ``k_min > n_leiden_clusters`` raises ``ValueError``.
* ``k_max=None`` resolves the upper bound to ``min(20, n_leiden_clusters)``.
* ``k_scores`` has the same length as ``k_candidates``.
* Determinism: identical input ⇒ identical ``SelectionResult``.
* Invalid metric string raises ``ValueError``.
"""

from __future__ import annotations

import numpy as np
import pytest
import scipy.cluster.hierarchy as sch
import scipy.spatial.distance as spd

from tmelandscape.cluster.selection import SelectionResult, select_n_clusters

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _three_blob_setup(
    n_per_blob: int = 40,
    n_feature: int = 10,
    separation: float = 6.0,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build a 3-blob embedding, fake-but-faithful Leiden labels, and a Ward
    linkage matrix over per-cluster means.

    The Leiden labels are exactly the ground-truth blob ids. The linkage
    is built over the per-Leiden-community means, mirroring the real
    pipeline. We bump ``n_leiden_clusters`` artificially by splitting
    each blob into a few sub-communities so the candidate range
    ``[2, min(20, n_leiden_clusters)]`` covers k=3 comfortably.
    """
    rng = np.random.default_rng(seed)
    centres = np.array(
        [
            [-separation] * n_feature,
            [0.0] * n_feature,
            [+separation] * n_feature,
        ]
    )

    embeddings: list[np.ndarray] = []
    leiden_labels_parts: list[np.ndarray] = []
    next_community_id = 0
    # Split each blob into 3 sub-communities to bump n_leiden_clusters.
    for c in centres:
        blob = rng.standard_normal(size=(n_per_blob, n_feature)) + c
        embeddings.append(blob)
        sub_ids = np.repeat(np.arange(3) + next_community_id, n_per_blob // 3 + 1)[:n_per_blob]
        leiden_labels_parts.append(sub_ids)
        next_community_id += 3

    embedding = np.vstack(embeddings).astype(np.float64)
    leiden_labels = np.concatenate(leiden_labels_parts).astype(np.int_)

    unique_ids = np.unique(leiden_labels)
    cluster_means = np.stack([embedding[leiden_labels == c].mean(axis=0) for c in unique_ids])
    d = spd.pdist(cluster_means, metric="euclidean")
    linkage = sch.linkage(d, method="ward").astype(np.float64)

    return embedding, leiden_labels, linkage


# ---------------------------------------------------------------------------
# WSS elbow
# ---------------------------------------------------------------------------


def test_wss_elbow_three_blobs_picks_small_k() -> None:
    """WSS-elbow on a 3-blob fixture picks k in ``[2, 4]`` (kneed's slop)."""
    embedding, leiden_labels, linkage = _three_blob_setup()

    result = select_n_clusters(embedding, leiden_labels, linkage, metric="wss_elbow")

    assert isinstance(result, SelectionResult)
    assert result.metric == "wss_elbow"
    assert 2 <= result.n_clusters <= 4
    assert result.k_candidates.size == result.k_scores.size
    assert result.k_candidates.size > 0


# ---------------------------------------------------------------------------
# Calinski-Harabasz
# ---------------------------------------------------------------------------


def test_calinski_harabasz_argmax_matches_score_array() -> None:
    """The chosen k is the argmax of the CH score array."""
    embedding, leiden_labels, linkage = _three_blob_setup()

    result = select_n_clusters(embedding, leiden_labels, linkage, metric="calinski_harabasz")

    assert result.metric == "calinski_harabasz"
    chosen_idx = int(np.argmax(result.k_scores))
    assert result.n_clusters == int(result.k_candidates[chosen_idx])
    # 3-blob structure ⇒ CH should peak at k=3 if the centroids and
    # Leiden communities recover that structure.
    assert result.n_clusters == 3


# ---------------------------------------------------------------------------
# Silhouette
# ---------------------------------------------------------------------------


def test_silhouette_argmax_matches_score_array() -> None:
    """The chosen k is the argmax of the silhouette score array."""
    embedding, leiden_labels, linkage = _three_blob_setup()

    result = select_n_clusters(embedding, leiden_labels, linkage, metric="silhouette")

    assert result.metric == "silhouette"
    chosen_idx = int(np.argmax(result.k_scores))
    assert result.n_clusters == int(result.k_candidates[chosen_idx])


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


def test_k_min_exceeds_n_leiden_raises() -> None:
    """``k_min`` above ``n_leiden_clusters`` raises ``ValueError``."""
    embedding, leiden_labels, linkage = _three_blob_setup()
    n_leiden = int(np.unique(leiden_labels).size)

    with pytest.raises(ValueError, match="exceeds the number of Leiden communities"):
        select_n_clusters(
            embedding,
            leiden_labels,
            linkage,
            metric="wss_elbow",
            k_min=n_leiden + 1,
        )


def test_invalid_metric_raises() -> None:
    """Unknown metric string raises ``ValueError``."""
    embedding, leiden_labels, linkage = _three_blob_setup()
    with pytest.raises(ValueError, match="unsupported `metric`"):
        select_n_clusters(embedding, leiden_labels, linkage, metric="not-a-metric")


# ---------------------------------------------------------------------------
# k_max default
# ---------------------------------------------------------------------------


def test_k_max_none_resolves_to_min_20_n_leiden() -> None:
    """``k_max=None`` ⇒ candidate range upper bound is ``min(20, n_leiden)``."""
    embedding, leiden_labels, linkage = _three_blob_setup()
    n_leiden = int(np.unique(leiden_labels).size)
    expected_upper = min(20, n_leiden)

    result = select_n_clusters(embedding, leiden_labels, linkage, metric="wss_elbow")

    assert int(result.k_candidates[-1]) == expected_upper
    assert int(result.k_candidates[0]) == 2


def test_k_max_capped_at_n_leiden() -> None:
    """Explicit ``k_max`` larger than ``n_leiden`` is clamped down."""
    embedding, leiden_labels, linkage = _three_blob_setup()
    n_leiden = int(np.unique(leiden_labels).size)

    result = select_n_clusters(
        embedding,
        leiden_labels,
        linkage,
        metric="wss_elbow",
        k_max=n_leiden + 100,
    )

    assert int(result.k_candidates[-1]) == n_leiden


# ---------------------------------------------------------------------------
# Shape invariants
# ---------------------------------------------------------------------------


def test_scores_shape_matches_candidates() -> None:
    """``k_scores`` length equals ``k_candidates`` length for each metric."""
    embedding, leiden_labels, linkage = _three_blob_setup()
    for metric in ("wss_elbow", "calinski_harabasz", "silhouette"):
        result = select_n_clusters(embedding, leiden_labels, linkage, metric=metric)
        assert result.k_candidates.shape == result.k_scores.shape


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_determinism_repeated_calls_equal_result() -> None:
    """Same input ⇒ identical ``SelectionResult`` across calls."""
    embedding, leiden_labels, linkage = _three_blob_setup()

    for metric in ("wss_elbow", "calinski_harabasz", "silhouette"):
        a = select_n_clusters(embedding, leiden_labels, linkage, metric=metric)
        b = select_n_clusters(embedding, leiden_labels, linkage, metric=metric)
        assert a.n_clusters == b.n_clusters
        assert a.metric == b.metric
        np.testing.assert_array_equal(a.k_candidates, b.k_candidates)
        np.testing.assert_array_equal(a.k_scores, b.k_scores)
