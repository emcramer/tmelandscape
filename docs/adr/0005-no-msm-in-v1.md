# 0005 — v1 scope ends at clustering; no MSM/MDP/projection

- **Status:** Accepted
- **Date:** 2026-05-12
- **Deciders:** Eric, Claude

## Context

The LCSS paper (`docs/literature/lcss.pdf`) extends the pipeline beyond clustering into:

- Markov state model (MSM) construction over the discovered TME states.
- Drug-conditioned transition matrices.
- MDP / finite-horizon intervention design.

The full manuscript additionally describes **landscape projection** — mapping new spatial-statistic observations (clinical MTI ROIs) onto a fitted landscape and assigning state labels. Both are described prominently in the papers but require additional design work and data-formatting that fall outside the core landscape-generation pipeline.

## Decision

`tmelandscape` v1 implements only **steps 1, 3, 4, and 5** of the five-step pipeline (sampling → external simulation → summarisation → embedding → clustering). The MSM/MDP analysis and landscape projection are explicitly **out of scope for v1** and tracked as future modules in `docs/development/ROADMAP.md` ("Beyond v1.0").

## Consequences

- Smaller, faster v1 with clear deliverable: a fitted `Landscape` bundle.
- The `Landscape` facade is designed with a future `.project()` method in mind (the bundle stores embedding parameters + cluster centroids + linkage) so the projection module can be added without breaking the v1 API.
- Users wanting MSM analysis today can run scipy / pyemma directly on the labels emitted by v1.

## Alternatives considered

- Include MSM in v1: would push v1 by ~one phase and expand the test surface significantly; deferred.
- Include projection in v1: rejected per Eric — the input-data harmonisation required to make this robust (cell-type label mapping, ROI sampling strategy, scale-correction) is a project of its own.
