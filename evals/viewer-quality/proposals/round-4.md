# Round 4

Status: applied (uncommitted), run and reviewed: 8.3 / 10 (`viewer-quality-train-20261009-181219`).

Round 3 scored 7.1 / 10 (7.6 without labels-6lu7, which OpenAI stopped). A fault in the eval broke the 3 cases
with files; change 1 fixes it.

| Change | Round 3 cases it fixes | Where | State |
|---|---|---|---|
| 1. The trial project in the project list | deepsite, poses, compare-vrk | `docker/viewer/server.py`, `tests/test_viewer_server.py` | applied, tested |
| 2. Camera: no `lig - pocket` example, a 2 Å margin | interface, pocket-1m17, compare-vrk | skill `SKILL.md`; PMView `updateVisualization.ts` | applied, tested |
| 3. A surface behind the subject | surface | skill `SKILL.md` | applied, tested |
| 4. Readable labels, in the user's numbering | slide, resistance | skill `SKILL.md`, `representations.md` | applied, tested |
| 5. `pmv.camera_zoom(distance)` | chains, covalent | PMView `utils.py` | applied, tested |
| 6. The labels case on a human protein | labels-6lu7 | `cases/vq-labels-3hs4/`, `train.yaml`, README | applied |

## 1. The trial project in the project list

All `pmview_load` calls of round 3 failed: `Could not fetch file carles-project/7Y5K_prepared.pdb`. Rounds 1 and 2
used the site's PMView and had no such error.

The sidecar shows the trial files as project `app` (cookie `PM_PROJECT=app`, route `/v3/file/app/...`). Our build
(PMView main 2d6c8c4) checks the saved project against the account's project list, `/v3/prefixes`
(`fileBrowser.store.ts`, `projectExists`, from commit 35e3780 "page refresh keeps project"). `app` is not in that
list, so PMView opens the default project `carles-project`. PMView puts its project in front of each file path
(`cleanFilePath`), and the sidecar sends a project that is not `app` to the site. The deployed site does not check.

Effect: deepsite drew the map as spheres from a PDB that it wrote by hand (4 / 10). Poses took 1IEP from RCSB, which
has other coordinates than the poses: the closest pose was 11.9 Å from the crystal ligand (7 / 10, "bad view").
Compare-vrk aligned in Python (9 / 10).

The sidecar adds the trial projects to the list:

```python
# docker/viewer/server.py
async def project_list(route) -> None:
    """Playwright route for /v3/prefixes, the account's projects: the site's list and the trial projects.
    PMView opens the account's default project when its project is not in this list."""
    response = await route.fetch()
    if not response.ok:
        return await route.fulfill(response=response)
    projects = await response.json()
    trial = [p.name for p in FILES.iterdir() if p.is_dir() and p.name not in projects]
    await route.fulfill(response=response, json=projects + trial)

# Browser._start, next to the /v3/file/ route
        await self.context.route("**/v3/prefixes", project_list)
```

`tests/test_viewer_server.py` gets `test_project_list`: a fake site list, the trial project added once, a site error
passed on.

Test on this host (our build, `VIEWER_PRELOAD='{"files": ["3PTB.pdb"]}'`, `3PTB.pdb` in `app/`):

| Sidecar | `/open?project=app` |
|---|---|
| as in round 3 | 503: `preload ['3PTB.pdb']: Could not fetch file carles-project/3PTB.pdb` |
| with `project_list` | ready; `preloaded 3PTB.pdb`; the site list has 781 projects, `app` added |

## 2. Camera: no `lig - pocket` example, a 2 Å margin

`direction` (round 3) gave about +1 point in all. In the cases where the agent used it, the camera lines of the
rubric changed so:

| Case | Camera line | Round 2 → 3 | Points |
|---|---|---|---|
| covalent-6oim | ligand and Cys12 in the center, nothing in front | fail → pass | +3 (the prompt also changed) |
| resistance-1m17 | nothing in front of the space between Thr790 and the ligand | fail → pass | +1 |
| interface-1n8z | the interface in the center and zoomed | pass → fail | -3 |
| hbonds-1iep | imatinib fully visible | fail → fail | 0 |
| pocket-1hsg, slide-3ptb, poses-1iep | the camera lines | pass → pass | 0 |

The skill example `direction=lig - pocket` caused the interface loss: the agent used the vector from HER2 to the
Fab, and the camera on the Fab side shows the Fab in front of the interface. `direction` and `camera_turn` stay; the
example goes, and no new camera call comes in.

`SKILL.md`, the section "Camera":

```diff
 - `pmv.camera_zoom(distance)` moves the camera along the line of sight, in Å: away when positive, closer when negative.
 
-A ligand in a pocket shows best from the open side of the pocket:
-
-```python
-lig = mol.coords[mol.atomselect('resname MK1'), :, 0].mean(0)
-pocket = mol.coords[mol.atomselect('protein and within 8 of resname MK1'), :, 0].mean(0)
-mol.focus('resname MK1', direction=lig - pocket)
-```
-
 Adding or removing a molecule resets the camera to the whole scene. A camera set before the scene is complete is lost.
```

