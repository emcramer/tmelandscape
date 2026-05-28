"""Tests for the tissue_simulator wrapper that produces initial-condition CSVs.

All tests run against the hand-rolled structured source CSV at
``tests/data/ic_source_structured.csv`` (10 tumor + 12 fibroblast + 8 CD8
cells laid out so CD8↔tumor edges are exactly 0 under the default radius
graph). Tests that assert *exclusion-structure preservation* use
``scaffold_strategy="perturb_source"`` because uniform-random scaffold
geometry does not, in general, preserve cross-type adjacency on a 30-node
graph.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

from tmelandscape.sampling.tissue_init import IcGenResult, generate_initial_conditions

_REQUIRED_COLUMNS = {"x", "y", "z", "radius", "cell_type", "is_boundary"}
SOURCE_CSV = Path("tests/data/ic_source_structured.csv")


def _count_edges_by_pair(csv_path: Path, radius: float = 12.5) -> Counter[tuple[str, str]]:
    """Build a radius graph on the IC CSV and return per-type-pair edge counts."""
    from tissue_simulator import SpatialNetworkAnalyzer, load_tissue_from_csv

    tissue = load_tissue_from_csv(str(csv_path))
    analyzer = SpatialNetworkAnalyzer()
    g = analyzer.build_network_from_tissue(tissue, mode="radius", radius=radius)
    edges: Counter[tuple[str, str]] = Counter()
    for u, v in g.edges():
        pair = tuple(sorted([g.nodes[u]["cell_type"], g.nodes[v]["cell_type"]]))
        edges[pair] += 1
    return edges


def test_writes_expected_files_and_columns(tmp_path: Path) -> None:
    results = generate_initial_conditions(
        n_replicates=2,
        output_dir=tmp_path,
        seed=42,
        source_csv=SOURCE_CSV,
    )
    assert len(results) == 2
    assert [r.path.name for r in results] == ["ic_0000.csv", "ic_0001.csv"]
    for r in results:
        assert r.path.is_absolute()
        assert r.path.exists()
        df = pd.read_csv(r.path)
        assert _REQUIRED_COLUMNS.issubset(df.columns)
        assert len(df) == 30  # matches source node count exactly


def test_returns_ic_gen_result_per_replicate(tmp_path: Path) -> None:
    results = generate_initial_conditions(
        n_replicates=3,
        output_dir=tmp_path,
        seed=11,
        source_csv=SOURCE_CSV,
    )
    assert len(results) == 3
    seeds = [r.scaffold_seed for r in results]
    assert len(set(seeds)) == 3, "each replicate must spawn a distinct seed"
    for r in results:
        assert isinstance(r, IcGenResult)
        assert len(r.sha256) == 64
        assert r.sa_final_cost >= 0
        assert sum(r.achieved_proportions.values()) == pytest.approx(1.0, abs=1e-9)


def test_proportions_match_source_exactly(tmp_path: Path) -> None:
    results = generate_initial_conditions(
        n_replicates=2,
        output_dir=tmp_path,
        seed=42,
        source_csv=SOURCE_CSV,
    )
    expected = {"tumor": 10 / 30, "fibroblast": 12 / 30, "cd8": 8 / 30}
    for r in results:
        for cell_type, target in expected.items():
            assert r.achieved_proportions[cell_type] == pytest.approx(target, abs=1e-9)
        df = pd.read_csv(r.path)
        counts = df["cell_type"].value_counts().to_dict()
        assert counts == {"fibroblast": 12, "tumor": 10, "cd8": 8}


def test_cd8_tumor_edge_fraction_preserved_with_perturb_source(tmp_path: Path) -> None:
    """perturb_source preserves the source's geometric CD8/tumor exclusion."""
    results = generate_initial_conditions(
        n_replicates=2,
        output_dir=tmp_path,
        seed=2026,
        source_csv=SOURCE_CSV,
        scaffold_strategy="perturb_source",
    )
    source_edges = _count_edges_by_pair(SOURCE_CSV)
    assert source_edges.get(("cd8", "tumor"), 0) == 0
    total_source_edges = sum(source_edges.values())
    for r in results:
        ic_edges = _count_edges_by_pair(r.path)
        total_ic_edges = sum(ic_edges.values())
        source_frac = 0.0
        ic_frac = ic_edges.get(("cd8", "tumor"), 0) / max(total_ic_edges, 1)
        # Acceptance criterion: per-IC CD8-tumor edge fraction within 0.02 of source's.
        assert abs(ic_frac - source_frac) <= 0.02, (
            f"cd8-tumor edge fraction {ic_frac:.3f} too far from source "
            f"{source_frac:.3f} (ic edges {dict(ic_edges)}; source total {total_source_edges})"
        )


def test_same_seed_yields_identical_csvs(tmp_path: Path) -> None:
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    results_a = generate_initial_conditions(
        n_replicates=2,
        output_dir=dir_a,
        seed=2026,
        source_csv=SOURCE_CSV,
    )
    results_b = generate_initial_conditions(
        n_replicates=2,
        output_dir=dir_b,
        seed=2026,
        source_csv=SOURCE_CSV,
    )
    for a, b in zip(results_a, results_b, strict=True):
        assert a.path.read_bytes() == b.path.read_bytes()
        assert a.sha256 == b.sha256
        assert a.scaffold_seed == b.scaffold_seed


def test_creates_output_dir_if_missing(tmp_path: Path) -> None:
    nested = tmp_path / "does" / "not" / "exist"
    results = generate_initial_conditions(
        n_replicates=1,
        output_dir=nested,
        seed=0,
        source_csv=SOURCE_CSV,
    )
    assert nested.is_dir()
    assert results[0].path.parent == nested.resolve()


def test_perturb_source_preserves_node_count_and_types(tmp_path: Path) -> None:
    results = generate_initial_conditions(
        n_replicates=1,
        output_dir=tmp_path,
        seed=7,
        source_csv=SOURCE_CSV,
        scaffold_strategy="perturb_source",
    )
    df = pd.read_csv(results[0].path)
    assert len(df) == 30
    assert set(df["cell_type"]) == {"tumor", "fibroblast", "cd8"}


def test_n_replicates_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="n_replicates must be positive"):
        generate_initial_conditions(
            n_replicates=0,
            output_dir=tmp_path,
            seed=0,
            source_csv=SOURCE_CSV,
        )
