# Decision: establish a decision-log system

- **Date:** 2026-05-14 (UTC)
- **Status:** Accepted
- **Owner / decider:** Eric

## Context

Through Phases 0-5 the project relied on a mix of artefacts to capture
why-decisions:

- **ADRs** (`docs/adr/`) — load-bearing, long-term, architectural. Ten
  filed so far.
- **Task files** (`tasks/`) — per-phase work tickets with embedded
  decision narrative.
- **STATUS.md / HANDOFF.md** — current state + cold-start orientation.
- **Commit messages** — short rationales tied to a specific diff.

This works for big decisions and big chunks of work, but the small
"why did we pick option X over Y here" decisions get scattered across
commits and lost between phases. At the end of the v0.6.0 session, the
owner asked for a more rigorous, reproducible system:

> All development decisions should be logged. If they were not
> previously, then we must start doing so rigorously now. Don't go back
> and revise. Just set up a system for logging design/development
> decision making and make sure each session is logged in a detailed,
> reproducible, and appropriate manner.

## Options considered

### Option A — One growing `DECISIONS.md` file

- Pros: single file, easy to grep, no directory clutter.
- Cons: rebases poorly when multiple agents touch it in the same
  session; gets long; no per-decision review affordance.

### Option B — Per-decision Markdown files under `docs/development/decisions/`

- Pros: each decision is its own commit-able artefact; reviewable in
  isolation; supports both per-topic and per-session entries; an INDEX
  keeps a chronological table of contents.
- Cons: more files to manage; requires discipline around the index.

### Option C — A tag at the top of every commit message linking to a
"decisions thread"

- Pros: zero new files.
- Cons: decisions get spread across many commits with no single landing
  page; impossible to write a decision *before* the code lands.

## Decision

**Option B.** New directory `docs/development/decisions/` with:

- `README.md` — process: when to write, format, lifecycle.
- `TEMPLATE.md` — copy-paste skeleton.
- `INDEX.md` — chronological table (newest at top).
- `YYYY-MM-DD-<slug>.md` — one file per decision *or* one per session.

## Consequences

- **Process change going forward:** the orchestrator (human or agent)
  writes one session-log entry at the end of every working session, plus
  one per-decision entry whenever a non-obvious choice gets made
  mid-session.
- **No back-fill** — per Eric's instruction, prior phases (0-4) are not
  retroactively logged. The log starts at 2026-05-14 with the v0.6.0
  ship and the v0.6.1 housekeeping bundle.
- **Index discipline:** `INDEX.md` is the single source of "what
  decisions exist in this project". Every new entry must add a row.
- **ADR promotion path documented:** if a decision surfaces an invariant
  that should bind permanently, it gets promoted to an ADR (with
  cross-links in both directions).
- **AGENTS.md / HANDOFF.md** will eventually be updated to point new
  agents at this directory (will happen in the next session that touches
  those files — keeping this change tight).

## References

- Owner directive: 2026-05-14 transcript ("All development decisions
  should be logged. […] Set up a system for logging design/development
  decision making.")
- The new directory: `docs/development/decisions/`
