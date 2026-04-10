# playmoleculeai-evals — Code Spec

This document defines *how the code should look*: stack choices, module
boundaries, interface shapes, data schemas, naming conventions, and testing
expectations. The roadmap and architectural reasoning live in `docs/plan.md`.

Treat this spec as the contract. If you are about to write code that violates
a rule here, update the spec in the same commit.

---

## 1. Tech stack

| Concern | Choice |
|---|---|
| Language | Python 3.11+ |
| Packaging | `uv` with `pyproject.toml`, `src/pmai_evals/` layout |
| Browser automation | `playwright` (async API) |
| Config / models | `pydantic` v2 + `pydantic-settings` for `.env` loading |
| CLI | `typer` |
| HTTP | `httpx` (async) |
| Database | stdlib `sqlite3` in read-only URI mode (`?mode=ro`) |
| LLM providers | `anthropic`, `openai`, `google-genai` SDKs |
| YAML | `ruamel.yaml` (round-trippable, needed for comments in eval sets) |
| Logging | standard `logging` with a single root configurator; no `print()` outside the CLI |
| Testing | `pytest`, `pytest-asyncio`, `pytest-playwright` |
| Linting / formatting | `ruff` (lint + format) |
| Type checking | `pyright` in strict mode for `src/`, lenient for `tests/` |

No `print`, no `requests`, no `black`, no `mypy`, no `unittest`. One way to do
each thing.

## 2. Repo layout

```
playmoleculeai-evals/
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore                       # includes runs/, playwright/.auth/, .env
├── README.md
├── docs/
│   ├── plan.md
│   └── spec.md
├── src/pmai_evals/
│   ├── __init__.py
│   ├── config.py                    # Settings (pydantic-settings), loads .env
│   ├── pricing.yaml                 # model registry + price table
│   ├── cli.py                       # typer app: `pmai-evals {setup-auth,run,grade,report}`
│   ├── browser/
│   │   ├── __init__.py
│   │   ├── session.py               # PMBrowser (context manager, auth, page lifecycle)
│   │   ├── chat.py                  # new_chat, send_prompt, wait_for_completion, delete_chat
│   │   ├── observers.py             # JS eval helpers: screenshot, viewer_state, chat_id
│   │   ├── locators.py              # UI role/text locators in one place
│   │   └── fixtures.py              # upload eval fixtures into the project workspace
│   ├── trace/
│   │   ├── __init__.py
│   │   ├── reader.py                # load(chat_id, db_path) -> Trace
│   │   └── schemas.py               # Trace, Message, ToolCall, TokenUsage, TimingMetrics
│   ├── runner/
│   │   ├── __init__.py
│   │   ├── manifest.py              # plan the (case x model x seed) matrix
│   │   ├── executor.py              # hot loop: drives the browser and writes artifacts
│   │   ├── budget.py                # Budget with running cost + ceiling
│   │   └── artifacts.py             # RunArtifact writer/reader
│   ├── grading/
│   │   ├── __init__.py
│   │   ├── assertions.py            # all programmatic assertion implementations
│   │   ├── judge.py                 # LLM judge: absolute + blind pairwise
│   │   ├── critique.py              # "grade the grader" pass
│   │   ├── rubrics/
│   │   │   └── visualization.yaml
│   │   └── prompts/
│   │       ├── judge_absolute.md
│   │       ├── judge_pairwise.md
│   │       └── critique.md
│   ├── reporting/
│   │   ├── __init__.py
│   │   ├── aggregate.py             # benchmark.json (mean, stderr, per-tag slices)
│   │   └── render.py                # markdown + HTML
│   └── schemas.py                   # top-level pydantic models shared across layers
├── eval_sets/
│   └── molecular-visualization/
│       ├── eval_set.yaml
│       ├── cases.yaml
│       ├── fixtures/
│       │   └── ligand.sdf
│       └── rubric.md
├── runs/                            # gitignored; see §4.4
├── playwright/.auth/                # gitignored; storage_state.json
└── tests/
    ├── conftest.py
    ├── test_trace_reader.py
    ├── test_assertions.py
    ├── test_budget.py
    ├── test_runner_manifest.py
    └── test_browser_session.py      # playwright integration test, marked @pytest.mark.browser
```

**Layout rules:**

- Code lives under `src/pmai_evals/`. Eval data lives under `eval_sets/`.
  Mixing them is forbidden — an eval set is data, not code.
- Every submodule has an `__init__.py` that re-exports its public symbols.
  Internal helpers are prefixed with `_`.
