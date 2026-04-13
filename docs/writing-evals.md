# Writing evals

How to add a new eval set or a new case to an existing one. No harness
code changes are needed for a typical eval — it's all YAML and a few
fixture files.

Read [`how-it-works.md`](how-it-works.md) first if you haven't. The
mental model there — runner collects artifacts, grader scores them with
two independent pipes — is assumed below.

## Anatomy of an eval set

```
eval_sets/<eval-set-id>/
├── eval_set.yaml       # metadata + default timeout, default rubric path
├── cases.yaml          # list of cases (one entry = one prompt)
├── rubric.yaml         # default LLM-judge rubric (the machine-readable one)
├── rubric.md           # same rubric in prose, for humans
└── fixtures/           # files a case may upload into the workspace
    └── ligand.sdf
```

All files are YAML or markdown. Cases are data, not code.

### `eval_set.yaml`

Top-level metadata for the whole set:

```yaml
id: molecular-visualization          # must match the directory name
skill_under_test: pmview              # which agent skill this exercises
description: |
  Basic molecular viewer operations — load PDBs, select residues,
  measure distances.
difficulty: mixed                     # trivial | easy | medium | hard | mixed
requires_browser: true                # always true for now
default_timeout_s: 300                # per-case default; cases can override
default_expected_cost_usd: 0.05       # used by the budget for dry-run estimates
rubric_path: rubric.md                # judge reads the .yaml sibling
tags: [viewer, visualization, pilot]
```

### `cases.yaml`

A list under `cases:`. One entry is one prompt the agent will run.
Minimum viable case:

```yaml
cases:
  - id: load-1crn
    difficulty: trivial
    prompt: "Load the PDB entry 1CRN on the viewer."
    tags: [load]
    assertions:
      - type: tool_called
        name: pmview_load
      - type: viewer_has_molecule
        identifier: "1CRN"
      - type: no_tool_error
    rubric:
      enabled: false
```

Fields:

| Field | Required | Notes |
|---|---|---|
| `id` | yes | Stable, kebab-case. Referenced by CLI filters. |
| `prompt` | yes | Exactly what gets typed into the chat box. |
| `difficulty` | no | `trivial` / `easy` / `medium` / `hard`. |
| `tags` | no | Free-form; the report slices by these. |
| `fixtures` | no | List of filenames under `fixtures/` to upload before prompting. |
| `timeout_s` | no | Overrides `default_timeout_s`. |
| `expected_cost_usd` | no | Used by budget pre-checks. |
| `assertions` | no | Deterministic checks (see below). |
| `rubric` | no | LLM-judge config for this case. |

Omitting `assertions` and disabling `rubric` gives you a case the
runner will execute but nothing will score — useful for smoke tests.

## Assertions

Every assertion has a `type:` field. Everything else is its config.
Results land in `grade.json` with a one-line evidence string that shows
up in the HTML report.

### Text assertions (operate on `final_answer.md`)

```yaml
- type: output_contains
  value: "Cn1cnc2c1c(=O)n(c(=O)n2C)C"
  case_sensitive: true                # default false

- type: output_matches_regex
  pattern: "(?i)rmsd\\s*[:=]?\\s*\\d+(?:\\.\\d+)?"
  ignore_case: false                  # default false; (?i) in pattern also works

- type: output_numeric_close
  value: 25.0                         # target number
  tolerance: 5.0                      # default 0.1
  pattern: "-?\\d+(?:\\.\\d+)?"       # optional; default matches any number
```

`output_numeric_close` extracts all numbers from the answer and passes
if any is within `tolerance` of `value`. Good for distances, RMSDs,
counts where the agent phrases the answer freely.

### Tool-call assertions (operate on `trace.json → tool_calls`)

```yaml
- type: tool_called
  name: pmview_load                   # at least once

- type: tool_called_with
  name: pmview_load
  arguments:                          # all listed keys must match exactly
    pdb_id: "1CRN"

- type: tool_call_count
  name: pmview_load                   # omit to count any tool
  op: ">="                            # ==, !=, >, >=, <, <=
  value: 2

- type: tool_call_order
  order: [pmview_load, pmview_select, pmview_color]
  # Checks that `order` is a subsequence of the observed call names.
  # Other calls between them are allowed.

- type: no_tool_error
  # Passes iff no tool call has is_error / error set.
```

### Viewer-state assertions (operate on `viewer_state.json`)

`viewer_state.json` is the Pyodide-side `systems_tree` dumped as JSON.
These assertions walk it as a nested dict.

```yaml
- type: viewer_has_molecule
  identifier: "1CRN"                  # substring match against any string leaf

- type: viewer_has_residue
  name: "HEM"

- type: viewer_representation_is
  representation: cartoon             # matches any value under a "representation" key

- type: viewer_color_scheme_is
  scheme: chain                       # matches any value under a "color" key

- type: viewer_system_count
  op: ">="
  value: 2
```

