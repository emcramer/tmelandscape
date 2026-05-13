"""Dynamic discovery + dispatch over ``spatialtissuepy``'s metric registry.

This module is the **only** place in ``tmelandscape`` that knows how
``spatialtissuepy`` is organised. It deliberately does **not** hardcode any
panel of statistics: the catalogue is discovered at runtime from
``spatialtissuepy.summary.registry._registry``, which is populated by import
side effects in the ``spatialtissuepy`` submodules.

Design notes
------------
* :func:`available_metric_names` returns the set of legal names the user can
  put in ``SummarizeConfig.statistics``. The set is computed fresh on every
  call (~µs), so it tracks upstream registrations without a reload.
* :func:`describe_metric` returns a small JSON-friendly dict describing one
  metric (name, category, description, parameter schema, custom flag) for
  use by discovery tools (CLI / MCP).
* :func:`compute_panel` builds a :class:`spatialtissuepy.summary.StatisticsPanel`,
  loads it with the user's chosen statistics + parameters, and evaluates it
  against a ``SpatialTissueData`` instance. Output keys are passed through
  verbatim except for the optional interaction-key rewrite (controlled by
  :attr:`SummarizeConfig.rewrite_interaction_keys`).

ADR 0009 is the design record for this no-hardcoded-panel decision.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tmelandscape.config.summarize import SummarizeConfig


def _ensure_metrics_registered() -> None:
    """Force-import every ``spatialtissuepy`` submodule so its ``@register_metric``
    decorators populate the global registry.

    Idempotent: ``importlib.import_module`` caches in ``sys.modules`` so
    repeated calls are cheap.
    """
    import spatialtissuepy

    # Walk all subpackages recursively. We avoid using a hardcoded list of
    # subpackages so newly added spatialtissuepy modules are discovered
    # automatically.
    for _finder, name, _ispkg in pkgutil.walk_packages(
        spatialtissuepy.__path__,
        prefix="spatialtissuepy.",
    ):
        # Skip the MCP server (heavy optional deps) — its metrics, if any,
        # would also be re-registered by the modules it imports.
        if name.startswith("spatialtissuepy.mcp"):
            continue
        try:
            importlib.import_module(name)
        except Exception:
            # A submodule whose optional dep is missing should not block
            # discovery of the rest of the catalogue.
            continue


def _registry() -> Any:
    """Return ``spatialtissuepy``'s singleton registry, populated."""
    _ensure_metrics_registered()
    from spatialtissuepy.summary.registry import _registry as singleton

    return singleton


def available_metric_names() -> frozenset[str]:
    """Return the set of metric names currently registered in ``spatialtissuepy``.

    Computed fresh on every call so it tracks upstream registrations and any
    custom metrics the caller has registered with ``register_custom_metric``.
    """
    return frozenset(_registry().list_metrics())


def describe_metric(name: str) -> dict[str, Any]:
    """Return a JSON-friendly description of one metric.

    Keys: ``name``, ``category``, ``description``, ``custom``, ``parameters``.
    ``parameters`` maps parameter name -> short type name (``"int"``,
    ``"float"``, etc.) suitable for surfacing in CLI / MCP discovery output.
    """
    info = _registry().describe(name)
    params_raw = getattr(info, "parameters", None) or {}
    params: dict[str, str] = {
        k: (getattr(v, "__name__", None) or str(v)) for k, v in params_raw.items()
    }
    return {
        "name": getattr(info, "name", name),
        "category": getattr(info, "category", "unknown"),
        "description": getattr(info, "description", ""),
        "custom": getattr(info, "custom", False),
        "parameters": params,
    }


def list_available_statistics() -> list[dict[str, Any]]:
    """Return a list of metric descriptions for every available statistic.

    Equivalent to ``[describe_metric(n) for n in sorted(available_metric_names())]``.
    Surfaced as a CLI verb and an MCP tool so agents can discover the
    catalogue before they construct a :class:`SummarizeConfig`.
    """
    return [describe_metric(n) for n in sorted(available_metric_names())]


