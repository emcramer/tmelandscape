# `tests/data/example_physicell/` — three example PhysiCell sim outputs

This directory is populated by `scripts/fetch_example_data.py`. The actual sim data is **not committed** (see `.gitignore`); only this README is tracked.

## Provenance

- **Zenodo deposition:** [10.5281/zenodo.20148946](https://doi.org/10.5281/zenodo.20148946)
- **Archive file:** `example_physicell_simulations.zip` (1.5 GB compressed; ~5.5 GB extracted)
- **MD5:** `9001e2a652799f6aa1485ead822ce5b7`
- **License:** CC-BY-4.0
- **Sims included:** `sim_000`, `sim_003`, `sim_014` (selected from a larger sweep — rationale to be recorded by Eric).
- **Local source (mirror):** `/Users/cramere/OneDrive - Oregon Health & Science University/graduate/knowledgebase/00-projects/parameter-exploration/data/abm/raw/{sim_000, sim_003, sim_014}`
- **Approximate size per sim:** ~1.5–2 GB; ~4,000 files (one PhysiCell timepoint dump each).

## How to populate

```bash
# Default: download from Zenodo (1.5 GB), verify MD5, extract, delete zip
uv run python scripts/fetch_example_data.py

# Keep the downloaded zip after extraction (idempotent reuse)
uv run python scripts/fetch_example_data.py --keep-zip

# Use a pre-downloaded zip
uv run python scripts/fetch_example_data.py --zip-path /path/to/example_physicell_simulations.zip

# Use a local source directory (e.g. OneDrive copy) — no network, no MD5 check
uv run python scripts/fetch_example_data.py --from-local \
    "/Users/cramere/OneDrive - Oregon Health & Science University/graduate/knowledgebase/00-projects/parameter-exploration/data/abm/raw"

# Symlink instead of copy (saves disk; breaks if source moves)
uv run python scripts/fetch_example_data.py --from-local <dir> --symlink
```

## How to use

The opt-in real-data integration test (`tests/real_data/`, gated by `pytest -m real`) reads from this directory. After fetching:

```bash
uv run pytest -m real
```

## When to refresh

If the upstream ABM is regenerated or these sims are reseeded, update both the source (Zenodo deposition) and bump `ZENODO_DOI` in `scripts/fetch_example_data.py`. Record the change in an ADR (`docs/adr/`).
