---
name: eval-authoring
description: Author programmatic eval cases for the playmoleculeai-evals repo (cases.yaml, checks.py, fixtures, dev scripts) grounded in real agent traces. Use whenever the user is adding, designing, drafting, refining, or grading an eval case in this project, including phrases like "new eval", "add a case", "wire up a case", "design a test for chat N", any case-id like `xxx-NNNN`, or work touching cases.yaml, checks.py, the RunArtifact API, or the development/dump_chat_*.py / test_case_*.py dev scripts. Invoke this skill before reading checks.py or starting a new case.
---

# Eval authoring for playmoleculeai-evals

## Mission

Evals here measure whether the agent does the right thing, not whether it passes. When a model passes by doing something subtly wrong, the check is broken: tighten the check, do not loosen the prompt. Source every case from a real user task (typically a chat in the open agent.db) so the eval reflects work users actually do, and shape the grading so that real failure modes are caught.

What counts as "in scope" depends on the eval set, not on the skill. Each set under `eval_sets/` defines its own category and policy (which tools the agent may use, what artifacts get graded). Respect the per-set scope; if a case does not fit, propose a viewer-only or category-appropriate equivalent or move it to a different set.

## Architecture in 30 seconds

A case lives in `eval_sets/<set>/cases.yaml`. The runner spins up a browser-driven playmoleculeAI agent for the case's `prompt`, optionally pre-loading PDB IDs / fixture files / project files from `preload`, then captures artifacts: `final_answer.md`, `trace.json`, `screenshot.png`, `viewer_state.json` and `viewer_selection.json` (when the viewer is used), `systems/` (exported viewer state, including any post-run coordinate transforms the agent applied), and `metrics.json`.

Grading runs `python_check` assertions: each entry under `assertions:` names a function that the runner resolves by import name from `checks.py` of the same set. The function takes `(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult` and is the only assertion type the framework supports today. `RunArtifact` (in `src/pmai_evals/runner/artifacts.py`) exposes `final_answer()`, `viewer_state()`, `viewer_selection()`, `load_system(name)` (returns a moleculekit `Molecule` reading the post-run exported file), `system_files()`, etc. An optional LLM-judge `rubric` block grades subjective dimensions; default to disabling it (`rubric: { enabled: false }`) unless the case is genuinely about subjective quality.

CLI surface: `pmai-evals run -e <set> -m <model>` runs cases; `pmai-evals grade <run-id>` re-grades; `pmai-evals report <run-id>` summarises. Local sanity check after any change: `uv run pytest eval_sets/<set>/ tests/ --ignore=tests/test_session_auth.py -q`.

## Workflow for a new case

1. **Source the intent.** Copy `development/dump_chat_<N>.py`, change `CHAT_ID` and `OUT`, run it. Read the user's prompt, the agent's tool calls, and any failure modes in the trace. Original prompts are often messy (typos, ratio ambiguity, code-mixing); polish but preserve the intellectual challenge that motivated the original task. Cases can also come from category gaps the user wants covered, not only from chats.

2. **Confirm the case fits the set's scope.** Each eval set has a policy. If the source chat exercises a workflow outside that policy, propose an in-scope reframe before designing grading.

3. **Propose the design before editing.** Lay out the polished prompt, the grading signals you intend to capture, the source of truth (which file or computation produces the expected answer), and any open tradeoffs (tolerance bands, what counts as "correct"). High-uncertainty design choices benefit from user input before code commitment; resist the urge to land code while a framing question is unresolved.

4. **Derive ground truth deterministically.** Add `development/test_case_<N>.py` that loads the relevant inputs and prints the truth (residue sets, atom indices, distances, counts, whatever the check needs). Bake the printed values into `checks.py` constants prefixed with the case id (e.g. `_<ID>_*`). Mention the dev script in a comment so the constants are re-derivable when source data changes.

5. **Wire the case.** Add the entry to `cases.yaml`. Add the python_check function to `checks.py`. Add any local files to `fixtures/`. Reuse the shared helpers at the top of `checks.py`; if a pattern repeats across cases, hoist it.

