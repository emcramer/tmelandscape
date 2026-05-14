"""Unit tests for :func:`tmelandscape.cluster.selection.select_n_clusters`.

Covers the Stream A Phase 5 checklist from
``tasks/06-clustering-implementation.md``:

* WSS-elbow on a synthetic 3-blob dataset selects a k in ``[2, 4]``.
* Calinski-Harabasz argmax matches argmax of the per-k CH array.
* Silhouette argmax matches argmax of the per-k silhouette array.
* ``k_min > n_leiden_clusters`` raises ``ValueError``.
* ``k_max=None`` resolves the upper bound to ``min(12, n_leiden_clusters)``
  (the biologically interpretable cap; was 20 pre-v0.6.1).
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
    ``[2, min(12, n_leiden_clusters)]`` covers k=3 comfortably.
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


def test_k_max_none_resolves_to_min_12_n_leiden() -> None:
    """``k_max=None`` ⇒ candidate range upper bound is ``min(12, n_leiden)``.

    The cap of 12 is the biologically interpretable upper bound for TME
    states (decision log 2026-05-14-cluster-count-max-default.md).
    """
    embedding, leiden_labels, linkage = _three_blob_setup()
    n_leiden = int(np.unique(leiden_labels).size)
    expected_upper = min(12, n_leiden)

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
    for metric in (
        "wss_elbow",
        "calinski_harabasz",
        "silhouette",
        "wss_lmethod",
        "wss_asymptote_fit",
        "wss_variance_explained",
    ):
        result = select_n_clusters(embedding, leiden_labels, linkage, metric=metric)
        assert result.k_candidates.shape == result.k_scores.shape


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_determinism_repeated_calls_equal_result() -> None:
    """Same input ⇒ identical ``SelectionResult`` across calls."""
    embedding, leiden_labels, linkage = _three_blob_setup()

    for metric in (
        "wss_elbow",
        "calinski_harabasz",
        "silhouette",
        "wss_lmethod",
        "wss_asymptote_fit",
        "wss_variance_explained",
    ):
        a = select_n_clusters(embedding, leiden_labels, linkage, metric=metric)
        b = select_n_clusters(embedding, leiden_labels, linkage, metric=metric)
        assert a.n_clusters == b.n_clusters
        assert a.metric == b.metric
        np.testing.assert_array_equal(a.k_candidates, b.k_candidates)
        np.testing.assert_array_equal(a.k_scores, b.k_scores)


# ---------------------------------------------------------------------------
# k>=4 anchor regression
# ---------------------------------------------------------------------------


def _five_blob_setup(
    n_per_blob: int = 30,
    n_feature: int = 8,
    separation: float = 9.0,
    seed: int = 7,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """5 well-separated blobs with sub-communities, so the true elbow is k≥4.

    Constructed analogously to ``_three_blob_setup`` but with 5 blob
    centres in a 5-vertex simplex-like arrangement and 4 sub-communities
    per blob, yielding ``n_leiden_clusters == 20``. The wide separation
    relative to within-blob noise should produce a WSS curve whose elbow
    is at k=5, well above ``k_min=2``.
    """
    rng = np.random.default_rng(seed)
    centres = separation * np.eye(5, n_feature, dtype=np.float64)

    embeddings: list[np.ndarray] = []
    leiden_labels_parts: list[np.ndarray] = []
    next_community_id = 0
    for c in centres:
        blob = rng.standard_normal(size=(n_per_blob, n_feature)) + c
        embeddings.append(blob)
        sub_ids = np.repeat(np.arange(4) + next_community_id, n_per_blob // 4 + 1)[:n_per_blob]
        leiden_labels_parts.append(sub_ids)
        next_community_id += 4

    embedding = np.vstack(embeddings).astype(np.float64)
    leiden_labels = np.concatenate(leiden_labels_parts).astype(np.int_)

    unique_ids = np.unique(leiden_labels)
    cluster_means = np.stack([embedding[leiden_labels == c].mean(axis=0) for c in unique_ids])
    d = spd.pdist(cluster_means, metric="euclidean")
    linkage = sch.linkage(d, method="ward").astype(np.float64)
    return embedding, leiden_labels, linkage


def test_wss_elbow_five_blobs_picks_k_at_or_above_four() -> None:
    """5-blob fixture: the WSS elbow must land at k≥4 — anchor regression.

    Reviewer A2 (Phase 5, RISK #2) noted that the private k=1 anchor used
    inside ``_wss_elbow`` to expose the convex shape to kneed could in
    principle bias the chosen k toward smaller values when the true
    elbow is at k≥4. This regression fixture explicitly exercises that
    case: 5 well-separated blobs ⇒ the WSS-vs-k curve has a clear drop
    at k=5. If the k=1 anchor were pulling kneed too early, this test
    would pick k=2 or k=3 and fail. Assertion uses a tolerance band of
    ``[4, 6]`` to allow for kneed's known slop on convex-decreasing
    curves without being so loose as to mask a real regression.

    Linked decision: docs/development/decisions/2026-05-14-wss-elbow-algorithm-options.md.
    """
    embedding, leiden_labels, linkage = _five_blob_setup()

    result = select_n_clusters(embedding, leiden_labels, linkage, metric="wss_elbow")

    assert result.metric == "wss_elbow"
    assert 4 <= result.n_clusters <= 6, (
        f"WSS elbow picked k={result.n_clusters} on a 5-blob fixture where "
        f"the true elbow is at k=5. If this is a small-k bias from the k=1 "
        f"anchor, see the deferred WSS-elbow-algorithm-options decision log."
    )


def test_wss_elbow_five_blobs_calinski_harabasz_also_finds_k_at_or_above_four() -> None:
    """Companion check: CH on the same 5-blob fixture also lands at k≥4.

    The CH metric does not use the k=1 anchor (it scores per-window
    labels directly), so this acts as a sanity floor on what the WSS
    elbow ought to roughly agree with on a fixture this well-separated.
    """
    embedding, leiden_labels, linkage = _five_blob_setup()

    result = select_n_clusters(embedding, leiden_labels, linkage, metric="calinski_harabasz")

    assert result.metric == "calinski_harabasz"
    assert 4 <= result.n_clusters <= 6


# ---------------------------------------------------------------------------
# wss_lmethod / wss_asymptote_fit / wss_variance_explained — Option 5 metrics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "metric",
    ["wss_lmethod", "wss_asymptote_fit", "wss_variance_explained"],
)
def test_option5_metric_shape_and_smoke(metric: str) -> None:
    """Each Option-5 metric returns a well-shaped ``SelectionResult``."""
    embedding, leiden_labels, linkage = _three_blob_setup()

    result = select_n_clusters(embedding, leiden_labels, linkage, metric=metric)

    assert isinstance(result, SelectionResult)
    assert result.metric == metric
    assert result.k_candidates.size > 0
    assert result.k_candidates.shape == result.k_scores.shape


@pytest.mark.parametrize(
    "metric",
    ["wss_lmethod", "wss_asymptote_fit", "wss_variance_explained"],
)
def test_option5_metric_recovers_three_blob_structure(metric: str) -> None:
    """Each Option-5 metric picks k in ``[2, 4]`` on a 3-blob fixture."""
    embedding, leiden_labels, linkage = _three_blob_setup()

    result = select_n_clusters(embedding, leiden_labels, linkage, metric=metric)

    assert 2 <= result.n_clusters <= 4, (
        f"{metric} picked k={result.n_clusters} on the 3-blob fixture; expected k in [2, 4]."
    )


def test_wss_lmethod_requires_at_least_four_candidates() -> None:
    """L-method needs ≥4 candidate ks; otherwise raise ``ValueError``."""
    embedding, leiden_labels, linkage = _three_blob_setup()

    # k_min=2, k_max=3 ⇒ 2 candidates < 4, no interior split possible.
    with pytest.raises(ValueError, match="wss_lmethod requires at least 4"):
        select_n_clusters(
            embedding,
            leiden_labels,
            linkage,
            metric="wss_lmethod",
            k_min=2,
            k_max=3,
        )


def test_wss_asymptote_fit_falls_back_on_degenerate_constant_wss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A constant WSS curve forces the fit to fail; verify graceful fallback.

    We monkeypatch :func:`_wss_at_k` to return a constant value
    regardless of k. The exponential-decay fit on a flat curve is
    degenerate, but the function must still return a sane integer in
    the candidate range — no crash, no NaN.
    """
    from tmelandscape.cluster import selection

    monkeypatch.setattr(
        selection,
        "_wss_at_k",
        lambda embedding, leiden_labels, linkage_matrix, k: 100.0,
    )

    embedding, leiden_labels, linkage = _three_blob_setup()
    n_leiden = int(np.unique(leiden_labels).size)

    result = select_n_clusters(embedding, leiden_labels, linkage, metric="wss_asymptote_fit")

    assert result.metric == "wss_asymptote_fit"
    assert 2 <= result.n_clusters <= n_leiden
    assert int(result.k_candidates[0]) <= result.n_clusters <= int(result.k_candidates[-1])


def test_wss_variance_explained_picks_smallest_k_above_threshold() -> None:
    """`wss_variance_explained` returns the smallest k whose
    `1 - wss/wss[0]` crosses 0.85.

    Independently recompute the variance-explained array from the
    result's WSS scores and verify the chosen k matches the smallest
    candidate position that meets the threshold (with fallback to the
    last candidate if none do).
    """
    embedding, leiden_labels, linkage = _three_blob_setup()

    result = select_n_clusters(embedding, leiden_labels, linkage, metric="wss_variance_explained")

    wss = result.k_scores
    var_explained = 1.0 - wss / wss[0]
    mask = var_explained >= 0.85
    if not np.any(mask):
        expected_k = int(result.k_candidates[-1])
    else:
        expected_k = int(result.k_candidates[int(np.argmax(mask))])
    assert result.n_clusters == expected_k
