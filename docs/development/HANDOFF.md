# HANDOFF — cold-start guide for a new agent joining `tmelandscape`

You are picking up a multi-month research-software project that produces tumour-microenvironment (TME) state landscapes from agent-based-model simulation ensembles. The project owner is Eric Cramer (OHSU). The repo is at <https://github.com/emcramer/tmelandscape>.

The current version is **v0.5.0**, shipped 2026-05-13. Pipeline steps 1, 3, 3.5, and 4 are done. Step 2 is intentionally external. Step 5 (clustering) is the next phase and has a pre-drafted task file at `tasks/06-clustering-implementation.md` in the repo root with frozen API contracts.

## 0. Read these, in this order

1. **This file** — orientation.
2. **[`STATUS.md`](STATUS.md)** — where the project is right now.
3. **`AGENTS.md`** at the repo root — house-style invariants, canonical commands, scope boundaries, do/don't lists.
4. **[`ROADMAP.md`](ROADMAP.md)** — what's shipped vs upcoming.
5. **`tasks/06-clustering-implementation.md`** (repo root, not on the docs site) — the next phase (Phase 5 / clustering), with API contracts already frozen and the buddy-pair stream allocation drafted.
6. **The most recent ADRs** (`docs/adr/000{6,7,8,9}-*.md`) — the binding architectural decisions you should not overturn without explicit owner approval.

## 1. Verify you have the project in a working state

```bash
cd /Users/cramere/landscape-generation
uv sync --all-extras
uv run pytest -q
```

You should see **247 passed, 1 deselected** in ~35 seconds. The deselected test is the opt-in `pytest -m real` real-data integration test, which requires the example PhysiCell sims fetched into `tests/data/example_physicell/`. If your run shows a different count, stop and figure out why before changing anything.

Other verification gates:

```bash
uv run ruff check .            # → All checks passed!
uv run ruff format --check .   # → N files already formatted
uv run mypy src                # → Success: no issues found in 45 source files
uv run mkdocs build --strict   # → exit 0
uv run tmelandscape version    # → 0.5.0
uv run tmelandscape-mcp        # MCP server boots over stdio
```

## 2. Three load-bearing conventions

### 2.1 Three public surfaces, every step

Every pipeline step exposes:

- A Python API: `from tmelandscape.<phase> import <step>_ensemble`.
- A CLI verb: `tmelandscape <step>`.
- An MCP tool: `<step>_ensemble_tool` in `src/tmelandscape/mcp/tools.py`, registered in `src/tmelandscape/mcp/server.py`.

There's also a strategy-discovery surface per step: `tmelandscape <step>-strategies list` plus `list_<step>_strategies` MCP tool. Cataloguing what strategies are available is a first-class concern (see ADR 0009).

When you implement a new step, ship all three surfaces in the same release, with an integration test in `tests/integration/test_<step>_end_to_end.py` that asserts byte-equal output across the three.

### 2.2 Never overwrite raw data, never hardcode user choices

Two binding invariants from the project owner, captured in ADRs 0006 and 0009:

- Pipeline steps **always** write a NEW Zarr at a user-supplied output path. The orchestrator refuses (`FileExistsError`) if the output already exists. Input is opened read-only inside an `xr.open_zarr` context manager. Tests verify byte-equality of the input store before and after every call.
- Data-selection knobs (which statistics to compute, which columns to drop, the window size, the number of final clusters) **must** be required arguments with no package default. Strategy literals can have defaults — `strategy: Literal["sliding_window"] = "sliding_window"` is fine, because the literal is just naming the algorithm — but the user-data choices that affect what they see in their landscape must be explicit.

These invariants drive a lot of the orchestrator code structure (defence-in-depth guards, the `drop_*` lists always defaulting to `[]`, the JSON-roundtrip validators in the configs).

### 2.3 Buddy-pair pattern for non-trivial phases

Phases 3, 3.5, and 4 were each built with this pattern:

- **Wave 1 (parallel)**: spawn three Implementer agents, one per stream (algorithm / Zarr orchestrator / config + alternatives). They run in parallel, each producing a written report listing files created, test counts, deviations from the contract, and surprises hit.
- **Wave 2 (parallel)**: spawn three Reviewer agents, one per stream. **Reviewers may NOT edit code.** They audit their partner's diff read-only and produce a findings report tagged BUG / RISK / SMELL / OK plus a 5-line verdict.
- **Wave 3 (orchestrator)**: you (the next session) apply review findings, integrate the streams (top-level function, CLI verb, MCP tool, integration test, docs), update STATUS/ROADMAP, bump the version, commit, tag, push.

The Phase 5 task file (`tasks/06-clustering-implementation.md`) has the three-stream allocation already drafted. Use it.

#### Useful prompts when spawning agents

Each previous phase's prompt has been preserved in conversation history (Phase 5 will mirror them closely). Key features of a good Implementer prompt:

