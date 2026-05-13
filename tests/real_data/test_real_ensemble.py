"""Opt-in real-data integration test.

Gated by ``pytest -m real``. Reads from ``tests/data/example_physicell/{sim_000,
sim_003, sim_014}``, which must be populated first via
``scripts/fetch_example_data.py``.

Phase 0: only a fixture-detection test that fails loudly if the example data is
missing. Per-step real-data tests land in their respective phases.
"""

from __future__ import annotations

from pathlib import Path

import pytest

EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "example_physicell"
EXPECTED_SIMS = ("sim_000", "sim_003", "sim_014")


@pytest.mark.real
def test_example_physicell_outputs_are_present() -> None:
    missing = [s for s in EXPECTED_SIMS if not (EXAMPLE_DIR / s).is_dir()]
    if missing:
        pytest.fail(
            "Example PhysiCell outputs are missing. Run "
            "`uv run python scripts/fetch_example_data.py --from-local <path>` "
            f"to populate. Missing: {missing}",
        )
