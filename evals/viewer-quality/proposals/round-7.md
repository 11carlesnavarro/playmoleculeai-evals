# Round 7

Status: applied (uncommitted), run (`viewer-quality-train-20261014-115559`) and reviewed: mean 9.07. See Result.

The agent works the viewer as a person does: it acts, it sees what the user sees, and each control it needs is one
call. Python stays the way to act. Evidence: the round 6 traces (`round-6.md`, Result) and the dev, prod and open
chats (5,420 chats with viewer tools, 30,289 `pmview_run_python` calls).

## Round 6 causes

| Cause | Evidence | Change |
|---|---|---|
| A camera call in the same run as a new display is lost | 9 of 14 trials did it, 6 needed one more call; the skill line on it did not stop them | PMView: the camera call applies after the new display (Mol* resets the camera when the first representation commits). Remove the skill line |
| `mol.focus` clips the scene to the selection radius + 4 Å | deepsite: focus on one atom cut a hole in the pocket map (4 points); the agent called it "a hollow center" | focus docstring and skill: the view keeps only what is that close to the center |
| The look shows the 3D view when the user sees another tab | deepsite: loading `output.csv` opened the Tables tab, and the user ends on the table; the state and the image do not show it | PMView: the state names the tab that the user sees; `pmv.show_tab(name)` |
| Labels nobody asked for | 4 of 14 trials (round 5: 7); the agent reads "highlight", "clear" and "show how" as a request for names | `viewer.md`: a label only when the user's message asks for labels. Skill: remove "over the rest of the scene" (sticks cover the labels in 3 images) |
| The palette skill gives the viewer its slot 1 (#1151a0) | slide: dark blue on black in rounds 4, 5 and 6 ("I need to stick with that"); palette read in 5 trials; its own table gives viewer colours to pmview | palette `SKILL.md`: remove pmview from its consumers. `viewer.md`: remove the palette line |
| Wrong guesses about representations | `len(mol.reps)` 2 errors, `mol.reps._reps` 1; `filter` read as remove (hbonds); a thicker rep on the same atoms probably hid a colour change in 3 updates (covalent) | `mol.reps` gets `len` and indexing (remove "`mol.reps` is not a list"); skill: `filter` and `remove` in two rows; one line on overlapping reps |
| A provider stop scores 0 | glycans: OpenAI `bio_policy` before any viewer call | eval: run a trial with a provider error again; do not score it |

## Tools

| Now | Round 7 | Evidence |
|---|---|---|
| `pmview_run_python(code, include_screenshot)` | `pmview_python(code)`: a run that changes the view returns the new view (state and image) | round 6: the agent asks for the image on 92 of 113 changes; 14 runs change nothing and only ask for the image |
| none | `pmview_look()`: the state and the image; no code, no file | the same 14; chats: 966 of 2,547 `pmview_screenshot` calls are in chats where the user asks for no image or file, and each writes a file into the project |
| `pmview_load(files, include_screenshot)` | `pmview_load(files)`: returns the view and the Python handle of each new system | the result is only "Success"; chats: `pmv.get_system(id)` in 14,600 calls, "No system found with this id" 218 times |
| `pmview_load_job`, `pmview_save`, `pmview_screenshot` | no change | |

The names keep `pmview_`. PMAI sends PMView its own command names (`tools.py:48`), so the rename needs no PMView
change; the PMView chat shows the code of `pmview_run_python` calls (`ToolArgs.tsx:43`), and that line takes both
names. `pmview_look` uses the state and screenshot commands that PMView has (`pmview.py:30`).

## Python names

- `import pmv` works; `dir(pmv)` and `print(pmv)` list the calls (now `dir(pmv)` shows no call: hbonds, resistance); an
  unknown name raises an error that lists the real ones. Chats: `import pmv` failed 77 times, `import pmview` 73,
  `viewer` not defined 38; 770 names after `pmv.` that do not exist (`_t` 106, `systems` 68, `viewer_state` 53).
- `mol.view(name=...)` names the system. Now PMView drops the name: resistance used 6 calls to rename; 40 eval calls.
- `pmv.camera_zoom(distance)`, with `factor` as the old name.
- The tool says what the viewer's Python has: MoleculeKit, RDKit and NumPy, no SciPy, no sandbox files. Round 6: `scipy`
  not found in 4 trials (one through `mol.mutateResidue`).

## New viewer calls

| Call | Evidence | Mol* 3.43.1 |
|---|---|---|
| `Interactions` style: H-bonds, salt bridges and stacking as dashed lines | hbonds: a fake molecule for the lines in 7 of 7 runs (round 6: a copy of chain A with 6 fake bonds, 177 of 380 s) | `interactions` representation, registered |
| `pmv.visible(sel)`: the share of `sel` that the camera sees, and the residues in front | hidden subject: round 6 pocket-1m17 4, chains 4, covalent 3, labels-3hs4 1; round 5: 16 of 49 lost points | `canvas3d.identify` |
| `pmv.settings(background=, clip=)` | chats: `set_background`, `set_background_color`, `set_theme` 56 calls, "background" in 166 user messages; slide wanted white (step 55); deepsite clip | `canvas3d.setProps` |

Not now: play and pause, camera read and set, pick by pixel, measurements, groups, colour ranges, the selection unit,
panels, session export. No trace asks for them, or `visible` and `Interactions` cover them.

## Safety

The agent's Python runs in a Web Worker. It cannot reach the page or the rest of the app. It sends named actions
(`rep_add`, `camera_turn`, ...) that the page checks and applies; each new control is one more named action. No
action reaches projects, files, the account or sharing.

## Order

1. Round 6 causes, tools, Python names. Measure: calls and errors for each trial, labels, the deepsite and covalent
   lines. Compare minutes only with the same model speed (round 6 decoded at 82 tokens/s, round 5 at 109).
2. `Interactions`, `pmv.visible`, `pmv.settings`. Measure: the hbonds and hidden-subject lines.

Where: PMView worktree (`utils.py`, `pyjs.js`, `updateVisualization.ts`, `executePythonScript.ts`, `ToolArgs.tsx`,
the viewer state in `LLMChat/utils/utils.ts`), PMAI (`tools.py`, `pmview.py`, `viewer.md`), skills
(`pmview/SKILL.md`, `references/representations.md`, `palette/SKILL.md`), eval (provider errors).

## Applied

PMAI is now in the worktree `playmoleculeAI-2-viewer-quality` (Makefile `PMAI`).

- Tested on this host: the sidecar on port 8799 with the PMView build, 1IEP. `import pmv`, `print(pmv)`, an unknown
  name lists the calls; focus in the same run as a new display keeps the focus; `mol.view(name=)` names and renames;
  `len(mol.reps)`, `mol.reps[i]`; `camera_zoom(10)` and `factor=-10`; `settings(background='white', clip=False)`, a bad
  colour gives a note; a loaded CSV gives `shown_tabs: ['Tables']`, `show_tab('3D Viewer')` brings the view back;
  `Interactions` in kind colours and in one colour; `pmv.visible`.
- PMAI tools against this PMView: no image when the code changes nothing or only calls `pmv.visible`; an image when
  the view changes; `pmview_load` gives `1iep.pdb: pmv.get_system('<id>')`.
- Found in the test and fixed: an `Interactions` line counted as a cover; `pmv.visible` alone returned an image.
- Eval: OpenAI's `[LLM_FAILED]` stop is an `UnknownApiError`, and the job runs that trial once more.

Run, as slurmweb: `make image && make viewer && make run JOB=evals/viewer-quality/train.yaml` (about $0.4).

## Result

Mean 9.07 (round 6: 7.4, round 4: 8.33). 15/15 trials, no provider stop, $0.32. Agent time 3,989 s (round 6: 5,392 s);
slide gives 1,326 s of the difference, and the other 14 trials did the same work as in round 6.

- Better: covalent 0 → 10 (the bond is drawn), glycans 0 → 10 (no provider stop), chains 6 → 10, pocket-1m17 6 → 10,
  slide 8 → 10 (white background), compare 6 → 9 (no labels).
- Worse: labels-3hs4 9 → 7 (labels on the atoms), resistance 10 → 7 (a label nobody asked for, white text in a white
  outline), poses 10 → 7 (the grey crystal ligand does not stand out on white; pose colours from the palette skill).
- Same: deepsite 6. The agent cut a copy of the map to show the top pocket, so the view shows one pocket.
- Changes: images to the model 131 → 91, no screenshot calls; a camera call in the same code as a new display worked in
  all trials that made one; no guessed `pmv` names; hbonds drew `Interactions`, no fake molecule; labels nobody asked
  for in 2 of 14 trials (round 6: 4).
- Faults: `mol.view(name=..., hold=True)` loses the name (4 of 9 trials); a state read after a change in the same code
  gives the old state (13 times in 11 trials); `print(mol.reps[i])` gives an address (11 times in 10 trials);
  `Interactions` is not in the `reps.add` docstring. Causes and the next changes: `round-8.md`.