- Frozen function signatures pasted into the prompt (no ambiguity at handoff).
- Explicit "do not create or touch" list for the files belonging to the other streams.
- Explicit "verify before reporting done" checklist (your tests pass; full suite still green; ruff + format + mypy clean).
- An explicit "report when done" template (files created, deviations, surprises).

Reviewer prompts:

- Explicit "MUST NOT EDIT CODE" guard.
- Audit checklist tied to the spec's bullet points.
- Sandbox commands they can use (`uv run python -c "..."`, `uv run pytest -v`, file readers).
- Severity-tagged findings format.

If you need to nudge a buddy-pair member after their initial report, use `SendMessage` to the agent ID returned in their initial report — they retain context. A `new Agent` call starts a fresh agent with no memory.

## 3. The directory tree at a glance

```
src/tmelandscape/
├── config/          # Pydantic configs per pipeline step
│   ├── sweep.py             # Phase 2
│   ├── summarize.py         # Phase 3
│   ├── normalize.py         # Phase 3.5
│   └── embedding.py         # Phase 4
├── sampling/        # Phase 2 (manifest, LHS, alternatives, tissue_simulator wrapper)
├── summarize/       # Phase 3 (driver, aggregator, registry, schema)
├── normalize/       # Phase 3.5 (within_timestep, alternatives, feature_filter stub)
├── embedding/       # Phase 4 (sliding_window, alternatives, __init__ orchestrator)
├── cluster/         # Phase 5 — TO BE WRITTEN
├── landscape/       # Phase 5+ — Landscape facade (post-clustering)
├── viz/             # Phase 6 — visualisation helpers
├── io/, utils/      # cross-cutting
├── cli/             # Typer verbs (one file per verb)
└── mcp/             # FastMCP server + tools

tests/
├── unit/                    # one test file per module
├── integration/             # one per pipeline step
├── data/synthetic_physicell/  # 3 sims × 3 timepoints × 21 cells fixture
└── real_data/               # opt-in via `pytest -m real`

reference/             # gitignored read-only oracle scripts (Eric's local marimo notebooks)
docs/
├── adr/              # 9 numbered ADRs
├── development/      # STATUS.md, ROADMAP.md, this HANDOFF.md, CONTRIBUTING.md
└── concepts/         # one per pipeline step
tasks/                # per-task markdown work-files
```

## 4. Common gotchas

- **`reference/` is gitignored.** The marimo notebooks (`00_abm_normalization.py`, `01_abm_generate_embedding.py`, `02_abm_state_space_analysis.marimo.py`, `utils.py`) are on Eric's local machine and were copied into `reference/` during Phase 1's audit. They're the oracle for every subsequent phase. When a contract references a "reference oracle," it's pointing into this directory.
- **`tissue_simulator` and `spatialtissuepy` are git-pinned, not PyPI.** ADR 0008 documents the pin policy (tag the upstream before bumping; for now, pin to commit SHAs in `uv.lock`). Eric is handling the upstream tagging separately.
- **The synthetic PhysiCell fixture** under `tests/data/synthetic_physicell/` is regenerated deterministically by `build.py`. It's intentionally tiny (3 sims × 3 timepoints × 21 cells, ~112 KB total) so it can live in git.
- **Zarr v3 unstable string dtype warnings** are filtered in `pyproject.toml.[tool.pytest.ini_options].filterwarnings`. Don't be alarmed if you see them when running the test suite manually outside `uv run pytest`.
- **The CI on GitHub Actions** runs the same `uv sync && uv run pytest` matrix. If your local tests pass and CI fails, the most likely culprit is a Python-version-specific behaviour (CI tests 3.11 and 3.12).
- **MCP tool count** as of v0.5.0: **9 tools**. Don't add an MCP tool without a matching public Python function AND a matching CLI verb (the "three surfaces" invariant from §2.1).

## 5. When you finish a session

Update `STATUS.md` with:

- What you shipped in this session.
- Whether the test suite is still green and the version that's tagged.
- Any open questions you couldn't resolve, with enough context that the next agent can ask Eric directly.
- A "next agent's first actions" list (1-5 bullet points).

If you wrote a non-trivial decision document or design choice, capture it as a new ADR in `docs/adr/`. Numbered, append-only.

If you started a task that didn't finish, leave a per-task work file in `tasks/<slug>.md` so the next session can pick up cold.

## 6. Who to ask

Eric (the project owner, [ericscrum@gmail.com](mailto:ericscrum@gmail.com)) is the source of truth on:

- Whether a feature is in scope.
- Whether a default is a "good default" or a "silent constraint on his science."
- Anything touching the reference oracle's algorithm — he wrote those notebooks.

When in doubt: leave a clear open question in STATUS.md and ask him before making a scope-affecting decision. The project has explicit ADRs for cases where defaults were rolled back because they constrained downstream choices (ADR 0009 in particular).

---

Welcome aboard.
