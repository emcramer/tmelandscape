# 0002 — Environment manager: `uv` with PEP 621 `pyproject.toml`

- **Status:** Accepted
- **Date:** 2026-05-12
- **Deciders:** Eric, Claude

## Context

The package needs a reproducible, deterministic environment manager. Candidates: `uv`, `pixi`, `conda` + `environment.yml`, `poetry`. The package is pure-Python with no native conda-only dependencies (PhysiCell is external; `spatialtissuepy` and `tissue_simulator` are `pip`-installable from GitHub).

## Decision

Use `uv` (https://docs.astral.sh/uv/) with a PEP 621 `pyproject.toml` and `uv.lock`. Optional-dependency groups: `viz`, `mcp`, `dev`, `docs`, plus an `all` meta-extra.

## Consequences

- Fastest installer in the ecosystem; cuts CI minutes.
- Deterministic via `uv.lock`.
- Standard `pyproject.toml` keeps the package compatible with `pip install` and any downstream tooling.
- HPC users who prefer `conda` can install via `pip install tmelandscape` inside a conda env once published.
- All canonical commands prefix with `uv run` (see `AGENTS.md`).

## Alternatives considered

- `pixi` — strong fit for conda-only deps, but we have none. Adds onboarding cost.
- `conda` + `environment.yml` — weakest reproducibility without `conda-lock`.
- `poetry` — mature but slower than `uv`; weaker scientific-Python community traction in 2026.
