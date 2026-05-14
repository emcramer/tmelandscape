"""Pydantic config for the step-5 two-stage Leiden + Ward clustering step.

The :class:`ClusterConfig` is the frozen public contract between the driver
(:mod:`tmelandscape.cluster.cluster_ensemble`) and its callers (Python API,
CLI verb, MCP tool). It carries the user-chosen clustering strategy plus the
per-stage switches the reference oracle exposes, including the
auto-selection knobs for the final cluster count.

Binding invariants (see :doc:`/adr/0007-two-stage-leiden-ward-clustering` and
:doc:`/adr/0010-cluster-count-auto-selection`):

* **No silent default for `n_final_clusters`.** The field is ``int | None``
  with no package default value. Either the user supplies an explicit integer
  (``>= 2``) or they leave it ``None`` and the package picks ``k`` by
  optimising ``cluster_count_metric`` over the candidate range. There is no
  baked-in "6 TME states" assumption — the metric is named, the number falls
  out of the data. This mirrors ADR 0009's "no silent science-shaping
  default" precedent.
* **No hidden hardcoded strategy panel.** ``strategy`` is a ``Literal`` with
  exactly one member in v0.6.0 (``"leiden_ward"``). The literal shape admits
  future algorithm additions in v0.6.x without breaking the public surface.
* **Never collide on the output Dataset's data_vars dict.** Six named
  variables -- ``source_variable`` (read), ``leiden_labels_variable``,
  ``final_labels_variable``, ``cluster_means_variable``, ``linkage_variable``,
  and ``cluster_count_scores_variable`` -- share the output Dataset's
  namespace. Any pairwise collision would silently shadow data, so all six
  are required to be distinct at config-construction time.
* **Candidate-k range must be consistent.** When ``cluster_count_max`` is
  supplied, it must be ``>= cluster_count_min``; otherwise the candidate
  range is empty and auto-selection cannot run. Validated at construction
  time.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClusterConfig(BaseModel):
    """User-supplied configuration for ``cluster_ensemble``.

    Attributes
    ----------
    strategy
        Which clustering algorithm to apply. Only ``"leiden_ward"`` exists
        in v0.6.0 (the reference algorithm from
        ``reference/01_abm_generate_embedding.py`` lines ~519-720). The
        :class:`Literal` shape admits future strategy names without breaking
        the public contract.
    knn_neighbors
        ``k`` for the kNN graph built in Stage 1. ``None`` ⇒ runtime heuristic
        ``int(sqrt(n_windows))``, matching the reference oracle. Must be
        ``>= 1``.
    leiden_partition
        Which ``leidenalg`` partition class to use for Stage 1. ``"CPM"``
        matches the reference (``leidenalg.CPMVertexPartition``);
        ``"Modularity"`` and ``"RBConfiguration"`` are exposed for
        experimentation.
    leiden_resolution
        Resolution parameter passed to Leiden. Must be ``> 0``. Default
        ``1.0`` matches the reference.
    leiden_seed
        Seed passed to ``leidenalg.find_partition``. Default ``42`` matches
        the reference.
    n_final_clusters
        Number of final TME states to cut the Ward dendrogram into. ``None``
        ⇒ auto-select via ``cluster_count_metric`` over the candidate range.
        **No package default** — either supply an explicit integer (``>= 2``)
        or accept auto-selection. Mirrors ADR 0009's "no silent
        science-shaping default" stance.
    cluster_count_metric
        Metric used to auto-select ``n_final_clusters`` when it is ``None``.
        ``"wss_elbow"`` (default) uses ``kneed`` on the WSS curve;
        ``"calinski_harabasz"`` / ``"silhouette"`` use ``argmax`` of the
        respective sklearn score.
    cluster_count_min
        Inclusive lower bound on the candidate-k range. Must be ``>= 2``
        (a single-cluster cut is degenerate for every metric here).
    cluster_count_max
        Inclusive upper bound on the candidate-k range. ``None`` ⇒ runtime
        heuristic ``min(12, n_leiden_clusters)`` (12 is the biologically
        interpretable cap for TME states; see decision log
        2026-05-14-cluster-count-max-default.md). Must be ``>= 2`` if
        supplied.
    source_variable
        Name of the input Zarr data variable carrying the embedding to be
        clustered. Defaults to ``"embedding"`` (the Phase 4 output) but any
        non-empty name is accepted.
    leiden_labels_variable
        Name of the per-window Leiden community label array in the output
        Zarr. Must be distinct from the other five variable names.
    final_labels_variable
        Name of the per-window final-cluster label array in the output Zarr.
        Must be distinct from the other five variable names.
    cluster_means_variable
        Name of the per-Leiden-cluster mean-embedding array in the output
        Zarr. Must be distinct from the other five variable names.
    linkage_variable
        Name of the Ward linkage-matrix array in the output Zarr. Must be
        distinct from the other five variable names.
    cluster_count_scores_variable
        Name of the per-candidate-k metric-score array in the output Zarr.
        Empty along the candidate dimension when ``n_final_clusters`` was
        user-supplied. Must be distinct from the other five variable names.
    """

    model_config = ConfigDict(extra="forbid")

    strategy: Literal["leiden_ward"] = Field(
        default="leiden_ward",
        description=(
            "Clustering algorithm. Only 'leiden_ward' is implemented in "
            "v0.6.0; the Literal accepts future strategies without a "
            "breaking change."
        ),
    )

    # ----- Stage 1 — Leiden on kNN graph ----------------------------------
    knn_neighbors: int | None = Field(
        default=None,
        ge=1,
        description=(
            "k for the kNN graph. None ⇒ heuristic int(sqrt(n_windows)). The reference uses sqrt-n."
        ),
    )
    leiden_partition: Literal["CPM", "Modularity", "RBConfiguration"] = Field(
        default="CPM",
        description=(
            "leidenalg partition class for Stage 1. 'CPM' matches the "
            "reference (CPMVertexPartition); 'Modularity' and "
            "'RBConfiguration' are exposed for experimentation."
        ),
    )
    leiden_resolution: float = Field(
        default=1.0,
        gt=0.0,
        description=(
            "Resolution parameter passed to leidenalg.find_partition "
            "(>= 0 exclusive). Default 1.0 matches the reference."
        ),
    )
    leiden_seed: int = Field(
        default=42,
        description=("Seed passed to leidenalg.find_partition. Default 42 matches the reference."),
    )

    # ----- Stage 2 — Ward on Leiden cluster means -------------------------
    n_final_clusters: int | None = Field(
        default=None,
        ge=2,
        description=(
            "Number of final TME states to cut the Ward dendrogram into. "
            "None ⇒ auto-select via cluster_count_metric over the candidate "
            "range. No package default; either supply an explicit integer "
            "or accept auto-selection (the metric is named, the number "
            "falls out of the data)."
        ),
    )

    cluster_count_metric: Literal["wss_elbow", "calinski_harabasz", "silhouette"] = Field(
        default="wss_elbow",
        description=(
            "Metric for auto-selection of n_final_clusters. "
            "'wss_elbow' (default): kneed-based elbow of the WSS curve. "
            "'calinski_harabasz' / 'silhouette': argmax of the sklearn "
            "score."
        ),
    )
    cluster_count_min: int = Field(
        default=2,
        ge=2,
        description=("Inclusive lower bound on the candidate-k range for auto-selection."),
    )
    cluster_count_max: int | None = Field(
        default=None,
        ge=2,
        description=(
            "Inclusive upper bound on the candidate-k range. "
            "None ⇒ runtime heuristic min(12, n_leiden_clusters) (12 is "
            "the biologically interpretable cap for TME states)."
        ),
    )

    # ----- Variable naming -----------------------------------------------
    source_variable: str = Field(
        default="embedding",
        min_length=1,
        description=(
            "Name of the input Zarr data variable carrying the embedding. "
            "Defaults to 'embedding' (the Phase 4 output) but any non-empty "
            "name is accepted."
        ),
    )
    leiden_labels_variable: str = Field(
        default="leiden_labels",
        min_length=1,
        description=(
            "Name of the per-window Leiden community label array in the "
            "output Zarr. Must differ from the other five variable names."
        ),
    )
    final_labels_variable: str = Field(
        default="cluster_labels",
        min_length=1,
        description=(
            "Name of the per-window final-cluster label array in the output "
            "Zarr. Must differ from the other five variable names."
        ),
    )
    cluster_means_variable: str = Field(
        default="leiden_cluster_means",
        min_length=1,
        description=(
            "Name of the per-Leiden-cluster mean-embedding array in the "
            "output Zarr. Must differ from the other five variable names."
        ),
    )
    linkage_variable: str = Field(
        default="linkage_matrix",
        min_length=1,
        description=(
            "Name of the Ward linkage-matrix array in the output Zarr. "
            "Must differ from the other five variable names."
        ),
    )
    cluster_count_scores_variable: str = Field(
        default="cluster_count_scores",
        min_length=1,
        description=(
            "Name of the per-candidate-k metric-score array in the output "
            "Zarr. Empty along the candidate dimension when n_final_clusters "
            "was user-supplied. Must differ from the other five variable "
            "names."
        ),
    )

    @model_validator(mode="after")
    def _no_collisions(self) -> ClusterConfig:
        # The six variable names share the output Dataset's data_vars dict.
        # A collision would silently clobber one entry with another on write,
        # so reject any pairwise overlap at config-construction time. Failing
        # fast here is the defence-in-depth complement to the orchestrator's
        # own pre-write check.
        names = [
            self.source_variable,
            self.leiden_labels_variable,
            self.final_labels_variable,
            self.cluster_means_variable,
            self.linkage_variable,
            self.cluster_count_scores_variable,
        ]
        if len(set(names)) != len(names):
            duplicates = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"variable names must all be distinct; duplicates: {duplicates}")
        return self

    @model_validator(mode="after")
    def _count_range_consistent(self) -> ClusterConfig:
        if self.cluster_count_max is not None and self.cluster_count_max < self.cluster_count_min:
            raise ValueError(
                f"cluster_count_max ({self.cluster_count_max}) must be >= "
                f"cluster_count_min ({self.cluster_count_min})"
            )
        return self
