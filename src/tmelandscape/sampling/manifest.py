"""Sweep manifest: the artefact handed off to the external step-2 agent.

A manifest carries the originating :class:`~tmelandscape.config.sweep.SweepConfig`,
the table of per-simulation rows, and provenance (creation time + package
version). Persistence is dual:

- ``<path>.json`` — full Pydantic model dump (config + metadata + rows). This
  is the canonical artefact and is what :meth:`SweepManifest.load` reads.
- ``<path>.parquet`` — just the rows table, flattened so every parameter in
  ``parameter_values`` becomes its own column. Provided for cheap downstream
  analytics (pandas / DuckDB) that do not need the rest of the model.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, Field

import tmelandscape
from tmelandscape.config.sweep import SweepConfig


def _default_version() -> str:
    return tmelandscape.__version__


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SweepRow(BaseModel):
    """One simulation in the sweep = (parameter combination, initial condition)."""

    simulation_id: str = Field(..., description="Unique id, e.g. 'sim_000042_ic_007'.")
    parameter_combination_id: int = Field(..., ge=0)
    ic_id: int = Field(..., ge=0)
    parameter_values: dict[str, float] = Field(..., description="Param name -> value.")
    ic_path: str = Field(
        ...,
        description="Relative path to the IC csv file (under initial_conditions_dir).",
    )


class SweepManifest(BaseModel):
    """Artefact handed off to the external step-2 (PhysiCell-running) agent."""

    config: SweepConfig
    initial_conditions_dir: str = Field(
        ...,
        description=(
            "Directory containing the IC CSVs. When `sweep_id` is set the actual "
            "CSVs live under `<initial_conditions_dir>/<sweep_id>/`."
        ),
    )
    sweep_id: str | None = Field(
        default=None,
        description=(
            "Optional sweep-scoped subdirectory name under `initial_conditions_dir`. "
            "Set by `generate_sweep` to `sweep_<config_hash[:8]>_<utc_timestamp>`, "
            "letting multiple sweeps coexist in one parent IC directory and avoiding "
            "stale-file confusion. `None` means CSVs live directly in `initial_conditions_dir`."
        ),
    )
    rows: list[SweepRow]
    created_at: datetime = Field(default_factory=_utc_now)
    tmelandscape_version: str = Field(default_factory=_default_version)

    def ic_root(self) -> Path:
        """Return the directory that actually contains the IC CSV files."""
        base = Path(self.initial_conditions_dir)
        return base / self.sweep_id if self.sweep_id is not None else base

    def save(self, path: str | Path) -> None:
        """Persist to disk. Writes both ``<path>.json`` and ``<path>.parquet``.

        ``path`` may be given with or without the ``.json`` suffix; the suffix
        is stripped before deriving the two sibling output paths.
        """
        json_path, parquet_path = _resolve_paths(path)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(self.model_dump_json(indent=2))

        table = self._rows_to_arrow_table()
        pq.write_table(table, parquet_path)  # type: ignore[no-untyped-call]

    @classmethod
    def load(cls, path: str | Path) -> SweepManifest:
        """Load from ``<path>.json``.

        ``path`` may be given with or without the ``.json`` suffix. The
        parquet sibling is not consulted on load: JSON is canonical for the
        full model (it carries the config and metadata in addition to rows).
        """
        json_path, _ = _resolve_paths(path)
        payload = json.loads(json_path.read_text())
        return cls.model_validate(payload)

    def _rows_to_arrow_table(self) -> pa.Table:
        """Build the flattened rows table used for the parquet sidecar.

        Every parameter named in :class:`SweepConfig` becomes its own float64
        column, guaranteeing a stable schema even when ``rows`` is empty or
        when a particular row happens to omit a parameter.
        """
        param_names = [p.name for p in self.config.parameters]
        columns: dict[str, list[Any]] = {
            "simulation_id": [r.simulation_id for r in self.rows],
            "parameter_combination_id": [r.parameter_combination_id for r in self.rows],
            "ic_id": [r.ic_id for r in self.rows],
            "ic_path": [r.ic_path for r in self.rows],
        }
        for name in param_names:
            columns[name] = [r.parameter_values.get(name) for r in self.rows]

        schema = pa.schema(
            [
                pa.field("simulation_id", pa.string()),
                pa.field("parameter_combination_id", pa.int64()),
                pa.field("ic_id", pa.int64()),
                pa.field("ic_path", pa.string()),
                *(pa.field(name, pa.float64()) for name in param_names),
            ]
        )
        return pa.table(columns, schema=schema)


def _resolve_paths(path: str | Path) -> tuple[Path, Path]:
    """Return ``(json_path, parquet_path)`` for a user-supplied manifest path.

    Accepts a path with or without the ``.json`` suffix so callers can write
    ``manifest.save("sweep")`` or ``manifest.save("sweep.json")`` interchangeably.
    """
    p = Path(path)
    stem = p.with_suffix("") if p.suffix == ".json" else p
    return stem.with_suffix(".json"), stem.with_suffix(".parquet")
