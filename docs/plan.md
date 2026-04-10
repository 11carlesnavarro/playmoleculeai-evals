# playmoleculeai-evals — Plan

Evals for the playmoleculeAI agentic system for drug discovery. This document is
the authoritative plan for *what* we are building and *why*. Code structure,
style conventions, and interface shapes live in `docs/spec.md`.

---

## 1. Goals

1. **Automate end-to-end evals** of the playmoleculeAI agent, including the
   molecular viewer, across multiple LLM providers (GPT, Claude, Gemini) without
   any manual browser interaction.
2. **Grade both programmatically and qualitatively.** Hard assertions over
   traces and viewer state for verifiable facts; rubric-based LLM-as-judge
   (with vision) for subjective quality.
3. **Make adding a new eval cheap.** New eval = new directory with a YAML
   description, fixtures, and optionally a custom rubric. No harness code
   changes for most new evals.
4. **Stay faithful to the real user experience.** The browser is always in the
   loop. Whatever ships to real users is what we measure.

## 2. Non-goals

- Not a load-test / benchmarking harness for throughput or concurrency. That
  lives in `playmoleculeAI/evals/benchmarks/locustfile.py`.
- Not a replacement for unit tests of the agent server or individual skills.
- Not a "one giant eval set" — evals stay small (~10 cases per set), runnable
  independently, and graded incrementally.

## 3. System under test (brief)

The playmoleculeAI system consists of three pieces the evals must account for:

- **Agent server** — FastAPI at `:8102` (dev) / `:8100` (prod), OpenAI-compatible
  `POST /v1/responses` with SSE streaming. Routes to GPT / Claude / Gemini by
  model-name prefix. Full traces persisted to SQLite.
- **Web frontend** — Vue app at `http://localhost:5173` (dev) or
  `https://open.playmolecule.org` (prod). Hosts the Molstar 3D viewer and a
  Pyodide worker that runs skill code in-browser. Connects to the agent via
  WebSocket for pmview tool dispatch.
- **SQLite trace DB** — at `/fast_shared/users/carles/data/playmoleculeAIdata/data/databases/{dev,prod,open}/agent.db`.
  Contains `Chat`, `Message`, `MessageMetrics` tables with full tool calls,
  token usage, latency, TTFT, and status per turn. Authoritative source for
  post-hoc trace analysis. Read patterns cribbed from
  `/fast_shared/users/carles/data/playmoleculeAIdata/dashboard/backend/store_*.py`.

**Skills** live in two repos:

- Project skills: `/fast_shared/users/carles/repos/acellera/playmoleculeAI/skills/`
- Org skills: `/fast_shared/users/carles/repos/acellera/acellera-skills/skills/`
  (`data-retrieval`, `playmolecule`, `molecule-modification`, `sar-analysis`,
  `latex-publication`)

Skills are loaded at agent startup and injected into the system prompt. They
are not runtime-loaded, so from the eval's perspective the "skill under test"
is a tag on an eval set — the actual dispatch is implicit in the agent's
behavior.

## 4. Architecture decisions

### 4.1 The browser is always in the loop (Phase 0, not Phase 3)

The viewer is a central part of the agent, not an optional visualization add-on.
Every eval runs inside a live Playwright browser session, even when the prompt
seems text-only, because:

- The agent may choose to use the viewer to understand 3D data.
- pmview tool calls flow through the server→WebSocket→browser Pyodide path;
  without a connected browser, those calls fail.
- We want to measure behavior as users experience it.

There is no "headless-only" eval path. Browser is phase zero.

### 4.2 Drive the real production UI; do not intercept tool calls

Two existing patterns in sibling repos:

- **Pattern A — `scripts/pmvier_browser.py`** (playmoleculeAI, recoverable via
  `git show d6df665:scripts/pmvier_browser.py`). Python + `browser_use` wrapper.
  Intercepts pmview tool calls from the SSE stream, executes them client-side
  in Pyodide via custom `window.pyodideWorker.RunPythonAsync(...)` wrappers,
  and re-injects results into the agent loop. ~555 lines including REPL
  namespace injection and VFS plumbing. Reimplements the server's tool loop.