6. **Verify locally.** Run pytest. Tests should still pass.

7. **Run against a real model and inspect.** Look at the latest run in `runs/`: `grade.json`, `screenshot.png`, `trace.json`, `viewer_state.json`, `viewer_selection.json`, the exported systems. Two failure modes need different responses: if a model passes a check that should fail, the check is too lenient — tighten it. If a model fails a check that should pass, look at the artifacts and decide whether the prompt was unclear, the truth was wrong, or the metric was the wrong choice for the kind of variation you want to tolerate.

## Bootstrapping a new eval set

Create `eval_sets/<set>/` with `cases.yaml` (start with `cases: []`), `checks.py` (with the imports `from pmai_evals.grading.assertions import PYTHON_CHECK_TYPE`, `from pmai_evals.runner.artifacts import RunArtifact`, `from pmai_evals.schemas import AssertionResult`), and `fixtures/`. Copy the shared-helpers section from a comparable existing set as a starting point and prune what does not apply. Add the set to whatever registration mechanism the runner uses (currently auto-discovered by directory). Document the set's scope policy in a short comment at the top of `cases.yaml` so future authors know what belongs and what does not.

## Prompt design

The prompt is half the eval. Strip ambiguity in the directions the grader cares about:

- Specify formats the grader expects: hex colors when colors matter (`#0000FF`), chain letters when chains matter, residue numbering, units.
- For numeric answers, require an `<answer>X.XX</answer>` tag and show one example value with the right precision; the grader extracts via regex.
- Express ratios in both directions to defeat reversal errors: "10 X for every 1 Y" beats "1/0.1".
- When the prompt asks the agent to load something, do not also pre-load it; loading is part of the task.
- When grading reads from a particular artifact (e.g., a viewer selection vs a representation), nudge the agent toward producing it ("highlight using a viewer selection", "report the answer in `<answer>...</answer>` tags").

Preserve the failure mode worth catching. If the source chat shows a real model error (ratio reversed, wrong chain, wrong domain), keep the prompt phrased so that error remains possible, then make the check catch it.

## Grading patterns

The general principle is to choose a metric that is robust to acceptable variation and discriminating against real failure modes. Some recurring shapes:

- **Numeric answer with tolerance.** Extract via the shared `<answer>` regex helper, compare with a tight tolerance reflecting the question's precision.
- **Set equality / containment.** When the truth is "exactly these residues / atoms / chains", build a Python set in the dev script, bake it as a constant, compare on the run. For lenient versions, switch to subset / superset checks.
- **Mask comparison.** When the truth is at atom granularity, use `numpy.array_equal` on the atom mask returned by the structure library against the truth mask built from a ground-truth selection string. Sharper than residue sets when the prompt is about atoms.
- **Boundary-band slack.** When the prompt names a cutoff (any "within X of Y" task), derive two sets in the dev script: definitely-inside (≤ X − ε) and definitely-outside (> X + ε). Require all definitely-inside in the agent's output and all definitely-outside absent. Borderline elements between the bands are not graded; this absorbs floating-point and selection-grammar drift without false negatives.
- **Robust geometric metrics.** Pick a metric that does not lie when the inputs differ in shape. Centroid distance is fragile when subset compositions differ across structures (a dimer-vs-monomer comparison shows tens of Å of centroid drift even after a perfect alignment). For superposition-quality checks, median nearest-neighbour distance over the aligned subset is far more robust: it stays in single-digit Å for good alignments and explodes for bad ones, regardless of how many extra atoms either side has.
- **Composite signals.** When a case requires several conditions (e.g., right structure visible AND right colors AND aligned), return a single `AssertionResult` whose evidence joins the per-signal reports with `;`. Splitting into multiple python_check entries makes failure attribution easier but inflates the assertion count; choose based on whether each signal is independently meaningful.

If the structure library is moleculekit, the selection grammar (`protein and name CA and chain A`, `same residue as within 5 of (chain B)`, `index 1 2 5 to 10`, `noh`, etc.) is what both the agent's `viewer_select` writes and the dev scripts use to bake truth. Read moleculekit docs for the full grammar; the index-list form is what `viewer_select(..., mode='set')` produces.