- No file should exceed ~400 lines. If you need more, split by concern.
- Shared types go in the layer's local `schemas.py` (e.g. `trace/schemas.py`)
  or in `src/pmai_evals/schemas.py` if used across layers.

## 3. Naming conventions

- **Classes** — `PascalCase`. Async methods carry no `async_` prefix.
- **Functions / methods** — `snake_case`. Prefer verbs for actions
  (`load_trace`, `compute_cost`), nouns for factories (`new_chat`).
- **Module names** — short, concrete, single-responsibility
  (`session.py`, `chat.py`, not `utils.py` or `helpers.py`).
- **Run ids** — `YYYYMMDD-HHMMSS_<eval_set>_<label>`.
  Example: `20260408-151230_molecular-visualization_iter-01`.
- **Case ids** — `kebab-case`, stable across runs
  (`load-ligand-sdf`, `align-1crn-1cbn`).
- **Artifact filenames** — lowercase, no spaces, extension-first semantics
  (`trace.json`, `screenshot.png`, `grade.json`).
- **Environment variables** — `PM_*` for playmolecule connection,
  `PMAI_EVALS_*` for eval harness knobs. No other prefixes.

## 4. Module contracts

Type signatures below are the source of truth. Implementations may add
private helpers but must not change these shapes without updating the spec.

### 4.1 `config.Settings`

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # connection
    pm_frontend_url: str
    pm_backend_url: str
    pm_agent_url: str
    pm_db_path: Path

    # auth
    pm_email: str | None = None
    pm_password: str | None = None
    pm_user_bucket: str
    pm_project: str

    # judge
    pmai_evals_judge_model: str = "claude-sonnet-4-6"
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    gemini_api_key: str | None = None

    # run defaults
    pmai_evals_max_cost_usd: float = 10.0
    pmai_evals_results_dir: Path = Path("./runs")
    pmai_evals_headless: bool = True
    pmai_evals_log_level: str = "INFO"
```

One `Settings` instance per process, loaded at entrypoint, passed explicitly
into functions that need it. Do not use module-level globals.

### 4.2 `browser.session.PMBrowser`

```python
class PMBrowser:
    """Async context-managed browser driver bound to one agent frontend URL."""

    def __init__(self, settings: Settings, *, storage_state: Path | None = None): ...

    async def __aenter__(self) -> "PMBrowser": ...
    async def __aexit__(self, exc_type, exc, tb) -> None: ...

    async def ensure_authenticated(self) -> None:
        """Loads storage_state if present and valid; else runs login flow and saves it."""

    async def new_chat(self, *, model: str, project: str) -> "ChatSession":
        """Opens a fresh page, navigates, waits for Pyodide ready, selects model."""

class ChatSession:
    """One chat: one page, one chat_id, one set of artifacts."""

    chat_id: str  # populated after first prompt

    async def upload_fixtures(self, fixtures: Sequence[Path]) -> None: ...
    async def send_prompt(self, prompt: str) -> None: ...
    async def wait_for_completion(self, *, timeout_s: int) -> CompletionStatus: ...
    async def get_viewer_state(self) -> dict: ...
    async def save_screenshot(self, path: Path) -> None: ...
    async def get_final_answer(self) -> str: ...
    async def delete_chat(self) -> None: ...
    async def close(self) -> None: ...

class CompletionStatus(StrEnum):
    completed = "completed"
    failed = "failed"
    timed_out = "timed_out"
```

**Rules:**

- `PMBrowser` owns exactly one Playwright `BrowserContext`. It is reused across
  cases in the same run for auth amortization.
- Each `ChatSession` owns exactly one `Page`. A `ChatSession` is single-use —
  close it after extracting artifacts, do not send multiple prompts through
  one `ChatSession`.
- All Playwright calls use role/text locators, never CSS selectors. Locators
  that must be tuned live in `browser/locators.py` as module-level constants:

  ```python
  PROMPT_INPUT = ("textbox", "Ask anything.")
  REGENERATE_BUTTON = ("button", "Regenerate")
  NEW_CHAT_BUTTON = ("button", "New chat")
  ```

- Completion detection has three fallbacks, checked in order: `Regenerate`
  button enabled, `Message.status == "completed"` in SQLite, hard timeout.
- Observer helpers (screenshot, viewer state) are read-only JS `page.evaluate`
  calls — they must never mutate the page or intercept network traffic.

### 4.3 `trace.reader.load_trace`

```python
def load_trace(chat_id: str, db_path: Path) -> Trace: ...

