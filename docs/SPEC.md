# playmoleculeai-evals — Spec

## 1. Glossary

- **Eval set** — a directory of declarative YAML, fixtures, and optional
  Python checks describing a related family of evaluations. Identified by
  a kebab-case `id` (e.g. `molecular-visualization`).
- **Case** — one prompt with assertions and optional rubric. Identified by
  a kebab-case `id` unique within an eval set.
- **Cell** — one (case, model, seed) triple. The atomic unit of work and
  the atomic unit of artifact storage.
- **Run** — one CLI invocation of `run`. Produces one immutable run
  directory containing all cells. Identified by a `run_id` of the form
  `YYYYMMDD-HHMMSS_<eval_set_id>_<label>` in UTC.
- **Artifact** — a file produced by the harness for a cell or a run.
  Artifacts are addressable by stable relative paths ([5](#5-artifact-layout)).
- **Rollout** — the act of executing one cell against the agent (one
  fresh chat, one prompt, one completion).
- **Grade** — the verdict on a cell: a list of assertion results plus an
  optional rubric grade, persisted as `grade.json`.

## 2. Scope

In scope:

- Producing reproducible, machine-readable evaluations of the
  playmoleculeAI agent across multiple LLM providers.
- Driving a real browser session against a configurable frontend URL.
- Programmatic assertions over the trace and viewer state.
- LLM-as-judge grading with vision when supported.
- Cost ceiling enforcement.
- Markdown / HTML / JSON reporting.

Out of scope (explicitly):

- Throughput or concurrency benchmarking of the agent server.
- Unit testing of individual skills or agent server endpoints.
- Modifying the agent server, the frontend, or the trace store.

## 3. Inputs

### 3.1 Eval set

An eval set is a directory under a top-level `eval_sets/` location:

```
eval_sets/<id>/
├── eval_set.yaml          required
├── cases.yaml             required
├── fixtures/              optional, required if any case references fixtures
│   └── ...
├── checks.py              optional, required if any case uses python_check
├── rubric.md              optional, human-readable rubric
└── rubric.yaml            optional, machine-readable rubric (see [3.5](#35-rubric))
```

The eval set id in `eval_set.yaml` must equal the directory name.

### 3.2 `eval_set.yaml`

```yaml
id: <kebab-case>                # required, must match the directory name
skill_under_test: <string>      # required, free-form tag
description: <string>           # optional
difficulty: <string>            # optional, free-form (e.g. "mixed")
requires_browser: true          # optional, default true
default_timeout_s: 300          # optional, default 300
default_expected_cost_usd: 0.05 # optional, default 0.05
rubric_path: rubric.md          # optional; relative to the eval set dir
tags: [a, b, c]                 # optional
```

Unknown keys are an error at load time.

### 3.3 `cases.yaml`

```yaml
cases:
  - id: <kebab-case>            # required, unique within the eval set
    prompt: <string>            # required, the user prompt
    difficulty: trivial|easy|medium|hard   # optional, default "easy"
    tags: [a, b]                # optional
    timeout_s: <int>            # optional, defaults to eval_set.default_timeout_s
    expected_cost_usd: <float>  # optional, advisory
    preload:                    # optional, see [3.4](#34-preload)
      project:
        files: [<fixture_name>]
      viewer:
        pdb_ids: [<pdb_id>]
        files: [<fixture_name>]
    assertions:                 # optional list, see [7](#7-assertion-catalog)
      - type: <assertion_type>
        ...type-specific config
    rubric:                     # optional
      enabled: <bool>           # default true
      dimensions:               # optional override of the eval-set rubric
        - name: <string>
          question: <string>
          scale: [<int>, <int>] # default [1, 5]
```

Unknown keys are an error at load time. Unknown assertion types are an
error at load time. `python_check` references whose `function` is missing
from `checks.py` are an error at load time. Fixtures referenced by
`preload.project.files` or `preload.viewer.files` that do not exist on
disk are an error at load time.

### 3.4 Preload

Preload state is materialized in the browser before the prompt is sent:

- `preload.project.files` — fixture filenames that must be uploaded into
  the user's project workspace and made visible to the agent.
- `preload.viewer.pdb_ids` — RCSB PDB identifiers that must be loaded
  into the viewer.
- `preload.viewer.files` — fixture filenames that must be loaded directly
  into the viewer (not persisted to the project).

Preload paths are resolved relative to `eval_sets/<id>/fixtures/`.

### 3.5 Rubric

A rubric is a list of named dimensions with questions and a numeric
scale. The judge scores every dimension, and the case passes the rubric
when the mean score is at or above `pass_threshold`.

The rubric source of truth for the judge is YAML; the `rubric_path` field
in `eval_set.yaml` may point to either a `.yaml`/`.yml` file or a `.md`
file with a sibling `.yaml` of the same stem.

```yaml
dimensions:
  - name: <string>
    question: <string>
    scale: [<int>, <int>]   # default [1, 5]
pass_threshold: 3.5         # default 3.5
```

A case may override the dimensions in its `rubric.dimensions` block.
Disabling a case's rubric (`rubric.enabled: false`) skips the judge
entirely for that case.

### 3.6 `checks.py`

Optional. When present, it must expose top-level functions of signature

```
(artifact, config) -> AssertionResult
```

referenced by `python_check` assertions in `cases.yaml`. Functions are
imported once per eval set load. Each function must return an
`AssertionResult` ([7.1](#71-assertion-contract)) whose `evidence` field is non-empty.

### 3.7 Run configuration (CLI)

```
pmai-evals run --eval-set <id> [options]

  --models <id,id,...>        Comma-separated model ids (overrides --tier)
  --tier flagship|cheap|all   Defaults to flagship
  --seeds <N>                 Default 1
  --max-cost <USD>            Default $PMAI_EVALS_MAX_COST_USD
  --headless / --no-headless  Default headless
  --case <id>                 Run only this case (repeatable)
  --label <str>               Suffix for run_id, default "iter"
  --judge-model <id>          Default $PMAI_EVALS_JUDGE_MODEL
  --dry-run                   Print the planned matrix and exit
```

`--models` and `--tier` are mutually informative: `--models` overrides
`--tier`. `--case` filters the matrix; an unknown case id is a user error.

### 3.8 Environment

The harness reads the following environment variables (and their `.env`
equivalents):

| Variable | Purpose |
|---|---|
| `PM_FRONTEND_URL` | Base URL of the playmoleculeAI frontend |
| `PM_BACKEND_URL` | Base URL of the backend API |
| `PM_AGENT_URL` | Base URL of the agent server |
| `PM_EMAIL`, `PM_PASSWORD` | Credentials, used only by `setup-auth` |
| `PM_USER_BUCKET` | Bucket path for project file uploads |
| `PM_PROJECT` | Project name to use for evaluations |
| `PMAI_EVALS_JUDGE_MODEL` | Default judge model |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` | Provider keys |
| `PMAI_EVALS_MAX_COST_USD` | Default budget ceiling |
| `PMAI_EVALS_RESULTS_DIR` | Where run directories are written |
| `PMAI_EVALS_HEADLESS` | Default browser headlessness |
| `PMAI_EVALS_LOG_LEVEL` | Logging verbosity |
| `PMAI_EVALS_AUTH_STATE` | Path of the saved browser storage state |

CLI flags override environment values. Environment values override
defaults baked into the harness.

## 4. Browser session contract

Every cell runs against a real browser session connected to the
configured frontend URL. The browser is not optional and is not
substitutable with a direct API call: pmview tool calls dispatched by
the agent flow over WebSocket to a connected browser, and an absent
browser turns those calls into failures.

Observable requirements per cell:

- A fresh chat is created. No chat is reused across cells.
- Preload ([3.4](#34-preload)) is materialized before the prompt is sent. Project
  uploads happen first, then viewer loads.
- The case prompt is submitted exactly once.
- The harness blocks until the chat reaches a terminal state, defined as
  the agent finishing its rollout (regenerate affordance available) or
  the case timeout elapsing.
- The model used for the rollout is verified against the requested
  model. Sending the wrong model is a cell failure, not a silent
  mismatch.

The browser session is authenticated via a one-shot `setup-auth`
subcommand whose output is a stored login state. Subsequent runs reuse
that login state until it is invalid; an invalid state is a user error
and prompts the user to re-run `setup-auth`.

## 5. Artifact layout

A run directory has this exact shape:

```
<results_dir>/<run_id>/
├── run.json                  per-run input snapshot ([6.1](#61-runjson))
├── manifest.json             planned cells ([6.2](#62-manifestjson))
├── cost.json                 cost journal ([6.3](#63-costjson))
├── summary.json              per-run output summary ([6.4](#64-summaryjson))
├── benchmark.json            written by `report` / aggregation ([9.1](#91-benchmarkjson))
├── critique.json             written by `critique` ([9.2](#92-critiquejson))
└── <case_id>/<model>/seed-<N>/
    ├── trace.json            agent trace ([6.5](#65-tracejson))
    ├── final_answer.md       last assistant message (UTF-8)
    ├── viewer_state.json     pmview systems_tree at completion
    ├── screenshot.png        molstar viewport image (PNG)
    ├── metrics.json          token usage, timings, cost ([6.6](#66-metricsjson))
    ├── status                one of: completed | failed | timed_out
    │                          | skipped_over_budget (plain text + newline)
    ├── error.txt             present iff status ∈ {failed, timed_out};
    │                          one or more lines of error context
    ├── systems/              optional; pmview structure export tree
    └── grade.json            present iff the cell has been graded ([6.7](#67-gradejson))
```

Rules:

- All JSON files are UTF-8, indented two spaces, with sorted keys and a
  trailing newline.
- The cell directory is write-once during a run: the runner creates each
  file at most once. Re-runs go to a fresh `run_id`.
- `grade.json` is the only file the grade stage writes. The grade stage
  may overwrite an existing `grade.json` only when invoked with
  `--force`.
- `screenshot.png` is required when the cell completes; on failure it is
  best-effort and may be absent.
- `systems/` is optional. When present it contains the pmview viewer
  export (one or more structure files) and is the source for assertions
  that need 3D coordinates.

## 6. Output schemas

Schemas are described as JSON shapes. Implementations may use any
serialization layer that produces these shapes.

### 6.1 `run.json`

```json
{
  "run_id": "<run_id>",
  "eval_set": "<eval_set_id>",
  "started_at": "<ISO 8601 UTC>",
  "finished_at": "<ISO 8601 UTC|null>",
  "git_sha": "<string|null>",
  "config": {
    "eval_set_id": "<eval_set_id>",
    "models": ["<model_id>", "..."],
    "seeds": "<int>",
    "max_cost_usd": "<float>",
    "headless": "<bool>",
    "tier": "flagship|cheap|all|null",
    "case_filter": ["<case_id>", "..."],
    "run_label": "<string>",
    "judge_model": "<model_id>"
  },
  "environment": {
    "pm_frontend_url": "<string>",
    "pm_agent_url": "<string>"
  }
}
```

`finished_at` is `null` until the run completes (whether normally or via
budget abort). `started_at` is the canonical run wall clock; downstream
artifacts use that single value rather than re-reading the clock.

### 6.2 `manifest.json`

```json
{
  "entries": [
    {"case_id": "<case_id>", "model": "<model_id>", "seed": 0}
  ]
}
```

The manifest is the planned matrix. Iteration order is model-major,
case-minor, seed-innermost. Filtering by `--case` restricts the case
axis. The number of entries equals `len(models) × len(cases) × seeds`
after filtering.

### 6.3 `cost.json`

```json
{
  "max_cost_usd": "<float>",
  "total_cost_usd": "<float>",
  "charges": [
    {
      "case_id": "<case_id>",
      "model": "<model_id>",
      "seed": "<int>",
      "input_tokens": "<int>",
      "output_tokens": "<int>",
      "cached_tokens": "<int>",
      "cost_usd": "<float>"
    }
  ]
}
```

`cost.json` is written incrementally: after each completed rollout,
`charges` gains one entry and `total_cost_usd` advances. The file is
the source of truth for budget enforcement; it may be re-read between
rollouts.

### 6.4 `summary.json`

```json
{
  "run_id": "<run_id>",
  "eval_set": "<eval_set_id>",
  "started_at": "<ISO 8601 UTC>",
  "finished_at": "<ISO 8601 UTC>",
  "total_cost_usd": "<float>",
  "aborted_over_budget": "<bool>",
  "cases": [
    {
      "case_id": "<case_id>",
      "model": "<model_id>",
      "seed": "<int>",
      "status": "completed|failed|timed_out|skipped_over_budget",
      "cost_usd": "<float>",
      "artifact_dir": "<case_id>/<model>/seed-<N>",
      "error": "<string|null>"
    }
  ]
}
```

Every planned cell appears exactly once in `cases`. Cells skipped due to
budget exhaustion have `status: skipped_over_budget`, `cost_usd: 0`, and
no per-cell artifacts beyond what (if anything) was written before
skipping.

### 6.5 `trace.json`

A `trace.json` captures the conversation produced by the rollout.

```json
{
  "chat_id": "<string>",
  "model": "<model_id|null>",
  "messages": [
    {
      "message_id": "<int>",
      "response_id": "<string>",
      "item_index": "<int>",
      "role": "user|assistant|tool|<other>",
      "type": "<string>",
      "text": "<string|null>",
      "payload": {},
      "model": "<string|null>",
      "created_at": "<string|null>",
      "status": "<string|null>"
    }
  ],
  "tool_calls": [
    {
      "call_id": "<string>",
      "name": "<string>",
      "arguments": {},
      "output": "<string|null>",
      "error": "<string|null>",
      "latency_ms": "<int|null>",
      "turn_index": "<int>",
      "is_error": "<bool>"
    }
  ],
  "usage": {
    "input_tokens": "<int>",
    "output_tokens": "<int>",
    "cached_tokens": "<int>",
    "reasoning_tokens": "<int>"
  },
  "metrics": {
    "ttft_ms": "<int|null>",
    "total_ms": "<int>",
    "tool_latency_ms": "<int>"
  },
  "final_answer": "<string>",
  "status": "completed|failed|timed_out|unknown"
}
```

`tool_calls` is flat and chronological. `final_answer` is the last
assistant text turn. `status` reflects what the harness observed at
capture time:

- `completed` — the agent reached a terminal state with no tool errors.
- `failed` — at least one tool call returned `is_error: true`.
- `timed_out` — the case timeout elapsed before completion.
- `unknown` — the trace could not be classified.

When the trace source does not expose token usage or per-turn latency,
those fields default to zero. Implementations must document which fields
are available; downstream consumers must tolerate zeros.

### 6.6 `metrics.json`

```json
{
  "input_tokens": "<int>",
  "output_tokens": "<int>",
  "cached_tokens": "<int>",
  "reasoning_tokens": "<int>",
  "ttft_ms": "<int|null>",
  "total_ms": "<int>",
  "tool_latency_ms": "<int>",
  "cost_usd": "<float>",
  "trace_status": "completed|failed|timed_out|unknown"
}
```

`cost_usd` is computed from the token counts and the model registry
([3.8](#38-environment)). Unknown model ids charge zero; this must be flagged at the call
site, never silently absorbed.

### 6.7 `grade.json`

```json
{
  "case_id": "<case_id>",
  "model": "<model_id>",
  "seed": "<int>",
  "assertions": [
    {
      "assertion_type": "<string>",
      "passed": "<bool>",
      "evidence": "<string>",
      "config": {}
    }
  ],
  "rubric": {
    "overall_score": "<float>",
    "passed": "<bool>",
    "dimensions": [
      {
        "name": "<string>",
        "score": "<float>",
        "justification": "<string>",
        "evidence": "<string>"
      }
    ],
    "evidence": ["<string>"]
  },
  "summary": {
    "assertions_passed": "<int>",
    "assertions_total": "<int>",
    "rubric_passed": "<bool|null>"
  },
  "judge_model": "<model_id|null>",
  "judge_error": "<string|null>"
}
```

`rubric` is `null` when the case opts out (`rubric.enabled: false`) or
when the judge errored (`judge_error` is set). `summary.rubric_passed`
mirrors `rubric.passed` when present, and is `null` otherwise.

## 7. Assertion catalog

### 7.1 Assertion contract

An assertion is a pure function of the cell's artifacts and a config:

- It must not perform network I/O.
- It must not write to disk.
- It must not invoke an LLM.
- It must produce an `AssertionResult` with a non-empty `evidence`
  string regardless of pass/fail. On pass, evidence cites the source of
  the pass (e.g., a turn index, an offset, a value). On fail, evidence
  describes what was expected versus observed.
- It must be discriminating: an assertion that passes for any output is
  malformed.

### 7.2 Catalog

There is exactly one assertion type. Eval-set–specific predicates live
in the eval set's `checks.py` and are referenced through `python_check`.

#### `python_check`

| key | required | default | meaning |
|---|---|---|---|
| `function` | yes | — | name of a function in the eval set's `checks.py` |
| `kwargs` | no | `{}` | passed through to the function as part of its config |

The function receives the cell artifact and the merged config (kwargs
plus `function`) and must return an `AssertionResult`. A function that
raises is reported as a fail with the exception class and message in
`evidence`. A function that returns a non-`AssertionResult` value
surfaces as an error at grade time.

## 8. Judge contract

### 8.1 Inputs

The judge consumes:

- The cell's `final_answer`, a brief of `tool_calls`, the trace status,
  and the case prompt.
- For absolute mode and when the judge model supports vision: the cell's
  `screenshot.png` as a vision input.
- The rubric (eval-set default or per-case override).

### 8.2 Modes

- **Absolute**: scores one cell against every rubric dimension.
- **Pairwise**: ranks two cells (`A` and `B`). Identifying tokens (model
  family names, chat ids) must be stripped from both transcripts before
  the prompt is composed; only the labels `A` and `B` may distinguish
  the two artifacts.

### 8.3 Output

The judge must produce structured output. In absolute mode:

```json
{
  "overall_score": "<float>",
  "passed": "<bool>",
  "dimensions": [
    {
      "name": "<dimension_name>",
      "score": "<float>",
      "justification": "<string>",
      "evidence": "<string>"
    }
  ],
  "evidence": ["<string>"]
}
```

`overall_score` is the mean of dimension scores when dimensions are
present. `passed` is `true` iff `overall_score >= rubric.pass_threshold`,
unless the judge response explicitly overrides it.

In pairwise mode:

```json
{
  "winner": "A|B|tie",
  "justification": "<string>",
  "evidence": ["<string>"]
}
```

### 8.4 Failure

A judge call that fails (network error, non-parseable output, missing
API key) does not abort the grade stage. It produces a `grade.json` with
`rubric: null` and a non-null `judge_error` describing the failure.
Other cells in the same grade pass continue to be graded.

## 9. Reporting

### 9.1 `benchmark.json`

Aggregation reads `summary.json` and every `grade.json` under the run
and writes:

```json
{
  "run_id": "<run_id>",
  "eval_set": "<eval_set_id>",
  "total_cost_usd": "<float>",
  "aborted_over_budget": "<bool>",
  "models": [
    {
      "model": "<model_id>",
      "cases_total": "<int>",
      "cases_completed": "<int>",
      "cases_failed": "<int>",
      "cases_timed_out": "<int>",
      "cases_skipped": "<int>",
      "assertions_passed": "<int>",
      "assertions_total": "<int>",
      "assertion_pass_rate": "<float>",
      "rubric_pass": "<int>",
      "rubric_total": "<int>",
      "rubric_pass_rate": "<float>",
      "rubric_mean": "<float|null>",
      "rubric_stderr": "<float|null>",
      "cost_usd": "<float>"
    }
  ],
  "cases": {
    "<case_id>": {
      "models": {
        "<model_id>": {
          "assertions_passed": "<int>",
          "assertions_total": "<int>",
          "rubric_passed": "<bool|null>"
        }
      },
      "rubric": {
        "<model_id>": "<float>"
      }
    }
  }
}
```

`rubric_stderr` is the standard error of the mean rubric score across
graded cells for that model; it is `null` when fewer than two scores
exist.

### 9.2 `critique.json`

The critique pass surveys grades and flags non-discriminating
assertions and rubric dimensions:

```json
{
  "non_discriminating": [
    {
      "assertion_or_dimension": "<case_id>::<label>",
      "reason": "<string>",
      "suggestion": "<string>"
    }
  ],
  "summary": "<string>"
}
```

A finding is emitted when, across at least two distinct models for the
same case:

- An assertion passes for every model (over-permissive), or
- An assertion fails for every model (under-specified or buggy), or
- A rubric dimension scores ≥ 4.5 for every model (ceiling), or
- A rubric dimension scores ≤ 1.5 for every model (floor).

### 9.3 `report` outputs

The `report` subcommand renders one of three formats from
`benchmark.json`:

- `markdown` — for terminal/PR-comment use.
- `html` — self-contained, suitable for opening in a browser.
- `json` — `benchmark.json` re-emitted, optionally to a file.

The chosen format is the only difference between invocations; the
underlying numbers are identical.

## 10. Cross-cutting invariants

### 10.1 Run/grade decoupling

Grading is a pure function of artifacts on disk. Re-running `grade` on
the same artifacts with the same judge model and rubric produces the
same `grade.json` (modulo non-determinism in the judge model). Changing
the judge model or rubric and re-grading must not require re-running
the agent.

### 10.2 Per-cell isolation

Every cell runs in a fresh chat. Cross-cell state via the agent is not
permitted. A failure in one cell, including an unhandled exception, is
recorded as `status: failed` in that cell and does not affect any other
cell.

### 10.3 Write-once artifacts

A run directory is immutable from the runner's perspective once written.
The runner does not overwrite a cell's artifacts within a single run.
The grade stage writes only `grade.json` and only overwrites it when
invoked with `--force`.

### 10.4 Cost ceiling enforcement

Before each rollout, the harness checks `total_cost_usd` against
`max_cost_usd`. When the ceiling is reached or exceeded, every remaining
cell is recorded as `skipped_over_budget`, the run summary is written,
and the harness exits with code `2`. After-the-fact charges that exceed
the ceiling do not retroactively fail completed cells.

### 10.5 Declarative eval addition

Adding a new eval set requires only:

1. Creating `eval_sets/<id>/` with `eval_set.yaml` and `cases.yaml`.
2. Optionally adding fixtures, a `checks.py`, and a rubric.

No code outside `eval_sets/<id>/` changes when an eval set is added.

### 10.6 Determinism

`run.json.started_at` is captured once and reused everywhere downstream
that needs the run's wall clock. Graders are deterministic functions of
artifacts and config; they do not consult the system clock or random
sources beyond what is fixed in the cell's `seed`.

### 10.7 Secrets

Secrets, including provider keys, login credentials, and saved login
state, must not appear in any artifact under `<results_dir>/`, in logs,
or in serialized configs.

## 11. CLI surface

```
pmai-evals setup-auth
pmai-evals run         --eval-set <id> [options]
pmai-evals grade       <run_id> [--judge-model <id>] [--force] [--rubric <path>]
pmai-evals report      <run_id> [--format markdown|html|json] [--out <path>]
pmai-evals critique    <run_id>
pmai-evals list-models
```

Exit codes:

| Code | Meaning |
|---|---|
| `0` | success |
| `1` | user error (bad args, missing eval set, unknown case id, etc.) |
| `2` | budget abort |
| `3` | unrecoverable harness error |

## 12. Authoring evals

This section is normative: it describes how an eval set is composed and
how a single case's grading is wired up.

### 12.1 Workflow

1. Create `eval_sets/<id>/` with `eval_set.yaml` and `cases.yaml`
   ([3.1](#31-eval-set)–[3.3](#33-casesyaml)).
2. Drop fixtures into `eval_sets/<id>/fixtures/` if any case references
   them.
3. Add `checks.py` if any case has a `python_check` assertion.
4. Add `rubric.md` / `rubric.yaml` if any case opts into the judge.
5. Add tests for `checks.py` next to it (e.g. `test_checks.py`); they
   are auto-discovered.
6. Add a derivation script under `development/` for any computed
   ground truth referenced from `checks.py` ([12.5](#125-reproducible-ground-truth)).
7. Validate with `pmai-evals run --eval-set <id> --dry-run`, then run,
   grade, and report.

### 12.2 Where check code lives

The harness ships exactly one assertion type, `python_check` ([7.2](#72-catalog)). All
eval-set-specific verification logic lives in `checks.py` inside the
eval-set directory. A case wires a check by name in `cases.yaml`:

```yaml
assertions:
  - type: python_check
    function: <name_of_a_function_in_checks_py>
```

`checks.py` is imported once at eval-set load. Every name listed under
`python_check.function` must resolve to a top-level function in that
module; missing references are an error at load time. There is no global
registry, no decorator, and no plugin discovery: the function only has
to be defined in `checks.py`.

### 12.3 Designing a case

A case has a single declared acceptance criterion. The criterion is what
the check verifies, and writing it down precisely is what makes the case
gradable.

- Define the criterion before writing the check, in concrete structural
  terms (objects produced, values reported, files written, tool calls
  made).
- When grading by exact match, the prompt must pin the answer to a
  single objectively-computable result. A vague prompt graded by a
  strict check fails on phrasing rather than capability.
- When the prompt admits more than one biologically or operationally
  equivalent answer, enumerate every valid answer and pass on the first
  match.
- Use the rubric for graded judgement, the `python_check` for
  verifiable facts. The two are complementary.

### 12.4 Writing the check

Each check is a top-level function with the contract
`(artifact, config) -> AssertionResult` ([3.6](#36-checkspy), [7.1](#71-assertion-contract)).

- The check is a pure function of the cell's artifacts. It reads them
  through the `RunArtifact` API (`viewer_state()`, `load_system(name)`,
  trace, screenshots) and returns a verdict.
- The check verifies the **meaning** of the agent's output, not the
  surface text the agent produced. Any agent-authored string (selection
  expression, file path, search query) is resolved against the
  corresponding structured artifact before comparison.
- Expected answers and thresholds are baked into the function.
  `kwargs` in `cases.yaml` are reserved for checks genuinely shared
  across parameterisations; one-off checks expose no configuration.
- Evidence strings are mandatory on every return path and must describe
  what was observed versus what was expected, in enough detail to debug
  a failed case without rerunning it.

### 12.5 Reproducible ground truth

Hardcoded constants in `checks.py` (residue lists, expected values,
fixed shapes) must be reproducible from inputs. When a constant is
computed rather than typed by hand, the derivation lives as a script
under `development/test_case_<id>.py`, and the constant in `checks.py`
carries a comment naming the script. Re-running the script after the
source data changes must regenerate the same constants verbatim.

### 12.6 Tests

`pyproject.toml` registers `eval_sets/` as a pytest path so `test_*.py`
files inside an eval-set directory are auto-discovered. Eval-set tests
cover the helpers in `checks.py`; the harness's grading dispatcher and
contract are tested separately under `tests/`.