- **Pattern B — `playmolecule-tests`** (acellera/playmolecule-tests). TypeScript
  + `@playwright/test`. Logs into `https://open.playmolecule.org`, saves
  `storage_state.json`, drives the chat UI with
  `getByRole('textbox', { name: 'Ask anything.' })`, uses the "Regenerate"
  button re-enabling as the completion signal. No tool interception — pmview
  calls flow through the real production WS path. Reference at
  `tests/agent-search-moleculekit.spec.ts`.

**Decision: adopt Pattern B, reimplemented in Python Playwright.**

Rationale:
- Tests the production code path end-to-end, including the WebSocket and
  frontend routing.
- No parallel re-implementation of the agent loop to maintain.
- Dramatically less code. Target: ~200 lines of browser driver vs the old 555.
- Survives changes to the agent server's tool dispatch without modification.

We reuse two read-only JS snippets from the old `pmvier_browser.py` as
pure observers (not interceptors):

- Screenshot: `window.molstar.helpers.viewportScreenshot.getImageDataUri()`
- Viewer state: `window.pyodideWorker.RunPythonAsync(...)` against
  `_internal_py_utils.systems_tree`

Those are grading signals, not control flow.

### 4.3 Python, not TypeScript

`playmolecule-tests` is TypeScript because Playwright's JS API was the natural
choice for UI-only tests. Our eval repo needs SQLite reading, pandas
aggregation, LLM judge calls (vision), rubric handling, cost math — all
Python-native. Playwright Python is a first-class peer; same selectors, same
contexts, same `storage_state` mechanism. Keeping the whole stack in one
language matters more than matching `playmolecule-tests`' language.

### 4.4 Run and grade are decoupled

Running produces artifacts on disk. Grading is a pure function of artifacts
to grades. This means:

- Grading can be re-run with a better rubric without re-paying for rollouts.
- Switching the judge model is a config change, not a re-run.
- Historical runs remain useful as the eval set evolves.

This is the single most important architectural decision in the framework.
Every other design choice should defer to it.

### 4.5 Trace source is SQLite, not stream parsing

The agent server already persists the full trace (messages, tool calls, tool
outputs, token usage, latency, TTFT, status) to SQLite via
`playmoleculeAI/playmoleculeai/apps/agent/models/tables.py`. Rather than
parsing SSE events ourselves, the runner captures `chat_id` from the UI and
post-hoc queries the DB by that id. This gives us richer data than the stream
provides and keeps the browser driver simple.

### 4.6 One fresh chat per (case × model × seed)

Chat reuse is forbidden. Cross-case state leakage is too easy and silently
breaks grading. Opening a new chat is cheap compared to the rollout itself.
The expensive thing — auth — is amortized across the whole run via
Playwright's `storage_state`.

## 5. Phasing

| Phase | What | Exit criteria |
|---|---|---|
| **0 — Foundations** | Python Playwright driver (`PMBrowser`), `setup-auth` CLI, SQLite trace reader, runner skeleton, cost budget, artifact layout. | Run one prompt end-to-end in headless Chrome against all five models, get `trace.json` + `screenshot.png` + `metrics.json` for each. |
| **1 — First eval** | `eval_sets/molecular-visualization/` with 10 cases + fixtures, programmatic assertion library, markdown/HTML report. | Full matrix runs under `$10`, report ranks the three flagship models on this eval. |
| **2 — LLM judge** | Rubric-based vision judge (Sonnet default, configurable), blind pairwise comparator, "grade the grader" critique pass that flags non-discriminating assertions. | Can eval a subjective question and get a defensible score with cited evidence. |
| **3 — Second eval** | Pick based on Phase 1 learnings — most likely `data-retrieval` (PDB / UniProt lookups), to stress-test the harness with a different skill shape. | Adding this eval requires zero harness code changes, only new YAML + fixtures. |
| **4 — Workflow / case studies** | Multi-skill evals graded at trace level: docking, protein preparation pipelines, eventually binding-free-energy. Hard cost caps. | One end-to-end case study eval can be added following the same declarative pattern. |

Binding free energy is the endgame and the most expensive. It gets a handful
of cases, not ten, and its runner config sets explicit cost ceilings above
the default.

## 6. First eval: `molecular-visualization`

Ten cases, spanning difficulty. Every case requires the viewer. Every case
produces: final text answer, full trace, viewer state JSON, and screenshot.

