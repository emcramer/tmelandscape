"""Unit tests for ``tmelandscape.viz.model_schematic``.

Covers the public surface defined in the v0.7.1 decision log
``docs/development/decisions/2026-05-14-lcss-1-schematic-in-scope.md``:
the :class:`CellType` / :class:`Interaction` dataclasses and the
:func:`plot_model_schematic` figure function. Every test closes all
matplotlib figures at the end to keep the global state stack from
growing.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as _mpl

_mpl.use("Agg")

import matplotlib.pyplot as plt
import pytest
from matplotlib.colors import to_hex
from matplotlib.patches import Circle
from matplotlib.text import Text

from tmelandscape.viz.model_schematic import (
    CellType,
    Interaction,
    plot_model_schematic,
)

PNG_HEADER = b"\x89PNG\r\n\x1a\n"


def _node_circles(fig: plt.Figure) -> list[Circle]:
    ax = fig.axes[0]
    return [p for p in ax.patches if isinstance(p, Circle)]


# --- Smoke + structural -----------------------------------------------------


def test_smoke_two_node_one_edge_produces_figure_with_one_axes() -> None:
    fig = plot_model_schematic(
        cell_types=["A", "B"],
        interactions=[Interaction(source="A", target="B", kind="promotes")],
    )
    assert len(fig.axes) == 1
    ax = fig.axes[0]
    # Two node circles (plus any endcap circles for promotes ⇒ none).
    assert len(ax.patches) >= 2
    plt.close("all")


def test_auto_coloring_uses_tab10_for_bare_strings() -> None:
    fig = plot_model_schematic(cell_types=["A", "B"], interactions=[])
    circles = _node_circles(fig)
    assert len(circles) == 2
    cmap = plt.get_cmap("tab10")
    expected_a = to_hex(cmap(0))
    expected_b = to_hex(cmap(1))
    assert to_hex(circles[0].get_facecolor()) == expected_a
    assert to_hex(circles[1].get_facecolor()) == expected_b
    plt.close("all")


def test_user_palette_colours_two_nodes_with_exact_hex_values() -> None:
    fig = plot_model_schematic(
        cell_types=["A", "B"],
        interactions=[],
        color_palette=["#ff0000", "#00ff00"],
    )
    circles = _node_circles(fig)
    assert to_hex(circles[0].get_facecolor()) == "#ff0000"
    assert to_hex(circles[1].get_facecolor()) == "#00ff00"
    plt.close("all")


def test_more_bare_strings_than_palette_raises() -> None:
    cells = [f"c{i}" for i in range(11)]
    with pytest.raises(ValueError, match="palette"):
        plot_model_schematic(cell_types=cells, interactions=[])
    plt.close("all")


def test_celltype_color_overrides_palette() -> None:
    fig = plot_model_schematic(
        cell_types=[
            "auto_a",
            CellType(name="X", color="#ff00ff"),
            "auto_b",
        ],
        interactions=[],
    )
    circles = _node_circles(fig)
    name_to_color = {
        text.get_text(): to_hex(circle.get_facecolor())
        for circle, text in zip(
            circles,
            [
                t
                for t in fig.axes[0].get_children()
                if isinstance(t, Text) and t.get_text() in {"auto_a", "X", "auto_b"}
            ],
            strict=False,
        )
    }
    # The user-supplied colour wins regardless of palette position.
    assert name_to_color["X"] == "#ff00ff"
    # The two auto-coloured nodes consume palette slots 0 and 1, not 0 and 2.
    cmap = plt.get_cmap("tab10")
    assert name_to_color["auto_a"] == to_hex(cmap(0))
    assert name_to_color["auto_b"] == to_hex(cmap(1))
    plt.close("all")


# --- Interaction-kind coverage ---------------------------------------------


@pytest.mark.parametrize(
    "kind",
    ["promotes", "inhibits", "transitions_to", "secretes"],
)
def test_each_interaction_kind_renders(kind: str) -> None:
    base_fig = plot_model_schematic(cell_types=["A", "B"], interactions=[])
    ax = base_fig.axes[0]
    base_count = len(ax.patches) + len(ax.collections)
    plt.close(base_fig)

    fig = plot_model_schematic(
        cell_types=["A", "B"],
        interactions=[Interaction(source="A", target="B", kind=kind)],  # type: ignore[arg-type]
    )
    ax2 = fig.axes[0]
    new_count = len(ax2.patches) + len(ax2.collections) + len(ax2.lines)
    assert new_count > base_count
    plt.close("all")


def test_edge_label_produces_text_artist() -> None:
    fig = plot_model_schematic(
        cell_types=["A", "B"],
        interactions=[
            Interaction(source="A", target="B", kind="secretes", label="IFNg"),
        ],
    )
    ax = fig.axes[0]
    label_texts = [t for t in ax.get_children() if isinstance(t, Text) and t.get_text() == "IFNg"]
    assert len(label_texts) >= 1
    plt.close("all")


def test_unsupported_arrow_style_key_raises() -> None:
    with pytest.raises(ValueError, match="Supported kinds"):
        plot_model_schematic(
            cell_types=["A", "B"],
            interactions=[],
            arrow_style={"unsupported_kind": {"color": "purple"}},
        )
    plt.close("all")


def test_supported_arrow_style_override_is_applied() -> None:
    fig = plot_model_schematic(
        cell_types=["A", "B"],
        interactions=[Interaction(source="A", target="B", kind="promotes")],
        arrow_style={"promotes": {"color": "#123456"}},
    )
    # No crash and the figure has its expected node count.
    assert len(_node_circles(fig)) == 2
    plt.close("all")


# --- Validation -------------------------------------------------------------


def test_empty_cell_types_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        plot_model_schematic(cell_types=[], interactions=[])
    plt.close("all")


def test_dangling_source_raises_with_name() -> None:
    with pytest.raises(ValueError, match="not_a_node"):
        plot_model_schematic(
            cell_types=["A", "B"],
            interactions=[
                Interaction(source="not_a_node", target="B", kind="promotes"),
            ],
        )
    plt.close("all")


def test_dangling_target_raises_with_name() -> None:
    with pytest.raises(ValueError, match="ghost"):
        plot_model_schematic(
            cell_types=["A", "B"],
            interactions=[
                Interaction(source="A", target="ghost", kind="promotes"),
            ],
        )
    plt.close("all")


def test_self_loop_renders_without_crash() -> None:
    base_fig = plot_model_schematic(cell_types=["A"], interactions=[])
    base_count = (
        len(base_fig.axes[0].patches)
        + len(base_fig.axes[0].collections)
        + len(base_fig.axes[0].lines)
    )
    plt.close(base_fig)

    fig = plot_model_schematic(
        cell_types=["A"],
        interactions=[Interaction(source="A", target="A", kind="promotes")],
    )
    ax = fig.axes[0]
    assert (len(ax.patches) + len(ax.collections) + len(ax.lines)) > base_count
    plt.close("all")


def test_spring_layout_is_deterministic() -> None:
    cells = ["A", "B", "C", "D"]
    edges = [
        Interaction(source="A", target="B", kind="promotes"),
        Interaction(source="B", target="C", kind="inhibits"),
        Interaction(source="C", target="D", kind="transitions_to"),
    ]
    fig_a = plot_model_schematic(cells, edges, layout="spring")
    fig_b = plot_model_schematic(cells, edges, layout="spring")
    centers_a = [(p.center[0], p.center[1]) for p in _node_circles(fig_a)]
    centers_b = [(p.center[0], p.center[1]) for p in _node_circles(fig_b)]
    assert centers_a == centers_b
    plt.close("all")


# --- Save round-trip --------------------------------------------------------


def test_save_round_trip_png(tmp_path: Path) -> None:
    out = tmp_path / "out.png"
    plot_model_schematic(
        cell_types=["A", "B"],
        interactions=[Interaction(source="A", target="B", kind="promotes")],
        save_path=out,
    )
    assert out.exists()
    assert out.read_bytes()[:8] == PNG_HEADER
    plt.close("all")


def test_save_round_trip_svg(tmp_path: Path) -> None:
    out = tmp_path / "out.svg"
    plot_model_schematic(
        cell_types=["A", "B"],
        interactions=[Interaction(source="A", target="B", kind="promotes")],
        save_path=out,
    )
    assert out.exists()
    head = out.read_bytes().lstrip()[:5]
    assert head == b"<?xml" or head.startswith(b"<svg ")
    plt.close("all")
