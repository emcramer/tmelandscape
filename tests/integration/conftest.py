"""Shared fixtures for ``tmelandscape`` integration tests."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def structured_source_csv(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a small structured source CSV via ``tissue_simulator`` at a fixed seed.

    The fixture packs ~40 cells uniformly in an 80x80x10 um volume and assigns
    three cell types by concentric rings on ``(x, y)``: an inner tumor disc, a
    fibroblast ring, and an outer CD8 annulus. The exact node count varies with
    the packing seed but the type vocabulary is stable. Used by every
    integration test that drives ``generate_sweep``.
    """
    from tissue_simulator import TissueSection

    out_path = tmp_path_factory.mktemp("ic_source") / "source.csv"

    # Generous bounding box (80x80) and modest radii (3.5-4.5 um) so the
    # scaffold can re-pack a matched-N tissue under uniform_random without
    # tripping the "domain too small" guard.
    bootstrap = TissueSection(
        height=80.0,
        width=80.0,
        thickness=10.0,
        cell_radii={"x": (3.5, 4.5)},
        seed=20260528,
    )
    bootstrap.generate_cells(
        max_attempts=2500,
        min_spacing=0.5,
        allow_boundary_cells=True,
    )

    # Cap to the first 30 cells so packing fraction stays well under the
    # geometric limit and the scaffold re-pack converges quickly.
    cells_to_write = bootstrap.cells[:30]

    cx, cy = 40.0, 40.0
    with out_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["x", "y", "z", "radius", "cell_type", "is_boundary"])
        for cell in cells_to_write:
            x, y, z = cell.center
            r2 = (x - cx) ** 2 + (y - cy) ** 2
            if r2 <= 12.0**2:
                cell_type = "tumor"
            elif r2 <= 24.0**2:
                cell_type = "fibroblast"
            else:
                cell_type = "cd8"
            writer.writerow([x, y, z, cell.radius, cell_type, "False"])

    return out_path