| # | Difficulty | Prompt (paraphrased) | Programmatic assertions | Rubric focus |
|---|---|---|---|---|
| 1 | trivial | Load `1CRN` from the PDB on the viewer. | `viewer_has_molecule("1CRN")`, `tool_called("pmview_*")` | basic loading |
| 2 | trivial | Load `ligand.sdf` and tell me its SMILES. | `output_contains(expected_smiles)` | recall + reporting |
| 3 | easy | Load `3PTB`, show only chain A as cartoon. | `viewer_representation_is("cartoon")`, selection matches chain A | selection syntax |
| 4 | easy | Load `4HHB`, color by chain. | color scheme matches `by_chain` | color schemes |
| 5 | easy | Load `4HHB`, show heme groups as sticks. | `viewer_has_residue("HEM")`, representation contains sticks | ligand highlighting |
| 6 | medium | Load `1HVR`, rotate the camera to show the dimer interface. | camera-state sanity | 3D reasoning |
| 7 | medium | Align `1CRN` and `1CBN`. | `viewer_system_count == 2`, RMSD value in output | multi-molecule ops |
| 8 | medium | Measure distance between the two alpha-chain heme irons in `4HHB`. | output contains a distance within tolerance | measurement |
| 9 | hard | Load `1GZX`, highlight residues within 5 Å of heme, color by hydrophobicity. | selection correctness from trace, color scheme | compound selection |
| 10 | hard | Given two PDBs, determine which has better resolution of the active site. | both loaded, correct answer in output | reasoning + viewer use |

**Why this is the right pilot:**

- Forces the browser harness to work end-to-end on day one (loading,
  interacting, observing).
- Exercises both programmatic ground truth (SMILES, RMSD, distances, molecule
  presence) and subjective quality (is the visualization clear? is the camera
  well-positioned?).
- Bounded cost. ~1–2 minutes per case means a full 5-model run is 50–100
  minutes and well under `$10`.
- Failures here will surface exactly the harness issues we need to solve
  before layering on anything else.

## 7. Grading strategy

### 7.1 Two paths, combined per case

**Programmatic assertions** — cheap, deterministic, discriminating. First-pass
assertion types (full list in `docs/spec.md` §5.2):

- `output_contains`, `output_matches_regex`, `output_numeric_close`
- `tool_called`, `tool_called_with`, `tool_call_count`, `tool_call_order`
- `no_tool_error`
- `viewer_has_molecule`, `viewer_representation_is`,
  `viewer_color_scheme_is`, `viewer_has_residue`, `viewer_system_count`
- `file_exists`, `file_content_matches`

**LLM judge with vision** — consumes the same artifacts plus the screenshot
as a vision input. Two modes:

- *Absolute* — score one output against a rubric with numeric dimensions
  (1–5 per dimension: correctness, completeness, visualization quality, etc.).
