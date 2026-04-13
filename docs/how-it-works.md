# How it works

A high-level tour of what happens when you run an eval, end to end. Read
this first if you've never used the harness; read [`writing-evals.md`](writing-evals.md)
next if you want to author one.

## The three stages

The pipeline splits cleanly into three CLI commands. Each stage is
re-runnable, reads from disk, and writes to disk — no hidden state.

```
 run            grade           report
  │                │               │
  ▼                ▼               ▼
 trace.json    grade.json     benchmark.{md,html,json}
 screenshot.png
 viewer_state.json
 final_answer.md
```

### 1. `run` — exercise the agent

For each `(case, model, seed)` cell in the matrix:

1. Open a fresh browser page at `acellera.playmolecule.ai`, authenticated
   from the stored `storage_state.json`.
2. Upload any declared fixtures into the project workspace.
3. Fill the prompt box with the case prompt and press Enter.
4. Capture `chat_id` from the `x-chat-id` response header on the rollout
   POST — this is the server's authoritative handle for the chat.
5. Wait until the "Regenerate" button re-enables, meaning the model has
   finished streaming and any tool calls have settled.
6. Fetch the full chat history via `GET /v3/agent/chat/{chat_id}`,
   dump the Molstar viewport screenshot, and read the Pyodide-side
   `systems_tree` from the viewer.
7. Write artifacts under `runs/<run_id>/<case_id>/<model>/seed-<N>/`.
8. Soft-delete the chat on the server (`DELETE /v3/agent/chat/{id}`).

The runner never grades anything. It only collects evidence.

### 2. `grade` — score the artifacts

For each cell directory that has no `grade.json` yet (or all of them
with `--force`):

1. Load the case spec from `cases.yaml`.
2. Run every **assertion** declared on the case against the cell's
   artifacts. Assertions are deterministic Python functions, cheap,
   re-runnable, and produce a pass/fail plus a human-readable evidence
   string.
3. If the case has a **rubric** enabled, call the LLM judge with the
   case prompt, the final answer, a trace summary, and (for vision
   models) the screenshot. The judge returns per-dimension 1–5 scores
   and an overall mean; the cell passes the rubric iff the mean clears
   `pass_threshold`.
4. Write both results into `grade.json`.

Assertions and the rubric are independent. A cell can pass all
assertions and fail the rubric, or vice versa — that's a feature, not a
bug. The report shows both.

### 3. `report` — aggregate and render

Walks every cell, rolls up assertion pass rates and rubric means per
model, and emits:

- `benchmark.json` — the machine-readable aggregate.
- a `markdown`, `html`, or `json` view to stdout (or `--out` file).

There's also `critique` ("grade the grader"), which flags rubric
dimensions or assertions that failed to discriminate between models.
That's an optional fourth pass, not part of the normal loop.

## Artifacts on disk

Every cell produces the same tree:

```
runs/<run_id>/<case_id>/<model>/seed-<N>/
├── trace.json          # messages + tool calls, via HTTP chat history
├── final_answer.md     # last assistant message, plain text
├── viewer_state.json   # Pyodide systems_tree (what molecules are loaded)
├── screenshot.png      # Molstar viewport
├── metrics.json        # latency, status, counters
├── grade.json          # written by `grade`; absent until then
└── status              # one-line plaintext: completed | failed | timed_out
```

Everything downstream reads only these files. You can delete `grade.json`
and re-grade; you cannot re-run without a fresh `run_id`.

## The two scoring pipes

This is the key mental model.

| | **Assertions** | **Rubric (LLM judge)** |
|---|---|---|
| Who runs it | Python functions in `grading/assertions.py` | An LLM (Claude Sonnet by default) |
| Input | `trace.json`, `viewer_state.json`, `final_answer.md`, files | Same, plus the screenshot for vision models |
| Output | List of `(passed, evidence)` per assertion | 1–5 score per rubric dimension, plus a mean |
| Cost | Free | One API call per cell |
| Good for | Hard facts: was the tool called, is the PDB loaded, does the answer contain a specific token | Judgment calls: is the camera framing right, is the answer hedging, is the reasoning sound |

You want **both** on most cases. Assertions catch regressions cheaply
and point at exactly what broke. The rubric catches quality issues you
can't express as a regex or a dict lookup.

## Why HTTP for traces

Earlier versions read traces from a local copy of the SQLite database,
which went stale fast. The harness now pulls chat history directly from
`GET /v3/agent/chat/{id}`. One known limitation: the endpoint doesn't
expose per-message token usage or latency, so cost and timing fields
are zeroed in `trace.json`. If you need cost tracking, that's a backend
change, not a harness change.

## Where to look next

- **Author an eval** → [`writing-evals.md`](writing-evals.md)
- **Change how the code is organised** → [`spec.md`](spec.md) (the code contract)
- **Understand the roadmap** → [`plan.md`](plan.md)