The margin: 10 of 14 agents moved the camera closer after `mol.focus` (`camera_zoom` from -1 to -45 Å), and
pocket-1m17 and compare-vrk lost the zoom line of the rubric. `mol.focus` keeps 4 Å around the selection, the
default of Mol*. Change it to 2 Å:

```diff
 // src/molkitstar-ui/PyodideTerminal/updateVisualization.ts, focusCamera
-  const radius = Math.max(sphere.radius + 4, 5);
+  const radius = Math.max(sphere.radius + 2, 5);
```

## 3. A surface behind the subject

surface-1a52 scored 5 or 6 in all four rounds. The agent draws the pocket as a surface around estradiol. An opaque
surface hides the ligand; in round 3 the agent made it transparent (opacity 0.12), and then the surface shows no
shape. The usual figure cuts the surface away on the camera side.

`SKILL.md`, a new line in "A good view":

````markdown
- A surface around the subject hides it from every side, and a transparent one loses the shape it should show. Draw the surface only of the atoms behind the subject, as the camera sees it:

  ```python
  d = np.array([0, 0, 1.0])  # the side the camera looks from
  mol.focus('resname EST', direction=d)
  center = mol.coords[mol.atomselect('resname EST'), :, 0].mean(0)
  pocket = mol.atomselect('protein and same residue as (within 6 of resname EST)')
  behind = np.where(pocket & ((mol.coords[:, :, 0] - center) @ d < 0))[0]
  mol.reps.add('index ' + ' '.join(map(str, behind)), 'Surf')
  ```
````

## 4. Readable labels, in the user's numbering

- slide-3ptb: the agent drew the Asp189 label with `label_style={'bg_opacity': 0.0, 'border_width': 0}`. The text
  then lies on the atoms, and you could not read it.
- resistance-1m17: you asked about Thr790; the label says THR 766, the number in the file. The text answer says
  that 766 is 790, but a label can only show the numbers of the molecule.

`references/representations.md`, section "Labels":

```diff
 - `label_style` sets the border, background and offset (see the docstring).
+- Text needs contrast with what is behind it. The label background gives it: a label with `bg_opacity=0` is hard to read over atoms.
```

`SKILL.md`, "A good view":

```diff
-- Files often number residues differently from the literature. Labels and text use the numbering of the user, and say when the file differs.
+- Files often number residues differently from the literature. Labels and text use the numbering of the user, and say when the file differs. A label shows the numbers of the molecule: to label in the user's numbering, change `mol.resid` before `mol.view`, then select with the new numbers.
```

## 5. `pmv.camera_zoom(distance)`

The skill writes `pmv.camera_zoom(distance)`, and the value is a distance in Å. PMView names the argument `factor`,
and `help` shows no docstring. `camera_zoom(distance=-4)` raised `TypeError` in chains and covalent.

```diff
-def _camera_zoom(factor, smooth=False):
-    if not isinstance(factor, (int, float)):
-        raise TypeError(f"'factor' must be a number, got {type(factor).__name__}")
+def _camera_zoom(distance, smooth=False):
+    """Move the camera along the line of sight by ``distance`` Å: away from the
+    center when positive, closer when negative."""
+    try:
+        distance = float(distance)
+    except (TypeError, ValueError):
+        raise TypeError(f"'distance' must be a number of Å, got {distance!r}") from None
     if not isinstance(smooth, bool):
         raise TypeError(f"'smooth' must be a boolean, got {type(smooth).__name__}")
     act_id = "camera"
-    _queue_viz_update(act_id, {"action": "camera_zoom", "data": {"factor": factor, "smooth": smooth}})
+    _queue_viz_update(act_id, {"action": "camera_zoom", "data": {"factor": distance, "smooth": smooth}})
```

No caller passes `factor=` (playmoleculeAI, acellera-skills).

The other API errors of round 3 get no change. Each cost one call, and the agent went on:

| Error | Cases | Why no change |
|---|---|---|
| `len(mol.reps)` | 4 | moleculekit's class; PMView adds no methods to it. The skill says `mol.reps` is not a list. |
| `import scipy` | 3 | Pyodide does not load scipy. The skill lists what the page has. |
| `label_fields='resname resid'` | 2 | moleculekit splits the string into letters before PMView sees it. PMView's error lists the fields. |
| a mask as selection | 1 | PMView's error says a string is needed. |

## 6. The labels case on a human protein

OpenAI stopped vq-labels-6lu7 (SARS-CoV-2 main protease) with `bio_policy` in rounds 1 and 3. The case measures
labels on a pocket, so the protein can change. 3HS4 is human carbonic anhydrase II with acetazolamide: AZM 701
binds the zinc and touches 11 residues (Gln92, His94, His96, His119, Val121, Phe131, Val143, Leu198, Thr199,
Thr200, Trp209). AZM 702 is a second copy on the surface, 17 Å from the zinc.

`cases/vq-labels-6lu7/` becomes `cases/vq-labels-3hs4/` (`task.toml` name `acellera/vq-labels-3hs4`;
`train.yaml` and the README case table follow).

