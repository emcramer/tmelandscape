"""Unit tests for :func:`tmelandscape.cluster.leiden_ward.cluster_leiden_ward`.

Covers the Stream A Phase 5 checklist from
``tasks/06-clustering-implementation.md``:

* Determinism: same seed ⇒ byte-identical output across two calls.
* Shape: well-separated 2-blob fixture with ``n_final_clusters=2`` yields
  a 2-cluster ``final_labels``.
* Auto-selection path: 2-blob fixture with ``n_final_clusters=None`` and
  ``cluster_count_metric="wss_elbow"`` chooses a k in ``[2, 4]``.
* Auto-selection determinism: same input ⇒ same chosen k.
* Partition literal: accepts the three valid values; rejects others with
  ``ValueError``.
* kNN heuristic: 64-row embedding with ``knn_neighbors=None`` ⇒
  ``knn_neighbors_used == 8``.
* ``n_final_clusters > n_leiden_clusters`` raises ``ValueError``.
* When user supplies k: ``cluster_count_metric_used == "user_supplied"``
  and ``cluster_count_candidates`` / ``cluster_count_scores`` are
  length-0 arrays.
* 1-feature embedding (degenerate): function returns a valid result.
* Input immutability: ``embedding`` numpy buffer is unchanged after the
  call.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from tmelandscape.cluster.leiden_ward import ClusterResult, cluster_leiden_ward

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _two_blob_embedding(
    n_per_blob: int = 50, n_feature: int = 20, separation: float = 5.0, seed: int = 42
) -> np.ndarray:
    """Build two well-separated isotropic Gaussian blobs in ``n_feature``-D."""
    rng = np.random.default_rng(seed)
    blob_a = rng.standard_normal(size=(n_per_blob, n_feature)) - separation
    blob_b = rng.standard_normal(size=(n_per_blob, n_feature)) + separation
    return np.vstack([blob_a, blob_b]).astype(np.float64)


def _three_blob_embedding(n_per_blob: int = 40, n_feature: int = 10, seed: int = 42) -> np.ndarray:
    """Build three well-separated isotropic Gaussian blobs."""
    rng = np.random.default_rng(seed)
    centres = np.array(
        [
            [-6.0] * n_feature,
            [0.0] * n_feature,
            [6.0] * n_feature,
        ]
    )
    blobs = [rng.standard_normal(size=(n_per_blob, n_feature)) + c for c in centres]
    return np.vstack(blobs).astype(np.float64)


def _hash_arrays(*arrays: np.ndarray) -> str:
    """Hash the concatenated byte representations of multiple arrays."""
    h = hashlib.sha256()
    for arr in arrays:
        h.update(np.ascontiguousarray(arr).tobytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_determinism_byte_identical_two_calls() -> None:
    """Same seed ⇒ byte-identical leiden_labels and final_labels."""
    embedding = _two_blob_embedding()

    out_a = cluster_leiden_ward(embedding, knn_neighbors=None, n_final_clusters=2)
    out_b = cluster_leiden_ward(embedding, knn_neighbors=None, n_final_clusters=2)

    assert _hash_arrays(out_a.leiden_labels, out_a.final_labels) == _hash_arrays(
        out_b.leiden_labels, out_b.final_labels
    )
    np.testing.assert_array_equal(out_a.leiden_labels, out_b.leiden_labels)
    np.testing.assert_array_equal(out_a.final_labels, out_b.final_labels)
    np.testing.assert_array_equal(out_a.leiden_cluster_means, out_b.leiden_cluster_means)
    np.testing.assert_array_equal(out_a.linkage_matrix, out_b.linkage_matrix)


def test_determinism_five_calls_stable() -> None:
    """Leiden seed truly stabilises across many repeated calls."""
    embedding = _two_blob_embedding()
    seen: set[str] = set()
    for _ in range(5):
        out = cluster_leiden_ward(embedding, knn_neighbors=None, n_final_clusters=2)
        seen.add(_hash_arrays(out.leiden_labels, out.final_labels))
    assert len(seen) == 1


# ---------------------------------------------------------------------------
# Shape — explicit k
# ---------------------------------------------------------------------------


def test_two_blob_explicit_k_yields_two_final_clusters() -> None:
    """100-by-20 two-blob fixture with ``n_final_clusters=2`` yields 2 final labels."""
    embedding = _two_blob_embedding(n_per_blob=50, n_feature=20)

    out = cluster_leiden_ward(embedding, knn_neighbors=None, n_final_clusters=2)

    assert isinstance(out, ClusterResult)
    assert np.unique(out.final_labels).size == 2
    assert out.final_labels.shape == (embedding.shape[0],)
    assert out.leiden_labels.shape == (embedding.shape[0],)
    assert out.n_final_clusters_used == 2
    assert out.leiden_to_final.shape == (out.n_leiden_clusters,)
    assert out.leiden_cluster_means.shape == (out.n_leiden_clusters, 20)
    assert out.linkage_matrix.shape == (out.n_leiden_clusters - 1, 4)


# ---------------------------------------------------------------------------
# Auto-selection path
# ---------------------------------------------------------------------------


def test_auto_selection_two_blob_wss_elbow_picks_small_k() -> None:
    """Auto-WSS-elbow on a 2-blob fixture picks k in ``[2, 4]``."""
    embedding = _two_blob_embedding()

    out = cluster_leiden_ward(
        embedding,
        knn_neighbors=None,
        n_final_clusters=None,
        cluster_count_metric="wss_elbow",
    )

    assert 2 <= out.n_final_clusters_used <= 4
    assert out.cluster_count_metric_used == "wss_elbow"
    assert out.cluster_count_candidates.size == out.cluster_count_scores.size
    assert out.cluster_count_candidates.size > 0


def test_auto_selection_determinism_same_k_chosen() -> None:
    """Identical input ⇒ identical auto-chosen k across repeated calls."""
    embedding = _two_blob_embedding()

    chosen_ks: set[int] = set()
    for _ in range(3):
        out = cluster_leiden_ward(embedding, knn_neighbors=None, n_final_clusters=None)
        chosen_ks.add(out.n_final_clusters_used)
    assert len(chosen_ks) == 1


# ---------------------------------------------------------------------------
# Partition literal validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("partition", ["CPM", "Modularity", "RBConfiguration"])
def test_partition_literal_accepted(partition: str) -> None:
    """All three supported partition literals are accepted."""
    embedding = _two_blob_embedding()
    out = cluster_leiden_ward(
        embedding,
        knn_neighbors=None,
        leiden_partition=partition,
        n_final_clusters=2,
    )
    assert out.n_final_clusters_used == 2


def test_partition_literal_unknown_raises() -> None:
    """An unknown partition literal raises ``ValueError``."""
    embedding = _two_blob_embedding()
    with pytest.raises(ValueError, match="unsupported `leiden_partition`"):
        cluster_leiden_ward(
            embedding,
            knn_neighbors=None,
            leiden_partition="NotARealPartition",
            n_final_clusters=2,
        )


# ---------------------------------------------------------------------------
# kNN heuristic
# ---------------------------------------------------------------------------


def test_knn_heuristic_sqrt_n_window() -> None:
    """64-row embedding with ``knn_neighbors=None`` ⇒ ``knn_neighbors_used == 8``."""
    rng = np.random.default_rng(0)
    embedding = rng.standard_normal(size=(64, 10))

    out = cluster_leiden_ward(embedding, knn_neighbors=None, n_final_clusters=2)

    assert out.knn_neighbors_used == 8


def test_knn_explicit_value_passed_through() -> None:
    """Explicit ``knn_neighbors`` is reflected in ``knn_neighbors_used``."""
    embedding = _two_blob_embedding()

    out = cluster_leiden_ward(embedding, knn_neighbors=15, n_final_clusters=2)
    assert out.knn_neighbors_used == 15


# ---------------------------------------------------------------------------
# n_final_clusters validation
# ---------------------------------------------------------------------------


def test_n_final_clusters_exceeds_leiden_raises() -> None:
    """``n_final_clusters > n_leiden_clusters`` raises a clear ValueError."""
    embedding = _two_blob_embedding()

    out = cluster_leiden_ward(embedding, knn_neighbors=None, n_final_clusters=2)
    too_many = out.n_leiden_clusters + 1

    with pytest.raises(
        ValueError, match=r"n_final_clusters.*must be <= the number of Leiden communities"
    ):
        cluster_leiden_ward(embedding, knn_neighbors=None, n_final_clusters=too_many)


def test_n_final_clusters_below_two_raises() -> None:
    """Explicit ``n_final_clusters < 2`` raises ``ValueError``."""
    embedding = _two_blob_embedding()
    with pytest.raises(ValueError, match=r"n_final_clusters.*must be >= 2"):
        cluster_leiden_ward(embedding, knn_neighbors=None, n_final_clusters=1)


# ---------------------------------------------------------------------------
# Provenance: user-supplied k vs auto path
# ---------------------------------------------------------------------------


def test_user_supplied_k_marks_metric_used() -> None:
    """User-supplied k ⇒ metric_used='user_supplied'; candidate arrays empty."""
    embedding = _two_blob_embedding()

    out = cluster_leiden_ward(embedding, knn_neighbors=None, n_final_clusters=2)

    assert out.cluster_count_metric_used == "user_supplied"
    assert out.cluster_count_candidates.shape == (0,)
    assert out.cluster_count_scores.shape == (0,)
    assert out.cluster_count_candidates.dtype.kind == "i"
    assert out.cluster_count_scores.dtype == np.float64


# ---------------------------------------------------------------------------
# Degenerate inputs
# ---------------------------------------------------------------------------


def test_single_feature_embedding_does_not_crash() -> None:
    """1-feature embedding is handled without crashing."""
    rng = np.random.default_rng(123)
    embedding = np.concatenate(
        [
            rng.standard_normal(size=(50, 1)) - 5,
            rng.standard_normal(size=(50, 1)) + 5,
        ],
        axis=0,
    )

    out = cluster_leiden_ward(embedding, knn_neighbors=None, n_final_clusters=2)

    assert isinstance(out, ClusterResult)
    assert out.final_labels.shape == (100,)
    assert out.leiden_cluster_means.shape[1] == 1


def test_non_2d_embedding_raises() -> None:
    """1D embedding raises ``ValueError`` with a clear message."""
    with pytest.raises(ValueError, match=r"must be a 2D"):
        cluster_leiden_ward(np.zeros(10), knn_neighbors=None, n_final_clusters=2)


# ---------------------------------------------------------------------------
# Purity
# ---------------------------------------------------------------------------


def test_embedding_not_mutated() -> None:
    """The function does not modify its ``embedding`` argument."""
    embedding = _three_blob_embedding()
    before = embedding.copy()
    before_hash = _hash_arrays(embedding)

    _ = cluster_leiden_ward(embedding, knn_neighbors=None, n_final_clusters=3)

    after_hash = _hash_arrays(embedding)
    assert before_hash == after_hash
    np.testing.assert_array_equal(embedding, before)