def _rewrite_interaction_keys(stats: dict[str, float]) -> dict[str, float]:
    """Rewrite ``interaction_<src>_<dst>`` keys to ``interaction_<src>|<dst>``.

    Cell-type names commonly contain underscores (``M0_macrophage``,
    ``effector_T_cell``), so the upstream key shape is genuinely ambiguous.
    We can't always disambiguate from the key alone (the cell-type
    vocabulary is per-timepoint), but we can rewrite using the registered
    cell-type list at call sites where it is known. This helper is the
    cheaper fallback: it doesn't try to recover ``(src, dst)`` from an
    ambiguous key — it just replaces the *last* underscore with ``|`` when
    no ``|`` is already present, which is correct whenever exactly one of
    src/dst names lacks an underscore. The driver provides the precise
    vocabulary-aware variant via :func:`rewrite_interaction_keys_with_types`.
    """
    out: dict[str, float] = {}
    for key, val in stats.items():
        if key.startswith("interaction_") and "|" not in key:
            body = key[len("interaction_") :]
            sep = body.rfind("_")
            if sep > 0:
                out[f"interaction_{body[:sep]}|{body[sep + 1 :]}"] = val
                continue
        out[key] = val
    return out


def rewrite_interaction_keys_with_types(
    stats: dict[str, float],
    cell_types: list[str],
) -> dict[str, float]:
    """Precise variant: rewrite ``interaction_<src>_<dst>`` using a known
    cell-type vocabulary so even underscore-bearing type names disambiguate.

    Falls back to the heuristic in :func:`_rewrite_interaction_keys` if a
    key does not match any expected ``(src, dst)`` pair from the vocabulary.
    """
    expected: dict[str, tuple[str, str]] = {
        f"interaction_{a}_{b}": (a, b) for a in cell_types for b in cell_types
    }
    out: dict[str, float] = {}
    for key, val in stats.items():
        if key in expected:
            a, b = expected[key]
            out[f"interaction_{a}|{b}"] = val
        elif key.startswith("interaction_") and "|" not in key:
            # Vocabulary-unaware fallback.
            body = key[len("interaction_") :]
            sep = body.rfind("_")
            if sep > 0:
                out[f"interaction_{body[:sep]}|{body[sep + 1 :]}"] = val
                continue
            out[key] = val
        else:
            out[key] = val
    return out


def compute_panel(
    *,
    spatial_data: Any,
    config: SummarizeConfig,
) -> dict[str, float]:
    """Evaluate the user's :class:`SummarizeConfig` against one timepoint.

    Builds a :class:`spatialtissuepy.summary.StatisticsPanel`, adds every
    :class:`StatisticSpec` from the config, calls ``panel.compute(spatial_data)``,
    and (optionally) rewrites interaction keys for unambiguous downstream
    indexing.

    Parameters
    ----------
    spatial_data
        A ``spatialtissuepy.core.spatial_data.SpatialTissueData`` instance
        for the timepoint. Typed as ``Any`` to keep this module importable
        without the upstream package at runtime.
    config
        The user-supplied :class:`SummarizeConfig`.

    Returns
    -------
    dict[str, float]
        Flat name -> scalar mapping. Matrix-valued metrics are flattened
        into one key per pair by spatialtissuepy itself; we do not further
        reshape.
    """
    from spatialtissuepy.summary import StatisticsPanel

    _ensure_metrics_registered()

    panel = StatisticsPanel()
    for spec in config.statistics:
        panel.add(spec.name, **spec.parameters)
    raw: dict[str, Any] = dict(panel.compute(spatial_data))
    out: dict[str, float] = {k: float(v) for k, v in raw.items()}

    if not config.rewrite_interaction_keys:
        return out

    raw_types = getattr(spatial_data, "cell_types_unique", None)
    # `cell_types_unique` is a numpy array; use len() rather than truthiness to
    # decide whether to take the vocabulary-aware rewrite path.
    if raw_types is not None and len(raw_types) > 0:
        return rewrite_interaction_keys_with_types(out, [str(t) for t in raw_types])
    return _rewrite_interaction_keys(out)
