# playmoleculeai-evals

Evals for the playmoleculeAI agentic system. Browser-driven, multi-LLM, with
both programmatic assertions and rubric-based LLM-as-judge grading.

The roadmap and architectural reasoning live in [`docs/plan.md`](docs/plan.md).
The code contract (modules, interfaces, schemas, conventions) lives in
[`docs/spec.md`](docs/spec.md). Read those first.

## Quickstart

```bash
# 1. install
uv sync
uv run playwright install chromium

# 2. configure
cp .env.example .env
$EDITOR .env

# 3. one-time login (saves storage_state.json)
uv run pmai-evals setup-auth

# 4. dry run a cheap eval to validate the set
uv run pmai-evals run --eval-set molecular-visualization --tier cheap --dry-run

# 5. real run + grade + report
uv run pmai-evals run    --eval-set molecular-visualization --tier flagship
uv run pmai-evals grade  <run_id>
uv run pmai-evals report <run_id>
```

## CLI

| Command | Purpose |
|---|---|
| `setup-auth`            | Interactive login, saves `playwright/.auth/storage_state.json`. |
| `run`                   | Execute the (case × model × seed) matrix and write artifacts under `runs/<run_id>/`. |
| `grade`                 | Grade an existing run (assertions + LLM judge). Re-runnable. |
| `report`                | Render markdown / HTML / JSON summaries from a graded run. |
| `critique`              | "Grade the grader": flag non-discriminating or buggy assertions. |

Exit codes:

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | user error (bad args, missing eval set, ...) |
| `2` | budget abort |
| `3` | unrecoverable harness error |

## Repository layout

See [`docs/spec.md`](docs/spec.md) §2.

## Adding a new eval

See [`docs/spec.md`](docs/spec.md) §9 — nine steps, no harness code changes
required for a typical new eval.
