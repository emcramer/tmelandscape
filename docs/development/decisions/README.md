# Decision log — process

This directory captures **design / development decisions** made during work on
`tmelandscape`, at a finer granularity than the ADRs in `docs/adr/`. ADRs are
for *architectural* decisions — major scope, technology, or invariant choices
that constrain the project for the long term. Decision-log entries are for
the *day-to-day* choices: which library to reach for, what an algorithm
should do when an edge case arises, which of several reasonable
implementations to ship, what was tried and rejected.

The goal is **reproducibility and rigour**, not bureaucracy: a reader (the
owner, a future agent, a code reviewer) should be able to open a decision
entry and understand *what* was decided, *why* that option won over the
alternatives, *what was considered and rejected*, and *what the immediate
follow-ups are*. Decisions that turn out to be wrong should be left in place
and superseded by a new entry — the log is append-only history, not a wiki.

## When to write a decision-log entry

Write one when **any** of these is true:

- A non-obvious algorithmic choice is being made (e.g. "which knee-detection
  algorithm to use", "how to handle degenerate cluster cuts").
- A library / dependency is added, removed, or pinned to a non-obvious
  version.
- A piece of behaviour was considered and explicitly *not* implemented (e.g.
  "we decided not to add a Leiden resolution sweep helper for v0.6.0").
- An invariant or default is changed in a way that affects downstream
  consumers (e.g. "cluster_count_max default narrowed from 20 to 12").
- A multi-agent session ships a non-trivial chunk of work — the session log
  captures wave-by-wave decisions and the rationale for any reviewer findings
  applied or deferred.
- The owner provides a directive that shapes a sub-feature (e.g. "no silent
  default for n_final_clusters").

Don't write one for:

- Routine bug fixes where the fix is unambiguous.
- Mechanical refactors with no behaviour change.
- Things already captured in commit messages or PR descriptions at sufficient
  depth.

When in doubt: prefer to write one. The cost of a brief entry is small; the
cost of a forgotten decision is large.

## Filename convention

`YYYY-MM-DD-<short-kebab-slug>.md`, in this directory. The date is the
session date in UTC. Examples:

- `2026-05-14-cluster-count-max-default.md`
- `2026-05-14-wss-elbow-algorithm-options.md`
- `2026-05-14-phase-5-session.md`

For session logs that span a long working session, the slug is
`phase-<N>-session` (or `vX.Y.Z-session`). For one-off decisions tied to a
single topic, the slug names the topic.

## Entry format

Use the template at [`TEMPLATE.md`](TEMPLATE.md). The required fields:

- **Title** (`# Decision: <one-line summary>`)
- **Date** (UTC)
- **Status** (`Proposed` / `Accepted` / `Superseded by <link>`)
- **Context** — what triggered the decision, what was the state going in.
- **Options considered** — at least two, each with pros/cons. If only one
  option was on the table, say so explicitly.
- **Decision** — which option was picked and why.
- **Consequences** — what changes downstream, what new work this implies,
  what's now harder/easier.
- **References** — ADRs, task files, PRs, prior decision entries, owner
  messages.

Session logs additionally include a **Session log** section: a chronological
list of waves / agents spawned / reviewer findings / fixes applied,
sufficient to reconstruct what happened.

## Relationship to ADRs

If a decision-log entry surfaces an invariant that should bind the project
permanently, **promote it to an ADR**: add a new numbered ADR in
`docs/adr/`, link from the decision-log entry, and link back. The
decision-log entry stays in place as the original context.

## Index

Maintain a chronological index at [`INDEX.md`](INDEX.md). One line per
entry: date, title, status. Newest at top.

## What to do at the END of every working session

The session orchestrator (human or agent) writes **one** session log entry
covering:

- What the session set out to do.
- What it actually shipped (commits, tags, version bumps).
- Decisions made along the way (link to per-decision entries if any were
  written separately).
- Reviewer findings applied vs. deferred.
- Surprises hit and how they were resolved.
- Open follow-ups for the next session.

This is the single most important habit. STATUS.md is the *current state*;
the decision log is the *path that got us there*.
