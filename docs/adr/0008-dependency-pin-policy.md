# 0008 — Dependency pin policy for git-only upstreams

- **Status:** Accepted (revised 2026-05-14: PyPI-target language removed per owner directive — see [decision log](../development/decisions/2026-05-14-no-pypi-plan.md))
- **Date:** 2026-05-13 (revised 2026-05-14)
- **Deciders:** Eric, Claude

## Context

Two of tmelandscape's core dependencies — `tissue_simulator` and `spatialtissuepy` — are installed directly from GitHub (`pip install git+...`) because neither has a PyPI release yet. As of v0.1.x both were pinned to *the default branch*, which means a `uv lock` re-run could silently pull in an upstream change without the version number moving. The post-v0.1.0 audit also surfaced fragility from this: any breaking API change upstream would bypass our test suite until the next CI run.

Both packages are also single-author and pre-release; the working commit is what was tested, not "main yesterday."

## Decision

For every core dep installed from git+URL, we pin to **a tag** (annotated, signed if possible), not to `main`. The `uv.lock` is the deterministic guarantor *inside* a given tag — it pins to a specific commit — but the human-readable surface is the tag, which is the unit of intent.

Workflow:

1. On the upstream repo, the maintainer (currently Eric for both packages) tags a release: `git tag -a v0.x.y -m "..." && git push --tags`.
2. tmelandscape's `pyproject.toml` references the tag: `package @ git+https://github.com/owner/repo.git@v0.x.y`.
3. `uv lock` resolves to whatever commit the tag points to; `uv sync` reproduces deterministically across machines.
4. An ADR-worthy bump (new tag) is captured in tmelandscape's CHANGELOG / commit history.

For dual-published upstreams (a PyPI release exists), prefer PyPI and drop the git+URL entirely. **PyPI publishing for `tissue_simulator` and `spatialtissuepy` is not a project goal** — both packages will remain git+tag pinned indefinitely. If either ships to PyPI in the future, the owner will signal a re-pin; until then no roadmap line item depends on it. See [decision log: no PyPI plan](../development/decisions/2026-05-14-no-pypi-plan.md).

## Action items at the time of writing

- `tissue_simulator` is currently pinned to floating `main`. Maintainer should tag `v0.1.0` at commit `67becc12576d76e56be29ac612f55101df878b62` (the commit `uv` resolved into tmelandscape v0.1.0's lockfile). tmelandscape's pyproject pin will then change to `@v0.1.0`.
- `spatialtissuepy` is currently pinned to commit `c03cfa4`. Maintainer should tag `v0.2.0` at that commit. tmelandscape pin updates to `@v0.2.0`.
- Until tags exist, the commit-pinned form is acceptable as a temporary measure; the policy is "tagged unless impossible right now."

**Status (2026-05-14):** both action items complete. `tissue_simulator` is now pinned at `@v0.1.4`; `spatialtissuepy` is now pinned at `@v0.0.1`.

## Consequences

- Drift risk eliminated: a `uv lock --upgrade` on an unchanged tag does nothing.
- Human-readable provenance: looking at `pyproject.toml` tells you the upstream version, not just a commit hash.
- Slight friction on the upstream side: maintainers have to remember to tag. Mitigation: document the tag-on-release habit in upstream READMEs and / or automate via release-please / a release script.
- The git+tag form is the **long-term plan**, not a transitional one. The ADR does not retire on a hypothetical PyPI migration.

## Alternatives considered

- **Commit-SHA pinning only:** maximum determinism but no human-readable version. Loses release-note context.
- **Floating `main`:** the status quo before this ADR. Trivial, but breaks reproducibility on any `uv lock` re-run that crosses an upstream commit.
- **Git submodule + local `pip install -e`:** works for development but breaks `pip install tmelandscape` for users.
