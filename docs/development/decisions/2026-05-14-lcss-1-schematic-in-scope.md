# Decision: LCSS Figure 1 is in scope as a programmatic schematic generator

- **Date:** 2026-05-14 (UTC)
- **Status:** Accepted
- **Owner / decider:** Eric

## Context

The Phase 6 scope-research pass treated LCSS Figure 1 as **out of
scope for a Python function** — it was characterised as a hand-drawn
BioRender schematic of the ABM signalling architecture, with no
underlying data behind the figure. The Phase 6 task file accordingly
flagged it as "ships as a static SVG asset" in the
[Phase 6 session log](./2026-05-14-phase-6-session.md) and in
[`docs/concepts/viz.md`](../../concepts/viz.md). Eric was asked to
provide a hand-drafted SVG.

Eric's response, 2026-05-14 (second clarification of the session):

> The goal of this project is NOT to recreate the figures exactly,
> but to create a package that can create these figures from new
> models or new data. The LCSS figure 1 schematic shows the
> agent-based model used in the project by displaying the types of
> entities (cell types), their relationships or interactions, and
> the nature of those relationships. I want the package to be able
> to generate a similar schematic for any provided model given the
> names of the cell types present and the rules of the model. This
> doesn't need to use fancy Biorender icons. It can used colored
> circles with text labels and generate a SVG image.

This reframes the figure. The `tmelandscape` package's mission is to
produce these visualisations *for new models, new data* — not to
replicate the exact pixels of the published LCSS paper. LCSS Fig 1 is
therefore a **schematic-generator function** whose input is a
user-supplied model description (cell types + interaction rules) and
whose output is an SVG (or PNG) figure of coloured nodes + labelled
arrows.

## Decision

Add a new public function `tmelandscape.viz.model_schematic.plot_model_schematic(...)`
producing the schematic from a structured model description. v0.7.1
includes:

- A `CellType` dataclass: `(name: str, color: str | None, category: str | None)`.
- An `Interaction` dataclass: `(source: str, target: str, kind: Literal[...], label: str | None)` where `kind` is one of `"promotes"`, `"inhibits"`, `"transitions_to"`, `"secretes"`. Future kinds can be added on demand.
- The function:

  ```python
  def plot_model_schematic(
      cell_types: Sequence[str | CellType],
      interactions: Sequence[Interaction],
      *,
      layout: Literal["circular", "spring"] = "circular",
      color_palette: Sequence[str] | None = None,
      node_radius: float = 0.15,
      arrow_style: dict[str, dict[str, str]] | None = None,
      save_path: str | Path | None = None,
  ) -> matplotlib.figure.Figure: ...
  ```

  - `cell_types` accepts plain strings (auto-coloured via a palette) or
    `CellType` instances (user-supplied colour).
  - `interactions` is a flat list of `Interaction` objects.
  - `layout="circular"` arranges nodes on a unit circle; `"spring"`
    uses `networkx.spring_layout` (networkx is already in core deps
    per ADR 0007).
  - Arrow style varies by `kind`: `"promotes"` → green arrow; `"inhibits"`
    → red T-bar; `"transitions_to"` → blue dashed arrow; `"secretes"`
    → grey arrow with a small bound-circle. `arrow_style=` overrides
    the defaults.
  - `save_path` accepts `.svg` (vector) or `.png` (raster) per
    `matplotlib`'s extension dispatch.

- An MCP tool wrapper `plot_model_schematic_tool` (consistent with the
  Phase 6 surface convention). The MCP tool accepts JSON-friendly
  list-of-dicts for `cell_types` and `interactions`.

- `list_viz_figures` catalogue entry updated to include LCSS-1 with
  the new tool name.

## Consequences

- **No external assets required.** The schematic ships as a function;
  there is no `docs/assets/lcss-figure-1-schematic.svg` placeholder
  pending Eric's hand-off.
- **Generic across models.** Phase 8+ figures that need a different
  ABM (e.g. a future variant with new cell types) reuse this function.
- **Reference oracle:** none. The reference notebooks don't produce
  this figure; the LCSS paper's Fig 1 is the visual reference, but the
  output need not be pixel-identical. Smoke + structure tests, not
  baseline image diffs.
- **Open Question removed:** STATUS no longer needs the "LCSS Figure 1
  schematic SVG — pending hand-off from Eric" open question.

## References

- Owner directive: 2026-05-14 transcript (the LCSS Fig 1 reframing).
- [Phase 6 task file](../../../tasks/07-visualisation-implementation.md)
- [Phase 6 session log](./2026-05-14-phase-6-session.md) (notes the
  pre-Option-5 status of LCSS-1).