@dataclass(frozen=True)
class Trace:
    chat_id: str
    model: str
    messages: tuple[Message, ...]
    tool_calls: tuple[ToolCall, ...]   # flat, chronological
    usage: TokenUsage                  # summed across turns
    metrics: TimingMetrics             # derived from MessageMetrics rows
    final_answer: str
    status: Literal["completed", "failed", "timed_out"]

@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict                    # parsed from JSON
    output: str | None
    error: str | None
    latency_ms: int | None
    turn_index: int

@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    cached_tokens: int                 # default 0
    reasoning_tokens: int              # default 0

@dataclass(frozen=True)
class TimingMetrics:
    ttft_ms: int | None                # first turn only
    total_ms: int
    tool_latency_ms: int               # sum across turns
```

The reader **must** open the SQLite DB read-only via stdlib `sqlite3`
with the URI form (`file:{path}?mode=ro`, `uri=True`). It must not write.

### 4.4 Artifact layout

```
runs/<run_id>/
├── run.json                     # RunConfig snapshot + git SHA + env
├── manifest.json                # planned (case, model, seed) matrix
├── cost.json                    # running budget
├── summary.json                 # written after grading
└── <case_id>/<model>/seed-<N>/
    ├── trace.json               # Trace serialized via pydantic
    ├── final_answer.md
    ├── viewer_state.json
    ├── screenshot.png
    ├── dom_snapshot.html        # optional, for post-mortem
    ├── metrics.json             # TokenUsage + TimingMetrics + cost_usd
    ├── grade.json               # written by grade stage; absent if not yet graded
    └── status                   # one-line: completed | failed | timed_out | skipped_over_budget
```

**Rules:**

- Artifacts are write-once. The runner never overwrites a completed case
  directory — re-runs go to a new `run_id`.
- `grade.json` is the only file the grade stage writes. Runs and grades are
  decoupled: if `grade.json` is missing you can re-grade without re-running.
- Every JSON file uses UTF-8, 2-space indent, trailing newline, sorted keys
  for stable diffs.
- `status` is a plain text file (not JSON) so `cat status` works in a shell.

### 4.5 `grading.assertions`

```python
class AssertionResult(BaseModel):
    assertion_type: str
    passed: bool
    evidence: str                      # short, cite-able; required whether pass or fail
    config: dict                       # the original assertion spec

class Assertion(Protocol):
    def __call__(self, artifact: RunArtifact, *, config: dict) -> AssertionResult: ...

ASSERTION_REGISTRY: dict[str, Assertion] = {
    "output_contains": check_output_contains,
    "output_matches_regex": check_output_matches_regex,
    "output_numeric_close": check_output_numeric_close,
    "tool_called": check_tool_called,
    "tool_called_with": check_tool_called_with,
    "tool_call_count": check_tool_call_count,
    "tool_call_order": check_tool_call_order,
    "no_tool_error": check_no_tool_error,
    "viewer_has_molecule": check_viewer_has_molecule,
    "viewer_representation_is": check_viewer_representation_is,
    "viewer_color_scheme_is": check_viewer_color_scheme_is,
    "viewer_has_residue": check_viewer_has_residue,
    "viewer_system_count": check_viewer_system_count,
    "file_exists": check_file_exists,
    "file_content_matches": check_file_content_matches,
}
```

**Rules:**

- Every assertion function is pure: `(RunArtifact, config) -> AssertionResult`.
  No network, no disk writes, no LLM calls.
- `evidence` is mandatory. On pass it cites where the pass came from
  (`"pmview_load called at turn 2 with args={'path': 'ligand.sdf'}"`); on fail
  it describes what was expected vs observed.
- Adding a new assertion type = one function + one entry in the registry + one
  unit test in `tests/test_assertions.py`. No other touchpoints.
- Assertions must be discriminating. During development, verify any new
  assertion fails on a deliberately wrong artifact before committing it.

### 4.6 `grading.judge.LLMJudge`

```python
class JudgeMode(StrEnum):
    absolute = "absolute"
    pairwise = "pairwise"

class LLMJudge:
    def __init__(self, model: str, settings: Settings): ...

    async def grade_absolute(
        self,
        artifact: RunArtifact,
        rubric: Rubric,
    ) -> RubricGrade: ...

    async def grade_pairwise(
        self,
        a: RunArtifact,
        b: RunArtifact,
        rubric: Rubric,
    ) -> PairwiseGrade: ...

