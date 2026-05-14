"""Programmatic ABM model schematic generator (LCSS Figure 1, reframed).

This module ships a single public function :func:`plot_model_schematic`
plus its two input dataclasses :class:`CellType` and :class:`Interaction`.
The figure is the package's generic answer to "draw the ABM": given a
list of cell-type nodes and a list of typed interactions between them,
render a directed graph schematic of coloured circles + labelled arrows.

The function is intentionally model-agnostic — pass any cell-type list
and interaction list, not just the LCSS paper's specific model. See the
decision log
``docs/development/decisions/2026-05-14-lcss-1-schematic-in-scope.md``
for the rationale that supersedes the earlier "ship as a static SVG
asset" plan.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import matplotlib.figure as mfig
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from matplotlib.axes import Axes
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, FancyArrowPatch

_InteractionKind = Literal["promotes", "inhibits", "transitions_to", "secretes"]

_SUPPORTED_KINDS: tuple[_InteractionKind, ...] = (
    "promotes",
    "inhibits",
    "transitions_to",
    "secretes",
)

# Default arrow styling per interaction kind. Each entry is the kwargs
# passed to :class:`matplotlib.patches.FancyArrowPatch`. ``arrowstyle``
# uses matplotlib's textual style strings.
_DEFAULT_ARROW_STYLE: dict[_InteractionKind, dict[str, Any]] = {
    "promotes": {
        "arrowstyle": "-|>",
        "color": "#2ca02c",
        "linewidth": 2.0,
        "linestyle": "solid",
        "mutation_scale": 16,
    },
    "inhibits": {
        # Drawn as a coloured line; a perpendicular T-bar is added at
        # the head separately (see ``_draw_inhibits_endcap``).
        "arrowstyle": "-",
        "color": "#d62728",
        "linewidth": 2.0,
        "linestyle": "solid",
        "mutation_scale": 12,
    },
    "transitions_to": {
        "arrowstyle": "-|>",
        "color": "#1f77b4",
        "linewidth": 2.0,
        "linestyle": "dashed",
        "mutation_scale": 16,
    },
    "secretes": {
        # No arrowhead; a small open circle is placed at the target end
        # (see ``_draw_secretes_endcap``) to indicate ligand/receptor
        # binding.
        "arrowstyle": "-",
        "color": "#7f7f7f",
        "linewidth": 1.6,
        "linestyle": "solid",
        "mutation_scale": 12,
    },
}


@dataclass(frozen=True)
class CellType:
    """One node in the ABM schematic.

    Attributes
    ----------
    name
        Display label for the node.
    color
        Matplotlib-compatible colour (hex, RGB tuple as string, or named
        colour). ``None`` => auto-assigned from ``color_palette``.
    category
        Optional grouping label (e.g. ``"tumour"`` / ``"immune"`` /
        ``"stromal"``). Currently used only for documentation; future
        versions may use it to group same-category cells visually.
    """

    name: str
    color: str | None = None
    category: str | None = None


@dataclass(frozen=True)
class Interaction:
    """One directed edge in the ABM schematic.

    Attributes
    ----------
    source
        Name of the originating cell type (must match a ``CellType.name``).
    target
        Name of the receiving cell type.
    kind
        Relationship type. Determines the visual encoding:

        - ``"promotes"`` -> green solid arrow.
        - ``"inhibits"`` -> red line with a perpendicular T-bar at the
          target end.
        - ``"transitions_to"`` -> blue dashed arrow (e.g. cM0 -> cM1
          polarisation).
        - ``"secretes"`` -> grey solid line with an open-circle endpoint
          (cytokine / signalling factor binding indicator).
    label
        Optional text annotation (e.g. cytokine name "IFN-gamma").
    """

    source: str
    target: str
    kind: _InteractionKind
    label: str | None = None


def plot_model_schematic(
    cell_types: Sequence[str | CellType],
    interactions: Sequence[Interaction],
    *,
    layout: Literal["circular", "spring"] = "circular",
    color_palette: Sequence[str] | None = None,
    node_radius: float = 0.15,
    arrow_style: dict[str, dict[str, str]] | None = None,
    save_path: str | Path | None = None,
) -> mfig.Figure:
    """Render an ABM model schematic.

    Generic across any user-provided model: nodes are cell types,
    edges are typed interactions. The schematic is visual, not
    quantitative — there are no axis units or data behind it.

    Parameters
    ----------
    cell_types
        Nodes of the schematic. Each entry is either a bare string (the
        node name, auto-coloured from ``color_palette``) or a
        :class:`CellType` instance (carries its own colour).
    interactions
        Directed edges between cell types. Each :class:`Interaction`
        names the source and target cell-type names (must match the
        names in ``cell_types``); the visual encoding is set by
        ``Interaction.kind``.
    layout
        How to position nodes. ``"circular"`` (default) lays them out
        evenly around a unit circle. ``"spring"`` uses
        :func:`networkx.spring_layout` over the directed graph with a
        fixed seed for determinism.
    color_palette
        Sequence of matplotlib colour strings used to auto-colour
        bare-string cell types. ``None`` => matplotlib's ``tab10``.
        Raises ``ValueError`` if more bare strings than palette
        entries are supplied without a custom palette.
    node_radius
        Radius of the node circles in axis units.
    arrow_style
        Optional override map ``{kind: {style_kwarg: value}}`` that
        replaces (per-key) the default arrow style for the named
        kinds. Unknown kinds raise ``ValueError`` listing the supported
        kinds.
    save_path
        If given, ``fig.savefig(save_path, bbox_inches="tight",
        dpi=150)``. matplotlib's extension dispatch selects PNG vs SVG
        from the suffix.

    Returns
    -------
    matplotlib.figure.Figure

    Raises
    ------
    ValueError
        If an ``Interaction`` references a cell-type name that is not
        in ``cell_types``; if ``cell_types`` is empty; if the number of
        bare-string cell types exceeds the palette length; if
        ``arrow_style`` keys include an unsupported kind.

    Notes
    -----
    Reference: LCSS Figure 1 (concept). The package is intentionally
    generic — pass any cell-type list and interaction list, not just
    the LCSS paper's. See decision log
    ``2026-05-14-lcss-1-schematic-in-scope.md``.
    """
    if len(cell_types) == 0:
        raise ValueError("`cell_types` must be a non-empty sequence of nodes.")

    resolved_arrow_style = _resolve_arrow_style(arrow_style)
    node_colors = _resolve_node_colors(cell_types, color_palette)
    node_names = list(node_colors.keys())

    _validate_interactions(interactions, node_names)

    positions = _layout_positions(node_names, interactions, layout=layout)

    fig, ax = plt.subplots(figsize=(8, 8))
    _setup_axes(ax, positions, node_radius)

    for name in node_names:
        x, y = positions[name]
        ax.add_patch(
            Circle(
                (x, y),
                radius=node_radius,
                facecolor=node_colors[name],
                edgecolor="black",
                linewidth=1.2,
                zorder=2,
            )
        )
        ax.text(
            x,
            y,
            name,
            ha="center",
            va="center",
            fontsize=10,
            zorder=3,
            wrap=True,
        )

    for interaction in interactions:
        _draw_interaction(
            ax,
            interaction,
            positions=positions,
            node_radius=node_radius,
            arrow_style=resolved_arrow_style,
        )

    if save_path is not None:
        out_path = Path(save_path).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, bbox_inches="tight", dpi=150)

    return fig


# --- internals --------------------------------------------------------------


def _resolve_arrow_style(
    arrow_style: dict[str, dict[str, str]] | None,
) -> dict[_InteractionKind, dict[str, Any]]:
    """Merge user-supplied per-kind style overrides into the defaults."""
    merged: dict[_InteractionKind, dict[str, Any]] = {
        kind: dict(style) for kind, style in _DEFAULT_ARROW_STYLE.items()
    }
    if arrow_style is None:
        return merged
    bad = [k for k in arrow_style if k not in _SUPPORTED_KINDS]
    if bad:
        raise ValueError(
            f"`arrow_style` contains unsupported kind(s) {bad}. "
            f"Supported kinds: {list(_SUPPORTED_KINDS)}."
        )
    for kind, overrides in arrow_style.items():
        # ``kind`` is known-good by the check above; cast to the Literal
        # so the dict-key type matches ``merged``.
        merged[cast(_InteractionKind, kind)].update(overrides)
    return merged


def _resolve_node_colors(
    cell_types: Sequence[str | CellType],
    color_palette: Sequence[str] | None,
) -> dict[str, str]:
    """Resolve a final ``{name: colour}`` map honouring per-node overrides."""
    palette: Sequence[str]
    if color_palette is None:
        cmap = plt.get_cmap("tab10")
        palette = [_rgba_to_hex(cmap(i)) for i in range(cmap.N)]
    else:
        palette = list(color_palette)

    bare_indices: list[int] = []
    normalized: list[CellType] = []
    for entry in cell_types:
        if isinstance(entry, CellType):
            normalized.append(entry)
        else:
            normalized.append(CellType(name=entry))
            bare_indices.append(len(normalized) - 1)

    if color_palette is not None and len(bare_indices) > len(palette):
        raise ValueError(
            f"received {len(bare_indices)} bare-string cell type(s) but the "
            f"supplied `color_palette` only has {len(palette)} entries."
        )
    if color_palette is None and len(bare_indices) > len(palette):
        raise ValueError(
            f"received {len(bare_indices)} bare-string cell type(s) but the "
            f"default tab10 palette only has {len(palette)} entries. Pass a "
            "custom `color_palette` covering every bare-string node."
        )

    colors: dict[str, str] = {}
    palette_cursor = 0
    seen: set[str] = set()
    for ct in normalized:
        if ct.name in seen:
            raise ValueError(
                f"cell type name {ct.name!r} appears more than once in "
                "`cell_types`; names must be unique."
            )
        seen.add(ct.name)
        if ct.color is not None:
            colors[ct.name] = ct.color
        else:
            colors[ct.name] = palette[palette_cursor]
            palette_cursor += 1
    return colors


def _rgba_to_hex(rgba: tuple[float, float, float, float]) -> str:
    r, g, b, _ = rgba
    return f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"


def _validate_interactions(
    interactions: Sequence[Interaction],
    node_names: Sequence[str],
) -> None:
    names = set(node_names)
    for ix in interactions:
        if ix.source not in names:
            raise ValueError(
                f"interaction source {ix.source!r} is not in `cell_types` "
                f"(known names: {sorted(names)})."
            )
        if ix.target not in names:
            raise ValueError(
                f"interaction target {ix.target!r} is not in `cell_types` "
                f"(known names: {sorted(names)})."
            )
        if ix.kind not in _SUPPORTED_KINDS:
            raise ValueError(
                f"interaction kind {ix.kind!r} is not supported. "
                f"Supported kinds: {list(_SUPPORTED_KINDS)}."
            )


def _layout_positions(
    node_names: Sequence[str],
    interactions: Sequence[Interaction],
    *,
    layout: Literal["circular", "spring"],
) -> dict[str, tuple[float, float]]:
    graph = nx.DiGraph()
    for name in node_names:
        graph.add_node(name)
    for ix in interactions:
        graph.add_edge(ix.source, ix.target)

    if layout == "circular":
        raw = nx.circular_layout(graph)
    elif layout == "spring":
        raw = nx.spring_layout(graph, seed=42)
    else:  # pragma: no cover - guarded by Literal at the type level.
        raise ValueError(f"unknown layout {layout!r}; expected one of 'circular', 'spring'.")

    return {str(node): (float(xy[0]), float(xy[1])) for node, xy in raw.items()}


def _setup_axes(
    ax: Axes,
    positions: dict[str, tuple[float, float]],
    node_radius: float,
) -> None:
    xs = [p[0] for p in positions.values()]
    ys = [p[1] for p in positions.values()]
    # Pad so node circles and self-loops are not clipped by the axes
    # frame even when nodes sit on the unit circle boundary.
    pad = max(node_radius * 2.5, 0.2)
    ax.set_xlim(min(xs) - pad, max(xs) + pad)
    ax.set_ylim(min(ys) - pad, max(ys) + pad)
    ax.set_aspect("equal")
    ax.set_axis_off()


def _draw_interaction(
    ax: Axes,
    interaction: Interaction,
    *,
    positions: dict[str, tuple[float, float]],
    node_radius: float,
    arrow_style: dict[_InteractionKind, dict[str, Any]],
) -> None:
    style = arrow_style[interaction.kind]

    if interaction.source == interaction.target:
        _draw_self_loop(
            ax,
            position=positions[interaction.source],
            node_radius=node_radius,
            kind=interaction.kind,
            style=style,
            label=interaction.label,
        )
        return

    src = np.asarray(positions[interaction.source], dtype=float)
    tgt = np.asarray(positions[interaction.target], dtype=float)

    # FancyArrowPatch's shrinkA/shrinkB are measured in display points,
    # not data units; convert node_radius (data units) to points using
    # the current axes scale so the arrow always stops at the circle's
    # edge regardless of figure size.
    shrink_points = _data_radius_to_points(ax, node_radius)

    patch_kwargs = {
        "posA": (float(src[0]), float(src[1])),
        "posB": (float(tgt[0]), float(tgt[1])),
        "shrinkA": shrink_points,
        "shrinkB": shrink_points,
        "zorder": 1,
        **style,
    }
    arrow = FancyArrowPatch(**patch_kwargs)
    ax.add_patch(arrow)

    if interaction.kind == "inhibits":
        _draw_inhibits_endcap(
            ax,
            src=src,
            tgt=tgt,
            node_radius=node_radius,
            color=str(style.get("color", "#d62728")),
            linewidth=float(cast(float, style.get("linewidth", 2.0))),
        )
    elif interaction.kind == "secretes":
        _draw_secretes_endcap(
            ax,
            src=src,
            tgt=tgt,
            node_radius=node_radius,
            color=str(style.get("color", "#7f7f7f")),
            linewidth=float(cast(float, style.get("linewidth", 1.6))),
        )

    if interaction.label is not None:
        _draw_edge_label(ax, src=src, tgt=tgt, label=interaction.label)


def _data_radius_to_points(ax: Axes, radius_data_units: float) -> float:
    """Convert a data-unit radius to display points for arrow shrinking."""
    fig = ax.figure
    if fig is None:  # pragma: no cover - defensive; ax always has a figure
        return 0.0
    bbox = ax.get_window_extent()
    x_lim = ax.get_xlim()
    y_lim = ax.get_ylim()
    x_span = x_lim[1] - x_lim[0]
    y_span = y_lim[1] - y_lim[0]
    if x_span <= 0 or y_span <= 0:  # pragma: no cover - defensive
        return 0.0
    pixels_per_data_x = bbox.width / x_span
    pixels_per_data_y = bbox.height / y_span
    pixels = radius_data_units * min(pixels_per_data_x, pixels_per_data_y)
    dpi = float(fig.dpi)
    return float(pixels * 72.0 / dpi)


def _draw_inhibits_endcap(
    ax: Axes,
    *,
    src: np.ndarray,
    tgt: np.ndarray,
    node_radius: float,
    color: str,
    linewidth: float,
) -> None:
    """Draw a perpendicular T-bar just outside the target node."""
    direction = tgt - src
    norm = float(np.linalg.norm(direction))
    if norm == 0.0:  # pragma: no cover - guarded by self-loop branch.
        return
    unit = direction / norm
    perp = np.array([-unit[1], unit[0]])
    bar_center = tgt - unit * node_radius
    half = node_radius * 0.6
    p0 = bar_center + perp * half
    p1 = bar_center - perp * half
    ax.add_line(
        Line2D(
            [p0[0], p1[0]],
            [p0[1], p1[1]],
            color=color,
            linewidth=linewidth,
            zorder=1,
        )
    )


def _draw_secretes_endcap(
    ax: Axes,
    *,
    src: np.ndarray,
    tgt: np.ndarray,
    node_radius: float,
    color: str,
    linewidth: float,
) -> None:
    """Draw an open-circle (ligand-binds-receptor) marker at the target."""
    direction = tgt - src
    norm = float(np.linalg.norm(direction))
    if norm == 0.0:  # pragma: no cover - guarded by self-loop branch.
        return
    unit = direction / norm
    cap_radius = node_radius * 0.25
    cap_center = tgt - unit * (node_radius + cap_radius)
    ax.add_patch(
        Circle(
            (float(cap_center[0]), float(cap_center[1])),
            radius=cap_radius,
            facecolor="white",
            edgecolor=color,
            linewidth=linewidth,
            zorder=2,
        )
    )


def _draw_self_loop(
    ax: Axes,
    *,
    position: tuple[float, float],
    node_radius: float,
    kind: _InteractionKind,
    style: dict[str, Any],
    label: str | None,
) -> None:
    """Draw a small circular arc around the node for self-interactions."""
    loop_radius = node_radius * 0.9
    center = (position[0] + node_radius + loop_radius * 0.6, position[1] + node_radius)
    # FancyArrowPatch with a connection-style angle3 across a tiny
    # offset gives a clean circular hook around the node.
    offset = node_radius * 0.5
    pos_a = (center[0] - offset, center[1] + offset)
    pos_b = (center[0] + offset, center[1] - offset)
    arrow = FancyArrowPatch(
        posA=pos_a,
        posB=pos_b,
        connectionstyle=f"arc3,rad={loop_radius * 4:.3f}",
        zorder=1,
        **style,
    )
    ax.add_patch(arrow)

    if kind == "inhibits":
        ax.add_line(
            Line2D(
                [pos_b[0] - node_radius * 0.3, pos_b[0] + node_radius * 0.3],
                [pos_b[1], pos_b[1]],
                color=str(style.get("color", "#d62728")),
                linewidth=float(cast(float, style.get("linewidth", 2.0))),
                zorder=1,
            )
        )
    elif kind == "secretes":
        ax.add_patch(
            Circle(
                (pos_b[0], pos_b[1] - node_radius * 0.25),
                radius=node_radius * 0.18,
                facecolor="white",
                edgecolor=str(style.get("color", "#7f7f7f")),
                linewidth=float(cast(float, style.get("linewidth", 1.6))),
                zorder=2,
            )
        )

    if label is not None:
        ax.text(
            center[0] + loop_radius * 0.6,
            center[1] + loop_radius * 0.6,
            label,
            ha="left",
            va="bottom",
            fontsize=8,
            zorder=3,
        )


def _draw_edge_label(
    ax: Axes,
    *,
    src: np.ndarray,
    tgt: np.ndarray,
    label: str,
) -> None:
    midpoint = 0.5 * (src + tgt)
    direction = tgt - src
    norm = float(np.linalg.norm(direction))
    if norm == 0.0:  # pragma: no cover - guarded earlier
        offset = np.array([0.0, 0.0])
    else:
        unit = direction / norm
        perp = np.array([-unit[1], unit[0]])
        offset = perp * 0.04
    ax.text(
        float(midpoint[0] + offset[0]),
        float(midpoint[1] + offset[1]),
        label,
        ha="center",
        va="center",
        fontsize=8,
        zorder=3,
    )


__all__ = [
    "CellType",
    "Interaction",
    "plot_model_schematic",
]