```text
# instruction.md
Use the viewer. Load 3HS4. Label the residues that touch the acetazolamide bound to the zinc. Keep the labels readable.

# tests/rubric.txt
1 The acetazolamide on the zinc (AZM 701) is visible in the pocket.
4 The contact residues show as sticks, with one label each.
3 The labels are readable: they do not overlap each other or cover the inhibitor.
1 The view is zoomed on the binding site.
1 Waters are hidden.
```

Its scores are not comparable with labels-6lu7.

## Test

This repo: 35 tests pass (new: `test_project_list`), lint is clean. PMView: `npm run build` (`index-BwMZ1rxL.js`),
Prettier clean, no type errors and no new eslint errors in `updateVisualization.ts`.

Host sidecar (`docker/viewer/server.py` of this repo, the new build, project `app`):

| Check | Result |
|---|---|
| `/open` with `VIEWER_PRELOAD='{"files": ["3PTB.pdb"]}'` | ready, `preloaded 3PTB.pdb` |
| `help(pmv.camera_zoom)`; `camera_zoom('x')`; `camera_zoom(distance=-5)`, `camera_zoom(np.float32(3))` | the docstring; `TypeError: 'distance' must be a number of Å, got 'x'`; both work |
| 1M17: `mol.resid[mol.chain == 'A'] += 24` before `mol.view`, a label on `name CA and resid 790` | the label reads THR 790 |
| `mol.focus('resname AQ4 or resid 790')` with the 2 Å margin | erlotinib and Thr790 fill about 40 % of the view height |
| 1A52: the surface example of change 3 (102 of 196 pocket atoms behind estradiol) | a cup behind the ligand; nothing covers estradiol |

## Run

As slurmweb:

```bash
make image && make viewer                           # the skill, and the PMView build
make run JOB=evals/viewer-quality/train.yaml        # round 4: about $0.4
```

## Result

Run `viewer-quality-train-20261009-181219`: 15/15, $0.33, 30 min, no OpenAI stop. Reviewed
(`ratings/viewer-quality-train-20261009-181219.json`): mean 8.3 / 10. On the 14 cases of round 3 (without the labels
case): 8.2, from 7.6.

| Case | Round 3 | Round 4 | Your note |
|---|---|---|---|
| chains-4hhb | 6 | 6 | big dots (Fe as `VDW`, size 1.35, then 0.55) |
| cleanup-1jpz | 10 | 9 | |
| compare-vrk | 9 | 10 | colours chosen at random; the default colours were simpler |
| covalent-6oim | 9 | 8 | |
| deepsite-7y5k | 4 | 4 | the TOP label |
| glycans-6vxx | 9 | 10 | why is the protein not more opaque |
| hbonds-1iep | 8 | 9 | the rotation |
| interface-1n8z | 5 | 6 | |
| labels-3hs4 | | 10 | the zinc ball too big (`VDW`, size 0.8, then 0.4) |
| pocket-1hsg | 10 | 5 | |
| pocket-1m17 | 8 | 10 | |
| poses-1iep | 7 | 10 | |
| resistance-1m17 | 7 | 10 | still cluttered by the white sticks |
| slide-3ptb | 8 | 8 | the ASP 189 label: nobody asked for it |
| surface-1a52 | 6 | 10 | a bit from the side |

The rubric lines that each change aims at, round 3 → round 4:

| Change | Lines | Points |
|---|---|---|
| 1. Trial project | poses: the crystal ligand stands out, fail → pass. `pmview_load` worked in the 4 cases with files. deepsite: the map line still fails (the agent showed only the top pocket, isovalue 0.99). | +3 |
| 2. Camera | zoom lines fail → pass in compare-vrk (1) and pocket-1m17 (2); hbonds: imatinib fully visible fail → pass (2), zoomed and not crowded pass → fail (1); interface: center and zoom still fail (the agent moved the camera 24 Å back after `mol.focus`); pocket-1hsg: center and close pass → fail (5: 30 residues as sticks in front of MK1, focus on `within 7 of resname MK1`) | -1 |
| 3. Surface behind | surface: the pocket shape fail → pass (the agent used the example) | +4 |
| 4. Labels | resistance: Thr790 easy to find fail → pass (THR 790, in your numbering); covalent: no label, a readable ligand colour pass → fail (an unasked CYS 12 label); slide: clean still fails (an unasked ASP 189 label) | +2 |
| 5. `camera_zoom(distance)` | no `TypeError` (2 in round 3) | 0 |
| 6. Labels case | labels-3hs4: 10 | |

Other changes: glycans +1 (protein muted), cleanup -1 (the heme in one colour hides the iron), interface +1
(glycans do not cover the interface).

Errors in the viewer: 4 mask selections refused (deepsite 1, surface 3), `len(mol)` 2, focus before `mol.view` 1,
agent code 3. In surface-1a52 the first refused mask stayed in the held representations and failed the next two
calls; the agent then spent 9 calls on `inspect.getsource` of PMView.
