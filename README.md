# playmoleculeai-evals

Evals for the playmoleculeAI agentic system. Browser-driven, multi-LLM,
with deterministic assertions *and* rubric-based LLM-as-judge grading.

Docs live in [`docs/`](docs/):

- [`how-it-works.md`](docs/how-it-works.md) — pipeline tour. Start here.
- [`writing-evals.md`](docs/writing-evals.md) — authoring guide for new cases and eval sets.
- [`spec.md`](docs/spec.md) — code contract: modules, schemas, conventions.
- [`plan.md`](docs/plan.md) — roadmap and architectural reasoning.

## Install

```bash
uv sync
uv run playwright install chromium
cp .env.example .env && $EDITOR .env
uv run pmai-evals setup-auth          # one-time login, saves storage_state.json
```

## Run an eval

Three commands: `run` executes the agent and collects artifacts,
`grade` scores them, `report` renders the result.

```bash
# Dry-run first to validate the matrix.
uv run pmai-evals run --eval-set molecular-visualization --cases load-1crn --dry-run

# Real run (cheap tier), grade, report.
uv run pmai-evals run    --eval-set molecular-visualization --cases load-1crn --tier cheap
uv run pmai-evals grade  <run_id>
uv run pmai-evals report <run_id>
```

`<run_id>` is the directory name under `runs/`, printed at the end of
`run`. Re-grading is free and re-runnable; re-running the agent is not.

## CLI

| Command | Purpose |
|---|---|
| `setup-auth` | Interactive login, saves `playwright/.auth/storage_state.json`. |
| `run`        | Execute the `(case × model × seed)` matrix; write artifacts under `runs/<run_id>/`. |
| `grade`      | Grade an existing run (assertions + LLM judge). Re-runnable with `--force`. |
| `report`     | Render markdown / HTML / JSON summaries from a graded run. |
| `critique`   | "Grade the grader": flag non-discriminating rubric dimensions. |
| `list-models`| Print the model registry. |

Exit codes: `0` success, `1` user error, `2` budget abort, `3`
unrecoverable harness error.

## Adding evals

See [`docs/writing-evals.md`](docs/writing-evals.md). No code changes
needed for a typical new case — it's YAML plus optional fixtures.

## Repo layout

See [`docs/spec.md`](docs/spec.md) §2. Code lives under
`src/pmai_evals/`, eval data under `eval_sets/`, run outputs under
`runs/` (gitignored).
