"""Configurable feature-column filter for the normalisation step.

By default this module drops **no** features. Users who want a subset of
their summarised columns dropped before normalisation supply the names
explicitly via :class:`NormalizeConfig.drop_columns` (Phase 3.5; pending).

There is no built-in list of "always drop" features. Earlier iterations of
the reference oracle (``reference/00_abm_normalization.py``) hardcoded six
cell-density columns — that choice was specific to the LCSS-paper
application, not a property of the algorithm, and has been rolled back per
the project owner's explicit direction (ADR 0009).

Implementation deferred to Phase 3.5.
"""

from __future__ import annotations
