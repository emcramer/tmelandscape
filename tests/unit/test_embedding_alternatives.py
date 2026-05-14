"""Unit tests for :mod:`tmelandscape.embedding.alternatives`.

The only public function in v0.5.0 is :func:`embed_identity`, a true
passthrough. These tests pin that contract so future strategy additions to
the same module can't quietly break the registry's no-op anchor. Mirrors
the pattern set by ``tests/unit/test_normalize_alternatives.py``.
"""

from __future__ import annotations

import numpy as np

from tmelandscape.embedding.alternatives import embed_identity


class TestEmbedIdentity:
    def test_returns_input_unchanged_1d(self) -> None:
        arr = np.array([1.0, 2.0, 3.0, np.nan])
        out = embed_identity(arr)
        assert np.array_equal(out, arr, equal_nan=True)

    def test_returns_input_unchanged_3d(self) -> None:
        # The natural input shape for the embedding step is
        # (n_sim, n_timepoint, n_statistic). Verify the passthrough works
        # for that rank without copying or reshaping.
        rng = np.random.default_rng(seed=0)
        arr = rng.standard_normal((3, 10, 4))
        out = embed_identity(arr)
        assert np.array_equal(out, arr)

    def test_returns_same_object_no_copy(self) -> None:
        # Documented behaviour: passthrough returns by reference. Callers
        # treating the array as immutable should not rely on a defensive
        # copy here.
        arr = np.zeros((5,))
        assert embed_identity(arr) is arr

    def test_ignores_arbitrary_kwargs(self) -> None:
        # The function signature exists so callers can pass the same kwargs
        # they would give a real strategy (e.g. ``window_size``,
        # ``step_size``) without branching at the call site.
        arr = np.array([0.0, 1.0])
        out = embed_identity(
            arr,
            window_size=50,
            step_size=2,
            anything_else=object(),
        )
        assert np.array_equal(out, arr)

    def test_preserves_dtype(self) -> None:
        arr = np.array([1, 2, 3], dtype=np.int32)
        out = embed_identity(arr)
        assert out.dtype == np.int32
        assert np.array_equal(out, arr)