## When to use rubric grading

Default to python_check. Rubric grading exists for cases where correctness genuinely requires human-style judgement (writing quality, design choice rationale) and no deterministic check can stand in. If you find yourself reaching for a rubric because writing the check is hard, that is usually a sign the prompt is under-specified. Tighten the prompt or the truth-derivation first; reach for the rubric last.

## Conventions

- **Case ID**: each set picks a stable prefix (look at the existing `id:` values in `cases.yaml`). Constants for one case live in `checks.py` prefixed with the upper-cased id, separated from other cases by a banner comment.
- **`cases.yaml` fields per case**: `id`, `difficulty` (`easy` / `medium` / `hard`, anchored to the set's existing distribution), `prompt` (block scalar, multi-line), `tags` (free-form descriptive list, mirror what other cases use in the same set), `timeout_s` (a reasonable upper bound for the case length), optional `preload` (`viewer.pdb_ids`, `viewer.files`, `project.files`), `assertions` (list of `{type: python_check, function: <name>}`), `rubric` (`{enabled: false}` unless the case truly needs a judge).
- **Dev scripts**: one `development/test_case_<N>.py` per case. Each is self-contained, runnable with `uv run python development/test_case_<N>.py`, and prints the values that ended up in `checks.py`. Re-run when source data changes.
- **`checks.py` organisation**: shared helpers at the top in a stable order (constants → result helpers → answer parsing → system lookup → selection resolvers → set/mask helpers → set-specific geometry helpers), then per-case sections in roughly id-sorted order, separated by banner comments. Read the top of the file before adding a helper; reuse beats re-implement.
- **Function signature**: `def <id>_what_is_checked(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult`. `config` is unused but required; Pyright will warn on every check function and the warning is expected.

## Engineering principles

- **Propose before editing.** Design choices have tradeoffs the user often wants to weigh. Surface the tradeoff in prose, get a decision, then write code. A diff that lands during a framing discussion gets reverted.
- **Never tune a check to make a failing model pass.** Tune the check to grade correctly; failures from real model errors are the eval working as intended. Cite the specific behaviour you observed before changing thresholds.
- **Do not chase the original chat's exact files.** If the source chat used files the user has not provided, design the eval first, then provision data: a comparable public structure, or a small fixture deterministically generated by a dev script.
- **Visual messiness is not a metric failure.** A screenshot can look chaotic for reasons unrelated to grading correctness (extra subunits, conformational diversity, loose lipid tails). When the metric says "passed" but the screenshot looks wrong, address the visual by tightening the prompt's filter or the case's preload, not by changing the metric.
- **Choose robustness over cleverness.** Prefer the grading metric that fails clearly when the agent is wrong and stays quiet when the agent picks an acceptable variation. Color-by-hex equality is brittle (`#0000FF` vs `#004CFF`); selection-by-set is robust. Centroid distance is brittle to composition mismatch; nearest-neighbour distance is robust.

## Pointers, not enumerations

The shared helpers, the existing case patterns, and the moleculekit selection grammar all exist as readable code or upstream documentation. Rather than restate them here (where they would go stale), look in:

- `eval_sets/<set>/checks.py` top-of-file: the shared helper roster for that set, in canonical order.
- `eval_sets/<set>/cases.yaml`: existing prompts, preload patterns, difficulty/tag conventions.
- `src/pmai_evals/runner/artifacts.py`: the full `RunArtifact` API.
- `src/pmai_evals/grading/assertions.py`: how python_check resolves and what the function signature must satisfy.
- `src/pmai_evals/schemas.py`: the case-config schema (what fields `cases.yaml` accepts).
- `src/pmai_evals/browser/observers.py` and `chat.py`: what gets captured into `viewer_state.json` / `viewer_selection.json`. Read these only when extending the artifact stream.

When picking a grading approach for a new case, find the closest existing case in the same set and adapt; the helpers it uses are usually the right starting point.
