"""Configurable feature-column filter.

Reference oracle (``reference/00_abm_normalization.py``) drops six cell-density
columns before normalization::

    M0_macrophage_density, M1_macrophage_density, M2_macrophage_density,
    effector_T_cell_density, exhausted_T_cell_density, malignant_epithelial_cell_density

Implementation deferred to Phase 3.5.
"""

from __future__ import annotations

DEFAULT_DROP_COLUMNS: tuple[str, ...] = (
    "M0_macrophage_density",
    "M1_macrophage_density",
    "M2_macrophage_density",
    "effector_T_cell_density",
    "exhausted_T_cell_density",
    "malignant_epithelial_cell_density",
)