- *Blind pairwise* — compare two outputs with identifying info stripped,
  pick a winner, justify with rubric-backed evidence. Used for model-vs-model
  comparisons (the user's core use case).

Default judge: `claude-sonnet-4-6`. Overridable via `PMAI_EVALS_JUDGE_MODEL`
env var or `--judge-model` CLI flag.

### 7.2 Borrowed philosophy from `skill-creator`

Ideas we take from the `skill-creator` Claude Code skill and apply here:

- **Assertions must be discriminating.** A passing weak assertion is worse
  than no assertion — it creates false confidence. During Phase 1 bring-up,
  cross-check by running one case against a known-bad model; any assertion
  that still passes is a candidate for tightening or removal.
- **Grade the grader.** After grading, a critique pass flags assertions that
  pass for all models (non-discriminating) and assertions that fail for all
  models (possibly buggy or misaligned with the prompt).
- **Evidence burden is on the expectation.** LLM judge output must cite
  specific text or trace fragments. No evidence = no pass.
- **Ground truth > rubric where possible.** Rubrics drift; ground truth
  doesn't. Prefer adding an assertion over adding a rubric dimension.
- **Snapshot metrics at run time.** Don't rely on re-deriving token counts
  or timing later. Write them to `metrics.json` immediately.

## 8. Configuration

### 8.1 `.env` (values to provide)

```dotenv
# playmolecule connection
PM_FRONTEND_URL=http://localhost:5173
PM_BACKEND_URL=http://localhost:8000
PM_AGENT_URL=http://localhost:8102
PM_DB_PATH=/fast_shared/users/carles/data/playmoleculeAIdata/data/databases/dev/agent.db

# auth (used once by `pmai-evals setup-auth`; storage_state.json then takes over)
PM_EMAIL=
PM_PASSWORD=
PM_USER_BUCKET=/shared2/pmai/pmbackend/public-projects
PM_PROJECT=pmai-evals

# judge & provider keys
PMAI_EVALS_JUDGE_MODEL=claude-sonnet-4-6
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GEMINI_API_KEY=

# run defaults (all overridable on CLI)
PMAI_EVALS_MAX_COST_USD=10.0
PMAI_EVALS_RESULTS_DIR=./runs
PMAI_EVALS_HEADLESS=true
PMAI_EVALS_LOG_LEVEL=INFO
```

`.env` is gitignored. A committed `.env.example` documents the shape. CLI
flags always override env values.

### 8.2 Model list

```yaml
models:
  # flagship — benchmark targets
  - id: gpt-5.4
    provider: openai
    tier: flagship
  - id: claude-sonnet-4-6
    provider: anthropic
    tier: flagship
  - id: gemini-3.1-pro-preview
    provider: google
    tier: flagship

  # cheap — harness iteration and debugging
  - id: gpt-5.4-mini
    provider: openai
    tier: cheap
  - id: gpt-5.4-nano
    provider: openai
    tier: cheap
```

CLI defaults: `--tier flagship` for benchmark runs, `--tier cheap` when
iterating on the harness or eval definitions, `--models gpt-5.4-nano` to pin
a single model for debugging.

Price tables for cost computation live in `pmai_evals/pricing.yaml` alongside
the model registry, updated manually when provider pricing changes.

### 8.3 Cost cap

A `Budget` object tracks `total_cost_usd` across a run. After each rollout
it charges the cost computed from `Message.usage × price_table`. Before
each new rollout it checks the ceiling; if exceeded the runner aborts,
marks remaining cases as `skipped_over_budget`, writes the partial summary,
and exits non-zero. Default `$10` from `.env`, overridable with
`--max-cost 50` on the CLI. Per-case expected-cost hints in YAML enable
pre-flight "you're about to spend a lot, confirm?" checks.

## 9. Open questions

1. **Model dropdown in the UI.** Does the dev/prod frontend expose all five
   target models, or is it gated by tier/user? If gated, the Phase 0 browser
   driver needs a fallback path: call `/v1/responses` directly with cookies
   stolen from the Playwright context while keeping the browser alive so the
   WS connection services pmview tool calls naturally.
2. **`chat_id` extraction.** Is it embedded in the URL after creating a new
   chat (`/chat/<uuid>`), or only observable via JS eval on an app store?
   This is a Phase 0 probe.
3. **Frontend URL default.** `http://localhost:5173` is what the old
   `pmvier_browser.py` used and what this plan defaults to. Confirm this is
   still the right port for the dev frontend.
4. **Target instance for benchmark runs.** Dev server (fast, isolated but may
   lack production skills) or `https://open.playmolecule.org` (slow, shared,
   real). Per-run choice via `PM_FRONTEND_URL` — but the default matters.
5. **Cross-browser.** Chromium only (simpler), or all three browsers like
   `playmolecule-tests`? For correctness evals Chromium-only is fine; for
   compatibility regressions we want all three eventually.

## 10. References

- Agent server entrypoints —
  `playmoleculeAI/playmoleculeai/apps/agent/routes/responses.py:202` (rollout)
  and `playmoleculeAI/playmoleculeai/apps/agent/routes/ws.py` (pmview WS).
- Existing test client —
  `playmoleculeAI/evals/scripts/evals.py:138` (`AgentClient`).
- Old browser driver (recovered via git) —
  `git show d6df665:scripts/pmvier_browser.py` in the `playmoleculeAI` repo.
- Reference Playwright pattern —
  `acellera/playmolecule-tests/tests/auth.setup.ts` and
  `acellera/playmolecule-tests/tests/agent-search-moleculekit.spec.ts`.
- Trace DB schema —
  `playmoleculeAI/playmoleculeai/apps/agent/models/tables.py`.
- Trace read patterns —
  `/fast_shared/users/carles/data/playmoleculeAIdata/dashboard/backend/store_*.py`.
- Skills —
  `/fast_shared/users/carles/repos/acellera/playmoleculeAI/skills/` and
  `/fast_shared/users/carles/repos/acellera/acellera-skills/skills/`.
