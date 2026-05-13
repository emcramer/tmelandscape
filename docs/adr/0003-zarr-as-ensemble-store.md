# 0003 — Zarr as the ensemble-store format

- **Status:** Accepted
- **Date:** 2026-05-12
- **Deciders:** Eric, Claude

## Context

Step 3 (summarisation) produces multivariate time series for each simulation in the ensemble. A 100k-simulation ensemble × ~K timepoints × M spatial statistics is too large for a single in-memory DataFrame and must support partial / parallel reads in step 4 (embedding). The user has already decided that `spatialtissuepy` will convert PhysiCell outputs into tabular per-simulation summaries; the question is the aggregate format.

## Decision

Aggregate per-simulation tabular summaries into a single chunked **Zarr** store per ensemble, with logical dimensions `(simulation, timepoint, statistic)` and coordinate arrays for parameter values and initial-condition ids. Read via Dask for lazy operations. Provide an HDF5 export helper for archival / sharing.

## Consequences

- Cloud- and HPC-friendly: each chunk is a file; parallel writers work without locking.
- Excellent integration with Dask + xarray patterns common in scientific Python.
- Per-statistic / per-time-window slicing in step 4 is cheap.
- Sidecar `.provenance` group inside the store keeps provenance co-located with data.
- Costs: Zarr v2 vs v3 incompatibility is an ongoing ecosystem concern; pin `zarr>=2.18` for now and revisit when Zarr v3 dust settles.

## Alternatives considered

- Single HDF5 per ensemble — single-writer limitation; harder parallel ingest from many simulation directories.
- Parquet per simulation, no aggregate — keeps each simulation isolated but step 4 needs to load everything; lots of small-file overhead.
- AnnData per simulation + a top-level catalogue — idiomatic for single-cell but awkward for time-series ensembles; AnnData's strength is single (cells × features) tables, not time-stacks.

## Update 2026-05-13 (Zarr v3)

The original decision was written when Zarr v2 was the stable target. As of `uv sync` on 2026-05-13, the resolved version is `zarr 3.1.6` (the `>=2.18` constraint matched v3). Practical implications:

- xarray writes via `Dataset.to_zarr` and reads via `xarray.open_zarr` work cleanly in both directions.
- String coords (e.g. `simulation_id`, `statistic`) are stored as `FixedLengthUTF32`, which does not yet have a finalised v3 spec. Zarr 3.x emits `UnstableSpecificationWarning`; tmelandscape's `pyproject.toml` filters this in pytest so test output stays readable. Cross-library reads (zarr.js, future zarr-python releases) may need to revisit string-coord encoding.
- Consolidated metadata is also pre-spec on v3; same filter handling.

No action required for v0.2.x. Revisit before v1.0 release if Zarr v3 string-dtype spec lands.
