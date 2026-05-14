# Decision: drop all PyPI publishing plans — `tmelandscape` ships via git only

- **Date:** 2026-05-14 (UTC)
- **Status:** Accepted (extends [`2026-05-14-no-pypi-plan.md`](./2026-05-14-no-pypi-plan.md))
- **Owner / decider:** Eric

## Context

[An earlier decision](./2026-05-14-no-pypi-plan.md) removed the
"PyPI before v1.0" target for the *upstream* dependencies
(`tissue_simulator`, `spatialtissuepy`). ADR 0008 was amended.

Eric's clarification on 2026-05-14 (third bullet of the third
clarifications message) extends the policy to **`tmelandscape` itself**:

> Ignore any PyPi releases. We are not focused on that. When the
> package is done, I may upload the first completed version that I
> am satisfied with or that gets included in a publication to
> Zenodo, but that will be my choice and I will let you know when
> I choose to do that. For now, keep docs up to date and tracked
> with git.

Until 2026-05-14, the project's ROADMAP listed Phase 7 (release
hardening, v1.0.0) line item `[ ] PyPI release via trusted publisher`.
That item is now retired.

## Options considered

### Option A — Leave the ROADMAP Phase 7 line item, mark it "deferred"

- Pros: zero churn; the line stays as a hypothetical future option.
- Cons: misleading — agents reading the ROADMAP would prioritise
  setting up trusted publishing infrastructure that Eric has
  explicitly de-prioritised.

### Option B — Remove the PyPI line from Phase 7 entirely

- Pros: ROADMAP matches Eric's actual position; no agent picks up
  publishing as a "next-up" item; the line can be re-added if Eric
  later changes course.
- Cons: information loss if Eric *does* change course later (but the
  decision-log entries here are the durable record).

## Decision

**Option B.** ROADMAP Phase 7's PyPI line is removed. The Zenodo line
stays: Zenodo deposit is the explicit publication path Eric named, but
the timing is at his discretion ("I may upload the first completed
version that I am satisfied with") — so the ROADMAP line for Zenodo is
softened to "Eric uploads first satisfactory version to Zenodo when
ready" rather than a phase-completion gate.

## Consequences

- **`docs/development/ROADMAP.md`** Phase 7 — drop the
  `[ ] PyPI release via trusted publisher` line; soften the Zenodo line.
- **STATUS Open Questions** — drop the v0.7.0-era Phase-7-scope
  confirmation question; the v0.7.x focus is now reviewer follow-ups +
  any new feature directives, not release-publishing infrastructure.
- **Docs in git** — Eric's explicit ask: "keep docs up to date and
  tracked with git". This is the standing practice; no change. The
  `mkdocs` build is the canonical doc-site source; deployment to
  GitHub Pages is independent and not retired by this decision (it can
  serve docs from `git` without involving PyPI).
- **Reversibility:** trivial. If Eric later decides to publish, the
  PyPI infrastructure work can be added as a v1.x phase.

## References

- Owner directive: 2026-05-14 transcript (third clarification).
- [Earlier no-PyPI decision (upstreams)](./2026-05-14-no-pypi-plan.md)
- [ADR 0008 — Dependency pin policy](../../adr/0008-dependency-pin-policy.md)
- [ROADMAP Phase 7](../ROADMAP.md)
