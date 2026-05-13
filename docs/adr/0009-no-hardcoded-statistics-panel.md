# 0009 — No hardcoded statistics panel; dynamic discovery via spatialtissuepy

- **Status:** Accepted (supersedes Phase 3's default panel)
- **Date:** 2026-05-13
- **Deciders:** Eric, Claude

## Context

Phase 3 (v0.2.0) shipped `tmelandscape.summarize` with a built-in default
panel of six "LCSS paper" statistics — `cell_counts`, `cell_type_fractions`,
three centrality means, and `interaction_strength_matrix`. The defaults
lived as a `_default_statistics()` factory in `SummarizeConfig` plus a
hardcoded `KNOWN_STATISTICS` frozenset in the registry.

The project owner reviewed this and rejected both:

> "DON'T hardcode the spatial statistics panel! This should be collected
> via interaction with the user."

The rationale is application-portability. tmelandscape is intended for use
across cancer types and ABM frameworks; the right panel of statistics is a
**user decision**, not a package convention. Baking the LCSS panel in
implicitly tells every future user "use these six," which constrains the
science.

In parallel, `tmelandscape.normalize.feature_filter.DEFAULT_DROP_COLUMNS`
listed six cell-density columns mirroring the reference oracle. The same
rationale applies: those drops were specific to one application, not
universal.

## Decision

1. **No default statistics panel.** `SummarizeConfig.statistics` is a
   required field with no default. Construction without an explicit panel
   raises `ValidationError` at config-construction time.
2. **Dynamic discovery.** Legal statistic names come from
   `spatialtissuepy.summary.registry._registry.list_metrics()`, queried
   fresh on every `SummarizeConfig` validation. New upstream registrations
   (including user `register_custom_metric` calls) are picked up
   automatically.
3. **Per-metric parameters.** `SummarizeConfig.statistics` is
   `list[StatisticSpec]` where each spec carries a name plus a
   `parameters` dict. Metrics with required arguments (`cell_type_ratio`,
   `colocalization_score`, ...) are usable this way. Plain strings are
   coerced into `StatisticSpec(name=...)` for cosmetic convenience.
4. **Discovery surfaces.** A `tmelandscape.summarize.list_available_statistics()`
   function returns the catalogue (name + category + description +
   parameter schema). Exposed as a CLI verb (`tmelandscape statistics list`)
   and an MCP tool (`list_available_statistics`) so agents can present the
   catalogue to a human, collect a choice, and then construct a
   `SummarizeConfig`.
5. **No feature-drop default.** `tmelandscape.normalize.feature_filter`
   ships no `DEFAULT_DROP_COLUMNS`. Phase 3.5's `NormalizeConfig` will
   expose an explicit `drop_columns: list[str] = []`.

## Consequences

- Users *must* think about which statistics they want; surprises are
  surfaced at config time rather than silently inheriting LCSS choices.
- New spatialtissuepy releases that add (or rename) metrics are picked up
  by tmelandscape automatically — no version-bump required to expose them.
- Custom user metrics (registered via `spatialtissuepy.register_custom_metric`)
  are first-class in tmelandscape too.
- The `compute_statistic` helper from Phase 3 is replaced by
  `compute_panel`, which builds a `StatisticsPanel`, adds the user's
  selections, and calls `panel.compute(spatial_data)`. tmelandscape no
  longer maintains a per-metric `_compute_*` adapter layer.
- The interaction-key disambiguation (`interaction_<src>|<dst>` instead
  of underscore-joined) survives as a generic post-processing pass keyed
  on whether the output key matches `interaction_*` — not on whether the
  user picked any specific named statistic. Toggled by
  `SummarizeConfig.rewrite_interaction_keys` (default `True`).
- Existing tests, fixtures, and the integration test that relied on the
  Phase 3 default panel have been updated to pass an explicit
  `statistics=[...]` argument.

## Alternatives considered

- **Keep the LCSS default panel and let users override.** Rejected by the
  project owner. The default constrains expectations even when it can be
  overridden.
- **Provide named "preset" panels (e.g. `LCSSPanel.statistics`).** Out of
  scope; presets can live in user-side helper code if useful, and the
  manuscripts themselves document the LCSS panel.
- **Validate metric names against a static list maintained inside
  tmelandscape.** Brittle: drifts whenever spatialtissuepy ships new
  metrics. Dynamic discovery from the registry is the single source of
  truth.
