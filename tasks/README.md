# tasks/

Per-task work-files for any unit of work spanning more than one agent session. Survives context-window limits between agents.

## When to create one

- Any feature, bug, or refactor that won't finish in a single session.
- Any task that requires consensus between sessions on a non-trivial approach.

## When NOT to create one

- Trivial edits (typos, single-line bug fixes).
- Tasks fully captured by a ticket / issue (link from `STATUS.md` instead).

## Template

```markdown
# <task title>

- **slug:** <short-kebab-case>
- **status:** in-progress | blocked | done
- **owner:** <agent name / Eric>
- **opened:** YYYY-MM-DD
- **roadmap link:** <phase / milestone>

## Context

2–4 sentences. Why is this task happening, and what does success look like?

## Plan

- [ ] step 1
- [ ] step 2
- [ ] step 3

## Decisions

- <bullet, with [[adr-NNNN-slug]] link if applicable>

## Follow-ups

- <future work spun out of this task>

## Session log

- YYYY-MM-DD (Agent X): <what was done, what's next>
```

## Lifecycle

When a task hits `done`, leave the file in place (do not delete) and update `STATUS.md` to remove it from the active list. The history is the value.