The viewer assertions are deliberately loose: they match substrings in
string leaves of the tree. That's fine for "is 1CRN loaded" but won't
catch fine-grained state. Reach for the rubric instead if you need to
judge *how* something is rendered.

### File assertions

If a case produces a downloadable file (a report, a CSV), you can
write it into the cell directory and assert on it:

```yaml
- type: file_exists
  name: report.csv

- type: file_content_matches
  name: report.csv
  pattern: "resolution,\\s*1\\.\\d"
```

## Rubrics

The LLM judge reads the rubric, scores each dimension 1–5, and passes
the case iff the mean is at least `pass_threshold`.

### Default rubric (`rubric.yaml`)

```yaml
dimensions:
  - name: correctness
    question: |
      Does the response correctly answer the prompt? Are factual claims
      (PDB IDs, residues, distances, SMILES, RMSD) accurate?
    scale: [1, 5]
  - name: visualization_quality
    question: |
      Is the viewer state appropriate for the question? Is the camera
      positioned to make the relevant structure clearly visible?
    scale: [1, 5]
  - name: communication
    question: |
      Is the final answer clear, concise, and free of hedging?
    scale: [1, 5]
pass_threshold: 3.5
```

Keep questions short and load-bearing. The judge is good at answering
what you actually ask; it's bad at inferring what you meant.

### Per-case overrides

Under `cases.yaml` each case can opt in, opt out, or replace the
dimensions entirely:

```yaml
# Opt out: assertions alone are enough.
rubric:
  enabled: false

# Opt in with defaults (inherits from the eval set's rubric.yaml).
rubric:
  enabled: true

# Opt in with bespoke dimensions for this case.
rubric:
  enabled: true
  dimensions:
    - name: visualization_quality
      question: |
        Does the screenshot clearly show the dimer interface — both
        chains visible, the interface roughly centered, no occlusion?
    - name: correctness
      question: "Did the assistant identify the real interface?"
```

The `pass_threshold` is always inherited from the eval-set rubric.
If you override dimensions, you're only replacing the questions, not
the threshold.

### When to use the rubric

Use the rubric when the answer is right or wrong *and a human would
have to look at it to tell*. "Is the camera framing the dimer",
"is the reasoning sound", "is the answer hedging" — LLM territory.
Don't use the rubric for things a regex can check; assertions are
free and deterministic.

## Workflow: adding a new case

1. Open `eval_sets/<set>/cases.yaml` and append a new entry.
2. Add any fixtures to `eval_sets/<set>/fixtures/`.
3. Dry-run to confirm the YAML parses and the case is in the matrix:
   ```bash
   uv run pmai-evals run --eval-set <set> --cases <new-id> --dry-run
   ```
4. Run it for real on the cheapest model:
   ```bash
   uv run pmai-evals run --eval-set <set> --cases <new-id> --tier cheap
   ```
5. Inspect the cell directory under `runs/<run_id>/<new-id>/...`.
   Look at `trace.json`, `viewer_state.json`, and `screenshot.png`
   to confirm the agent did what you expected.
6. Grade and report:
   ```bash
   uv run pmai-evals grade  <run_id>
   uv run pmai-evals report <run_id>
   ```
7. If an assertion fires for the wrong reason or the rubric is
   non-discriminating, iterate on the YAML and re-grade with
   `--force`. You do not need to re-run the agent.

## Adding a new eval set

Same as above, but start by copying `eval_sets/molecular-visualization/`
to `eval_sets/<new-id>/` and editing the metadata. The directory name
must match `id:` in `eval_set.yaml`. Everything else — judge, runner,
reporter — picks the new set up automatically.

## Adding a new assertion type

Only needed if none of the existing types fit. One function plus one
line in `ASSERTION_REGISTRY` in `src/pmai_evals/grading/assertions.py`:

```python
def check_my_thing(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    target = _need(config, "target")
    # ... read artifact.trace() / artifact.viewer_state() / artifact.final_answer()
    return _result(
        "my_thing",
        passed=...,
        evidence="human-readable one-liner",
        config=config,
    )

ASSERTION_REGISTRY["my_thing"] = check_my_thing
```

Add a test under `tests/test_assertions.py` that feeds it a synthetic
artifact and asserts the result. That's it — no other plumbing.

## Tips

- **Start deterministic, add the rubric last.** If a case can be
  graded by assertions alone, don't invite LLM noise into the loop.
- **One thing per assertion.** `output_contains "1.5 Å"` is clearer
  than one regex that encodes three conditions.
- **Tag aggressively.** The report slices by tag, so `[load, pdb]`
  on every load case gives you a "load success rate" panel for free.
- **Iterate on the YAML, not the run.** Grading is cheap and
  re-runnable; runs are not. If the agent's behaviour is what you
  wanted, fix the assertions and re-grade.
