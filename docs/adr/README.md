# Architecture Decision Records

Numbered, append-only `NNNN-kebab-title.md` files using a lightweight Nygard-style format.

## When to write one

- Any cross-module architectural choice.
- Any scope change (esp. adding/removing items from v1).
- Any change to data formats, on-disk artefact layouts, or public API contracts.
- Any decision a future agent might second-guess without context.

## Template

```markdown
# NNNN — <Short title>

- **Status:** Proposed | Accepted | Superseded by NNNN | Deprecated
- **Date:** YYYY-MM-DD
- **Deciders:** Eric, <agent name>

## Context

What is the problem? What forces are at play?

## Decision

What we decided and why, in one or two paragraphs.

## Consequences

Positive, negative, and neutral consequences. What becomes easier? What becomes harder?

## Alternatives considered

- Option A — why rejected
- Option B — why rejected
```
