"""Regenerate the synthetic PhysiCell fixture deterministically.

Run with::

    uv run python tests/data/synthetic_physicell/build.py

Produces three sibling directories named ``sim_000000_ic_000``,
``sim_000001_ic_000``, and ``sim_000002_ic_000``. Each contains:

- ``PhysiCell_settings.xml`` — cell-type id <-> name mapping for the three
  types used by the LCSS panel: ``tumor``, ``effector_T_cell``,
  ``M0_macrophage``.
- ``output0000000N.xml`` for N in {0, 1, 2} — minimal output XML carrying
  the ``current_time`` scalar (in minutes) plus the
  ``simplified_data/cell_types`` table the upstream parser reads.
- ``output0000000N_cells_physicell.mat`` for N in {0, 1, 2} — paired cell
  matrices saved with ``scipy.io.savemat``.

Determinism
-----------
All randomness flows through :class:`numpy.random.default_rng` seeded by
``SYNTHETIC_FIXTURE_SEED + sim_idx``. Re-running the script overwrites the
existing files byte-identically.

To make the ``.mat`` files reproducible we overwrite the first 116 bytes
of the MAT v5 header (which scipy populates with a creation timestamp)
with a fixed description string. The remaining header bytes (124..) and
the body are deterministic given the input.

Layout invariants
-----------------
The ``.mat`` matrices use the *legacy* PhysiCell column layout (per the
upstream parser at ``spatialtissuepy/synthetic/physicell/parser.py``):

- ``shape = (n_features=20, n_cells=21)`` per timestep.
- Row 0: cell ID.
- Rows 1, 2, 3: x, y, z (z is fixed at 0.0; cells live in a 100x100 um box).
- Row 4: total_volume.
- Row 5: cell_type integer ID.
- Row 13: current_phase (set to 14 = "live"). With this layout the upstream
  parser auto-selects the legacy index mapping (because n_features < 30)
  and infers ``dead_flags = (phase >= 100)``, so all cells read as alive.

The legacy layout is used deliberately so that we can keep the total
on-disk fixture under 200 KB while still parsing cleanly. The auto-detect
heuristic in the upstream parser transposes when ``shape[0] > shape[1]``;
keeping ``n_features=20 < n_cells=21`` avoids the spurious transpose.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Final
from xml.dom import minidom

import numpy as np
from scipy.io import savemat

# Public so tests (and Reviewer A2) can import it for re-seed checks.
SYNTHETIC_FIXTURE_SEED: Final[int] = 20260513

# Three LCSS cell types, in registration order. IDs are stable across the
# fixture and pin the integer-to-name mapping the parser uses.
CELL_TYPE_NAMES: Final[tuple[str, ...]] = (
    "tumor",
    "effector_T_cell",
    "M0_macrophage",
)
CELL_TYPE_IDS: Final[tuple[int, ...]] = (0, 1, 2)

# Fixture size knobs. Kept small so the on-disk fixture stays well under
# 200 KB. See the module docstring for why n_features < n_cells matters.
N_SIMS: Final[int] = 3
N_TIMESTEPS: Final[int] = 3
N_CELLS_PER_TIMESTEP: Final[int] = 21  # 7 per type x 3 types
N_FEATURES: Final[int] = 20  # legacy PhysiCell column layout

# Spatial extent of the synthetic tissue, in microns. Z is fixed at 0 so
# the data is effectively 2D — matches the LCSS PhysiCell setup.
DOMAIN_MIN_UM: Final[tuple[float, float, float]] = (0.0, 0.0, 0.0)
DOMAIN_MAX_UM: Final[tuple[float, float, float]] = (100.0, 100.0, 0.0)

# Time per output step in minutes (synthetic; matches PhysiCell convention).
DT_MINUTES: Final[float] = 60.0

# Phase code 14 = "live" in the upstream PhysiCell phase dictionary; anything
# < 100 is treated as alive by the parser's dead-flag fallback.
LIVE_PHASE_CODE: Final[int] = 14

# Default per-cell volume in um^3, a plausible PhysiCell tumour-cell value.
DEFAULT_CELL_VOLUME_UM3: Final[float] = 2494.0

# Row offsets inside the (n_features, n_cells) .mat matrix. Must match the
# legacy index mapping in upstream parser.py (CELL_DATA_INDICES_LEGACY).
ROW_ID: Final[int] = 0
ROW_X: Final[int] = 1
ROW_Y: Final[int] = 2
ROW_Z: Final[int] = 3
ROW_TOTAL_VOLUME: Final[int] = 4
ROW_CELL_TYPE: Final[int] = 5
ROW_CURRENT_PHASE: Final[int] = 13

# Deterministic MAT v5 file header description. scipy.io.savemat writes
# "MATLAB 5.0 MAT-file Platform: posix, Created on: <timestamp>" into the
# first 116 bytes. We replace it with a fixed string after writing so the
# fixture is byte-identical across rebuilds. Length must be exactly 116;
# any trailing slack is padded with NUL bytes per MAT spec.
_MAT_HEADER_DESCRIPTION: Final[bytes] = (
    b"MATLAB 5.0 MAT-file tmelandscape synthetic fixture (deterministic)"
).ljust(116, b"\x00")


def _settings_xml_text() -> str:
    """Return the XML body for ``PhysiCell_settings.xml``.

    The upstream parser looks for ``cell_definitions/cell_definition`` with
    ``name`` and ``ID`` attributes; nothing else from this file is read by
    the Stream A pipeline, so we keep it minimal.
    """
    root = ET.Element("PhysiCell_settings", attrib={"version": "1.10.0"})
    cell_defs = ET.SubElement(root, "cell_definitions")
    for cid, name in zip(CELL_TYPE_IDS, CELL_TYPE_NAMES, strict=True):
        ET.SubElement(
            cell_defs,
            "cell_definition",
            attrib={"name": name, "ID": str(cid)},
        )
    return _pretty_xml(root)


def _output_xml_text(time_minutes: float) -> str:
    """Return the XML body for a single ``outputNNNNNNNN.xml`` timestep.

    Mirrors the PhysiCell 1.10+ ``simplified_data`` block so the upstream
    parser's first-pass cell-type lookup succeeds without needing the
    settings file as a fallback.
    """
    root = ET.Element("MultiCellDS", attrib={"version": "0.5.0"})
    metadata = ET.SubElement(root, "metadata")
    current_time = ET.SubElement(metadata, "current_time", attrib={"units": "min"})
    current_time.text = f"{time_minutes:.6f}"
    current_runtime = ET.SubElement(metadata, "current_runtime", attrib={"units": "sec"})
    current_runtime.text = "0.0"

    # Minimal mesh block so the parser picks up sane domain bounds.
    domain = ET.SubElement(ET.SubElement(root, "microenvironment"), "domain")
    bbox = ET.SubElement(domain, "mesh", attrib={"units": "micron"})
    bounding_box = ET.SubElement(bbox, "bounding_box", attrib={"units": "micron"})
    bounding_box.text = " ".join(f"{v}" for v in (*DOMAIN_MIN_UM, *DOMAIN_MAX_UM))

    cellular = ET.SubElement(root, "cellular_information")
    simplified = ET.SubElement(cellular, "simplified_data")
    cell_types = ET.SubElement(simplified, "cell_types")
    for cid, name in zip(CELL_TYPE_IDS, CELL_TYPE_NAMES, strict=True):
        type_elem = ET.SubElement(cell_types, "type", attrib={"ID": str(cid)})
        type_elem.text = name

    return _pretty_xml(root)


def _pretty_xml(root: ET.Element) -> str:
    """Return a stable pretty-printed XML string for deterministic output."""
    raw = ET.tostring(root, encoding="unicode")
    pretty: str = minidom.parseString(raw).toprettyxml(indent="  ")
    # minidom emits a default declaration line we keep, but trailing blank
    # lines make diffs noisy; strip them.
    return "\n".join(line for line in pretty.splitlines() if line.strip()) + "\n"


def _build_cell_matrix(rng: np.random.Generator) -> np.ndarray:
    """Build one timestep's cell matrix with shape (n_features, n_cells).

    Each of the three cell types is allocated an equal share of cells (7).
    Coordinates are uniformly drawn within the (x, y) box; z is pinned to
    zero. The current_phase row is set to ``LIVE_PHASE_CODE`` so the
    parser's dead-flag fallback marks every cell as alive.
    """
    matrix = np.zeros((N_FEATURES, N_CELLS_PER_TIMESTEP), dtype=np.float64)

    n_per_type, remainder = divmod(N_CELLS_PER_TIMESTEP, len(CELL_TYPE_IDS))
    # remainder must be zero for the fixture's "balanced" property; assert
    # rather than silently distribute, since the test counts depend on it.
    if remainder != 0:
        raise AssertionError(
            "N_CELLS_PER_TIMESTEP must be divisible by the number of cell types "
            f"({len(CELL_TYPE_IDS)}); got {N_CELLS_PER_TIMESTEP}."
        )

    type_id_column = np.concatenate(
        [np.full(n_per_type, cid, dtype=np.float64) for cid in CELL_TYPE_IDS]
    )

    # Cell IDs are 0..n-1 (stable across timesteps within a sim — close
    # enough to PhysiCell semantics for the parser's purposes).
    matrix[ROW_ID, :] = np.arange(N_CELLS_PER_TIMESTEP, dtype=np.float64)

    # Positions: uniform within a 100x100 um box, z = 0.
    matrix[ROW_X, :] = rng.uniform(DOMAIN_MIN_UM[0], DOMAIN_MAX_UM[0], size=N_CELLS_PER_TIMESTEP)
    matrix[ROW_Y, :] = rng.uniform(DOMAIN_MIN_UM[1], DOMAIN_MAX_UM[1], size=N_CELLS_PER_TIMESTEP)
    matrix[ROW_Z, :] = 0.0

    matrix[ROW_TOTAL_VOLUME, :] = DEFAULT_CELL_VOLUME_UM3
    matrix[ROW_CELL_TYPE, :] = type_id_column
    matrix[ROW_CURRENT_PHASE, :] = float(LIVE_PHASE_CODE)

    return matrix


def _write_sim(sim_idx: int, root: Path) -> Path:
    """Build sim directory ``sim_{sim_idx:06d}_ic_000`` under ``root``.

    Uses ``SYNTHETIC_FIXTURE_SEED + sim_idx`` as the RNG seed so each sim
    is independently reproducible.
    """
    sim_dir = root / f"sim_{sim_idx:06d}_ic_000"
    sim_dir.mkdir(parents=True, exist_ok=True)

    (sim_dir / "PhysiCell_settings.xml").write_text(_settings_xml_text())

    rng = np.random.default_rng(SYNTHETIC_FIXTURE_SEED + sim_idx)

    for ts in range(N_TIMESTEPS):
        xml_path = sim_dir / f"output{ts:08d}.xml"
        mat_path = sim_dir / f"output{ts:08d}_cells_physicell.mat"

        xml_path.write_text(_output_xml_text(time_minutes=ts * DT_MINUTES))

        matrix = _build_cell_matrix(rng)
        # ``do_compression=False`` is the savemat default; we set it
        # explicitly so the file is byte-identical run-to-run.
        # ``oned_as='column'`` and ``format='5'`` likewise pin the layout.
        savemat(
            str(mat_path),
            {"cells": matrix},
            do_compression=False,
            oned_as="column",
            format="5",
        )
        # scipy stamps the creation time into the first 116 bytes; overwrite
        # in place with a fixed description so the fixture diffs cleanly.
        with mat_path.open("r+b") as fh:
            fh.seek(0)
            fh.write(_MAT_HEADER_DESCRIPTION)

    return sim_dir


def build(root: Path | None = None) -> list[Path]:
    """(Re)generate all three synthetic sims under ``root``.

    Parameters
    ----------
    root
        Output directory. Defaults to the directory containing this file.

    Returns
    -------
    list[Path]
        Paths of the produced simulation directories in numeric order.
    """
    if root is None:
        root = Path(__file__).parent
    root.mkdir(parents=True, exist_ok=True)
    return [_write_sim(i, root) for i in range(N_SIMS)]


if __name__ == "__main__":
    paths = build()
    for p in paths:
        print(p)