class Rubric(BaseModel):
    dimensions: list[RubricDimension]
    pass_threshold: float = 3.5        # on the 1-5 scale

class RubricDimension(BaseModel):
    name: str
    question: str
    scale: tuple[int, int] = (1, 5)

class RubricGrade(BaseModel):
    overall_score: float
    passed: bool
    dimensions: list[DimensionScore]
    evidence: list[str]                # citations drawn from the transcript

class DimensionScore(BaseModel):
    name: str
    score: float
    justification: str
    evidence: str
```

**Rules:**

- Judge prompts live in `grading/prompts/*.md` and are loaded at call time.
  No f-string prompts in Python files — edit the markdown.
- Judge output is forced JSON via the provider's structured-output mode.
- Blind pairwise mode strips identifying info (model name, `chat_id`,
  timestamps) from both artifacts before constructing the judge prompt.
  Label them only as `A` and `B`.
- Screenshots are passed as vision inputs when available. If the judge model
  does not support vision, the judge raises; the runner catches and falls
  back to text-only with a warning recorded in `grade.json`.
- Judge failures (API errors, parse errors) produce a `grade.json` with
  `status: "judge_error"` and the error captured. They never abort the grade
  stage mid-run.

### 4.7 `runner.executor`

```python
async def run_matrix(
    eval_set: EvalSet,
    config: RunConfig,
    settings: Settings,
) -> RunSummary: ...

class RunConfig(BaseModel):
    models: list[str]
    seeds: int = 1
    max_cost_usd: float
    headless: bool
    tier: Literal["flagship", "cheap", "all"] | None = None
    case_filter: list[str] | None = None   # run only these case ids
    run_label: str                         # human-readable suffix for run_id
    judge_model: str
```

**Rules:**

- The executor creates one `PMBrowser` per model (not per case): amortizes
  login + storage_state reuse. Cases run sequentially within a model.
- Per-case flow matches the sequence in `docs/plan.md` §4 exactly. Any
  deviation is a spec violation and needs a spec update first.
- `Budget` is checked before every rollout. Abort is clean: write partial
  summary, mark unrun cases `skipped_over_budget`, exit with non-zero.
- The executor never calls `grading/`. It produces artifacts; grading is a
  separate CLI subcommand.
- Exceptions inside a single case are caught, logged, and recorded as
  `status: failed`. One bad case does not poison the run.

### 4.8 CLI (`cli.py`)

```
pmai-evals setup-auth
    Run the interactive login flow and save storage_state.json.

pmai-evals run --eval-set molecular-visualization [options]
    --models gpt-5.4,claude-sonnet-4-6     Comma-separated model ids
    --tier {flagship,cheap,all}            Shortcut for model selection
    --seeds N                              Default 1
    --max-cost USD                         Default from $PMAI_EVALS_MAX_COST_USD
    --headless / --no-headless             Default headless
    --case <id>                            Run only this case (repeatable)
    --label <str>                          Suffix for run_id
    --judge-model <id>                     Override judge model
    --dry-run                              Print manifest, do not execute

pmai-evals grade <run_id> [options]
    --judge-model <id>                     Override judge model
    --force                                Re-grade even if grade.json exists
    --rubric <path>                        Override the eval set's rubric

pmai-evals report <run_id> [options]
    --format {markdown,html,json}          Default markdown

pmai-evals critique <run_id>
    Run the "grade the grader" pass; emit critique.json
```

**Rules:**

- All CLI commands are thin wrappers around functions in the library layers.
  Business logic never lives in `cli.py`.
- Every CLI command exits with code `0` on success, `1` on user error,
  `2` on budget abort, `3` on unrecoverable harness error. Document in
  `README.md`.

## 5. Data schemas

### 5.1 `eval_set.yaml`

```yaml
id: molecular-visualization
skill_under_test: pmview
description: Basic molecular viewer operations — load, select, render, measure.
difficulty: mixed
requires_browser: true
default_timeout_s: 300
default_expected_cost_usd: 0.05
rubric_path: rubric.md
tags: [viewer, visualization]
```

### 5.2 `cases.yaml`

```yaml
cases:
  - id: load-1crn
    difficulty: trivial
    prompt: "Load the PDB entry 1CRN on the viewer."
    tags: [load]
    timeout_s: 120
    expected_cost_usd: 0.02
    assertions:
      - type: tool_called
        name: pmview_load
      - type: viewer_has_molecule
        identifier: "1CRN"
    rubric:
      enabled: false

  - id: load-ligand-sdf
    difficulty: trivial
    prompt: "Load ligand.sdf and tell me its SMILES."
    fixtures: [ligand.sdf]
    tags: [load, smiles]
    assertions:
      - type: output_contains
        value: "Cn1cnc2c1c(=O)n(c(=O)n2C)C"
        case_sensitive: true
      - type: tool_called
        name: pmview_load
    rubric:
      enabled: true
      dimensions:
        - name: correctness
          question: "Does the answer report the correct SMILES without hedging?"
        - name: communication
          question: "Is the SMILES cited cleanly in the final answer?"
```

**Rules:**

- YAML is the canonical format for eval definitions. JSON is for runtime
  artifacts.
- `cases.yaml` is validated against a pydantic model on load. Unknown keys
  are an error, not a warning.
- Every assertion has `type` plus type-specific config. Unknown assertion
  types are an error at load time, not at run time.
- `fixtures` paths are relative to the eval set directory. The runner
  uploads them before sending the prompt.

### 5.3 `run.json`

```json
{
  "run_id": "20260408-151230_molecular-visualization_iter-01",
  "eval_set": "molecular-visualization",
  "started_at": "2026-04-08T15:12:30+00:00",
  "finished_at": null,
  "git_sha": "c9d6646...",
  "config": {
    "models": ["gpt-5.4", "claude-sonnet-4-6", "gemini-3.1-pro-preview"],
    "seeds": 1,
    "max_cost_usd": 10.0,
    "headless": true,
    "judge_model": "claude-sonnet-4-6"
  },
  "environment": {
    "pm_frontend_url": "http://localhost:5173",
    "pm_agent_url": "http://localhost:8102",
    "pm_db_path": "/fast_shared/.../agent.db"
  }
}
```

### 5.4 `grade.json`

```json
{
  "case_id": "load-ligand-sdf",
  "model": "claude-sonnet-4-6",
  "seed": 0,
  "assertions": [
    {
      "assertion_type": "output_contains",
      "passed": true,
      "evidence": "Final answer text contained 'Cn1cnc2c1c(=O)n(c(=O)n2C)C' at offset 142.",
      "config": {"type": "output_contains", "value": "Cn1cnc2c1c(=O)n(c(=O)n2C)C"}
    }
  ],
  "rubric": {
    "overall_score": 4.5,
    "passed": true,
    "dimensions": [
      {
        "name": "correctness",
        "score": 5,
        "justification": "The reported SMILES exactly matches the expected canonical form.",
        "evidence": "Final answer: 'The SMILES is Cn1cnc2c1c(=O)n(c(=O)n2C)C (caffeine).'"
      }
    ]
  },
  "summary": {
    "assertions_passed": 2,
    "assertions_total": 2,
    "rubric_passed": true
  }
}
```

## 6. Conventions

### 6.1 Async

- Everything that touches I/O is `async`. No sync wrappers around async code,
  no `asyncio.run` except at the CLI boundary.
- Sequence concurrent work with `asyncio.gather` when tasks are independent.
  Do not spawn fire-and-forget tasks; use `asyncio.TaskGroup`.

### 6.2 Typing

- Full type hints on every public function and class.
- `Any` is a smell. Document why when it is unavoidable.
- Prefer frozen dataclasses for plain data, pydantic models for validated
  boundaries (config, assertions, grades).
- Type-check with `pyright` strict on `src/`. Broken type checks fail CI.

### 6.3 Errors

- Raise typed exceptions from `src/pmai_evals/errors.py`
  (`BrowserError`, `TraceNotFoundError`, `BudgetExceededError`,
  `AssertionConfigError`, `JudgeError`, ...).
- Never catch bare `Exception` except at the top-level runner for per-case
  isolation, and in that one place the exception is logged with full
  traceback and rewrapped into a `RunFailed` status.
- No silent fallbacks. If a fallback is taken, record it in the artifact's
  `metrics.json` or `grade.json`.

### 6.4 Logging

- One `logging.getLogger(__name__)` per module. No module-level handler setup
  outside `cli.py`.
- Log levels: `DEBUG` for tracing, `INFO` for lifecycle events, `WARNING`
  for recoverable anomalies, `ERROR` for case failures, `CRITICAL` for
  run aborts.
- Every log line for a rollout carries `run_id`, `case_id`, `model`, `seed`
  as structured extras. Use `extra={"run_id": ..., ...}`.

### 6.5 Comments and docstrings

- Docstring on every public class and function: one-line summary, optional
  args/returns for non-trivial shapes.
- Comments explain *why*, not *what*. If the code needs a comment to
  describe what it does, rewrite the code first.
- TODO comments include the author and a Github issue number or are
  forbidden.

### 6.6 Determinism

- No `datetime.now()` inside core logic — pass a clock in or use
  `settings.clock()`. The runner may capture `started_at` at the top of
  `run_matrix`; everything downstream uses that one value.
- No `random` inside graders. Seed is a case-level input the executor sets
  before calling the agent; graders are deterministic functions of artifacts.

### 6.7 Secrets

- Secrets come from `.env` or the process environment. They are never
  committed, logged, or written to artifacts.
- `storage_state.json` is treated as a secret — gitignored, stored under
  `playwright/.auth/`, never copied into `runs/`.

## 7. Testing

### 7.1 Unit tests (fast, pure)

- `tests/test_trace_reader.py` — fixture DBs with canned rows, assert parse
  correctness.
- `tests/test_assertions.py` — one test per assertion type, with a
  hand-crafted `RunArtifact` fixture, covering pass and fail paths.
- `tests/test_budget.py` — charging, ceiling enforcement, partial-run state.
- `tests/test_runner_manifest.py` — matrix planning, tier filtering, case
  filtering.
- `tests/test_grade_serialization.py` — pydantic round-trips for every
  schema in `schemas.py`.

All unit tests run in under 10 seconds total. No network, no DB beyond
tmpfs SQLite fixtures, no Playwright.

### 7.2 Integration tests (slower, marked)

- `tests/test_browser_session.py` — marked `@pytest.mark.browser`. Launches
  a real Chromium headless, navigates to `$PM_FRONTEND_URL`, runs a
  single canned prompt, verifies artifact layout is written correctly.
  Run opt-in with `pytest -m browser`.
- `tests/test_end_to_end.py` — marked `@pytest.mark.e2e`. Full harness run
  of one cheap model on one case, grading included. Run nightly or on
  demand, not in fast CI.

### 7.3 Eval-set linting

`pmai-evals` exposes no separate command for this. Instead, loading an eval
set through the runner validates it fully (pydantic + assertion-registry
lookup + fixture existence). The CI job `pmai-evals run --dry-run` on every
eval set serves as the lint.

## 8. What NOT to build

These are explicit non-features. If you find yourself tempted, re-read this
section.

- **No custom Pyodide REPL wrapper.** The old `pmvier_browser.py` had one.
  We do not. We drive the UI and let the production path handle Python
  execution.
- **No client-side tool interception.** The agent server dispatches pmview
  calls via WebSocket to the connected browser. We do not intercept or
  replay.
- **No SSE stream parsing for trace data.** SQLite is the source of truth.
- **No `utils.py`.** Every helper belongs in a module named for its
  responsibility.
- **No rubric inlined in Python.** Rubric dimensions live in YAML; rubric
  prompts live in markdown.
- **No retries on assertion failures.** A retry hides a real signal.
  Retries live at the network layer only (transient API errors).
- **No "smart" backoff / auto-tuning of eval prompts.** Evals are fixed
  data. Changing a case is a git commit, not runtime behavior.
- **No per-case concurrency within a model.** Cases run sequentially per
  model. Parallelism across models is permitted but not required day one.
- **No dashboard / web UI.** Reporting is static HTML + markdown. If you
  need a dashboard, use the existing
  `/fast_shared/users/carles/data/playmoleculeAIdata/dashboard/`.
- **No database writes.** The trace DB is read-only from our side.

## 9. Adding a new eval (the whole checklist)

1. `mkdir eval_sets/<name>/`.
2. Write `eval_set.yaml` with id, skill tag, description, default timeout,
   default expected cost, optional rubric path.
3. Write `cases.yaml` with 5–10 cases. Each case has `id`, `prompt`,
   optional `fixtures`, `assertions`, optional `rubric`.
4. Drop fixture files in `eval_sets/<name>/fixtures/`.
5. If qualitative grading is enabled, write `rubric.md` with dimensions
   keyed to case rubrics.
6. `pmai-evals run --eval-set <name> --tier cheap --dry-run` to validate.
7. `pmai-evals run --eval-set <name> --tier cheap --max-cost 1` for a
   cheap end-to-end sanity check.
8. `pmai-evals run --eval-set <name> --tier flagship` for the real run.
9. `pmai-evals grade <run_id>` followed by `pmai-evals report <run_id>`.

If any of these steps required editing code under `src/pmai_evals/`, the
harness has drifted from "declarative eval addition" and needs to be fixed.
