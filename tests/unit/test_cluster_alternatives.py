"""Unit tests for :mod:`tmelandscape.cluster.alternatives`.

The only public function in v0.6.0 is :func:`cluster_identity`, a true
single-cluster passthrough. These tests pin that contract so future strategy
additions to the same module can't quietly break the registry's no-op anchor.
Mirrors the pattern set by ``tests/unit/test_embedding_alternatives.py`` and
``tests/unit/test_normalize_alternatives.py``.
"""

from __future__ import annotations

import numpy as np

from tmelandscape.cluster.alternatives import cluster_identity


class TestClusterIdentity:
    def test_returns_correct_shape_and_dtype(self) -> None:
        out = cluster_identity(np.zeros((10, 4)))
        assert out.shape == (10,)
        assert out.dtype == np.int64

    def test_all_labels_are_zero(self) -> None:
        out = cluster_identity(np.zeros((10, 4)))
        assert np.all(out == 0)

    def test_empty_input_returns_empty_output(self) -> None:
        # (0, 4)-shaped embedding ⇒ (0,)-shaped labels; no crash and an
        # empty int64 array, not a bare scalar.
        out = cluster_identity(np.empty((0, 4)))
        assert out.shape == (0,)
        assert out.dtype == np.int64

    def test_input_not_mutated(self) -> None:
        # Defensive: the function must not write back into the embedding
        # array. Build a small fixture, snapshot it, call, and compare.
        rng = np.random.default_rng(seed=0)
        embedding = rng.standard_normal((8, 3))
        snapshot = embedding.copy()
        cluster_identity(embedding)
        assert np.array_equal(embedding, snapshot)

    def test_independent_of_embedding_values(self) -> None:
        # The output is purely a function of the row count; two embeddings
        # of the same n_window must produce identical label arrays no matter
        # what their feature values are.
        rng = np.random.default_rng(seed=1)
        emb_a = rng.standard_normal((15, 4))
        emb_b = rng.standard_normal((15, 7))  # different n_feature too
        assert np.array_equal(cluster_identity(emb_a), cluster_identity(emb_b))

    def test_single_row_embedding(self) -> None:
        out = cluster_identity(np.zeros((1, 4)))
        assert out.shape == (1,)
        assert out.dtype == np.int64
        assert out[0] == 0
