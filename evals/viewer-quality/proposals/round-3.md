# Round 3

Status: done (uncommitted). Run `viewer-quality-train-20261009-165017`, reviewed: mean 7.1 / 10.

Round 2 scored 7.0 / 10. Three causes lost most points; changes 1 to 3 fix them. Change 4 fixes one prompt.

| Change | Round 2 cases it fixes | Where | State |
|---|---|---|---|
| 1. `size=1` draws the normal size | chains, compare-vrk, interface, pocket-1hsg, pocket-1m17, poses | PMView `utils.py`; skill `representations.md` | applied, tested |
| 2. Skill text for colour and labels | pocket-1hsg, pocket-1m17, labels-6lu7 | skill `SKILL.md` | applied |
| 3. Camera: set the direction, turn along the screen | covalent, hbonds, resistance, surface, slide | PMView `utils.py`, `pyjs.js`, `updateVisualization.ts`; skill `SKILL.md` | applied, tested |
| 4. Covalent prompt asks for the view | covalent | `cases/vq-covalent-6oim/instruction.md` | applied |
| Sidecar serves our PMView build | (needed for 1 and 3) | `docker/viewer/server.py`, `Makefile` | applied, tested |

PMView changes are in the worktree `pmview-viewer-quality` (branch viewer-quality, from main 2d6c8c4); `build/`
has all of them. The sidecar still opens the deployed site (backend, login) and serves only the PMView files
from that build. Users get changes 1 and 3 when the PMView team merges them. The skill text of 1 and 3 needs
these PMView changes.

## 1. Size

All 15 round 2 agents ran `print(mol.reps.add.__doc__)` and read this (MoleculeKit 1.17.3, the wheel in
PMView `public/static/assets/`, `moleculekit/representations.py` line 325):

```text
size : float
    Scales the drawn size: stick and sphere radius, surface probe, point
    size, label text. Each style keeps its own sensible size at 1.
```

So the agent writes `size=1` or a bit more. PMView sent `size` unchanged to Mol*, and Mol* draws sticks at
0.15. So `size=1` drew sticks 6.7 times too thick.

```python
mol.reps.add('resname MK1', 'licorice', size=1.0)
# moleculekit: size_factor = 1.0;  PMView: sizeFactor = 1.0;  Mol* default for sticks: 0.15
```

PMView now multiplies by the default of the style, and divides again for the viewer state:

```python
# public/static/assets/utils.py
_VIZ_DEFAULT_SIZE = {"ball-and-stick": 0.15, "cartoon": 0.2, "backbone": 0.2, "putty": 0.2, "line": 2.0,
                     "molecular-surface": 1.5, "gaussian-surface": 3.0, "point": 3.0}   # others: 1
data["sizeFactor"] = described["size_factor"] * _VIZ_DEFAULT_SIZE.get(style, 1)          # _rep_payload
nr["size"] = round(r["sizeFactor"] / _VIZ_DEFAULT_SIZE.get(r.get("type"), 1), 3)        # _format_representation
```

The size table in `references/representations.md` is now one paragraph: "`size` scales the normal size of the
style, and 1 is that normal size. For sticks it scales the atomic radii: 0.6 draws thin sticks, for many
molecules in a small space, such as poses in one pocket; 2 draws heavy sticks with ball-shaped atoms."

## 2. Skill text for colour and labels

Round 2: "Show me the binding-site residues" gives a label on each pocket residue, and the labels overlap.
Agents make the subject bigger to make it stand out. The short bold rules ("**Text is rare.**") did not
change this. The new section has no bold rules: each line says what to do and why.

`SKILL.md`, the full new section "A good view":

```markdown
## A good view

A good view shows the subject of the request at a glance.

- Atoms between the camera and the subject hide it: the cartoon of its own protein, side chains, waters, a
  second copy. Leave them out of the representations, draw them thin or transparent, or turn the camera.
- Focus on the subject, not on the whole molecule, so that it fills the view.
- Draw only the context that the request needs, thin, pale or transparent, so that the subject reads first.
- Give the subject a colour that nothing else in the view has. A bigger size does not help: thick sticks and
  spheres cover the atoms around them. The background is black: dark colours sink into it, light colours
  stand out.
- Name the residues in the text answer, for example "ASP25, GLY27, ASP29". A label in the view covers the atoms
  behind it, and labels in a pocket overlap. A label helps for one or two atoms that the user must find in
  the view, such as a mutated residue.
- `within` cuts residues at the distance; `same residue as (...)` keeps them whole.
- Files often number residues differently from the literature. Labels and text use the numbering of the
  user, and say when the file differs.
```

## 3. Camera

Round 2: the subject is hidden or seen from the side in 5 cases (about 10 points). The agent cannot choose
the side it looks from. `mol.focus` keeps the old direction. `pmv.camera_rotate` turns about the x, y and z
axes of the structure, which the agent cannot relate to the screen, and it keeps the old `up` vector, so the
picture can tilt.

A second fault, found in the test: a camera call after `mol.focus` in the same run is lost. `focusLoci`
applies on the next frame and overwrites it. On the site's PMView, `mol.focus('protein');
pmv.camera_rotate([0, 1, 0], 1.5708)` gives the same image as `mol.focus('protein')` alone.

Two new calls:

```python
mol.focus(sel, direction=[x, y, z])   # the camera is on this side of sel (a vector in structure coordinates)
pmv.camera_turn(right=30, up=15)      # move the camera around the center, to the right and up on the screen
```

PMView code:

```python
# public/static/assets/utils.py: pmv_focus checks direction (3 numbers, not all zero; NumPy arrays too)
_queue_viz_update(molId, {"action": "syst_focus", "data": {"indices": sel_idxs, "direction": direction}})

def _camera_turn(right=0, up=0):   # degrees
    _queue_viz_update("camera", {"action": "camera_turn", "data": {"right": right, "up": up}})
```

```js
// public/static/assets/pyjs.js
_api.camera_turn = _internal_py_utils._camera_turn
```

```ts
// src/molkitstar-ui/PyodideTerminal/updateVisualization.ts
// focusCamera replaces focusLoci for mol.focus: the same sphere (+4 Å, at least 5 Å), but the camera
// moves at once, so a camera call after it in the same run starts from the focused view
const radius = Math.max(sphere.radius + 4, 5);
if (!direction) return camera.setState(camera.getFocus(sphere.center, radius), 0);
const dir = Vec3.normalize(Vec3(), Vec3.negate(Vec3(), Vec3.ofArray(direction)));   // camera to subject
const up = Vec3.orthogonalize(Vec3(), dir, along ? forward : oldUp);   // looking along the old up: forward goes up
camera.setState(camera.getInvariantFocus(sphere.center, radius, up, dir), 0);

// turnCamera: rotate the position and the up vector about the screen axes
const screenUp = Vec3.orthogonalize(Vec3(), toCamera, oldUp);
Vec3.transformQuat(toCamera, toCamera, Quat.setAxisAngle(Quat(), screenUp, degToRad(right)));
const screenRight = Vec3.normalize(Vec3(), Vec3.cross(Vec3(), screenUp, toCamera));
const tilt = Quat.setAxisAngle(Quat(), screenRight, -degToRad(up));
Vec3.transformQuat(toCamera, toCamera, tilt);
Vec3.transformQuat(screenUp, screenUp, tilt);
camera.setState({ position: Vec3.add(Vec3(), target, toCamera), up: screenUp }, 0);
```

`mol.focus` from Python no longer animates (250 ms before). `pmv.camera_rotate` stays in PMView; the skill
no longer names it.

`SKILL.md`, the new section "Camera":

````markdown
## Camera

The camera looks at a center from one direction.

- `mol.focus(sel)` centers the selection and zooms until it fills the view. The direction stays.
- `mol.focus(sel, direction=[x, y, z])` also puts the camera on the `direction` side of the selection, a
  vector in structure coordinates.
- `pmv.camera_turn(right=30, up=15)` moves the camera around the center by degrees, to the right and up on
  the screen, so the view shows more of that side. Negative values move it left and down.
- `pmv.camera_zoom(distance)` moves the camera along the line of sight, in Å: away when positive, closer when
  negative.

A ligand in a pocket shows best from the open side of the pocket:

```python
lig = mol.coords[mol.atomselect('resname MK1'), :, 0].mean(0)
pocket = mol.coords[mol.atomselect('protein and within 8 of resname MK1'), :, 0].mean(0)
mol.focus('resname MK1', direction=lig - pocket)
```

Adding or removing a molecule resets the camera to the whole scene. A camera set before the scene is complete
is lost.
````

## 4. Covalent prompt

Rounds 1 and 2: the prompt asks for "a high-quality figure". The agent makes PNG files with another tool
(`6oim_sotorasib_pocket.png`) and gives the viewer little care, but the rubric grades the viewer. It is the
most expensive case: 88 calls, $0.12.

```diff
-Use the viewer. The viewer shows KRAS G12C with sotorasib (6OIM). I need a high-quality figure of the ligand in its pocket for a paper. The covalent bond to Cys12 must be clear.
+Use the viewer. The viewer shows KRAS G12C with sotorasib (6OIM). Set up the view of the ligand in its pocket, so I can use it as a figure for a paper. The covalent bond to Cys12 must be clear.
```

The score of this case is then not comparable with rounds 1 and 2.

## Test

`docker/viewer/server.py` on this host (Playwright 1.58, control on 127.0.0.1:8799), eval account, project
`app`, 1HSG. Red, green and blue spheres mark the residues with the largest x, y and z.

| Check | Our build | Site's PMView |
|---|---|---|
| The page comes from the build (`index-BsqqEUNg.js`), ready in 17 s | yes | |
| `licorice` at `size=1` | normal sticks; the state reads 1.0 | big balls |
| `mol.focus(sel, direction=[0, 0, 1])` | red at the right, green at the top | |
| `mol.focus(sel, direction=[1, 0, 0])` | the same image as a turn of `right=90` | |
| `mol.focus(sel)`, then a turn, in one run | the turn applies | the turn is lost |
| `camera_turn(right=90)` / `(up=90)` | blue to the left / blue to the bottom, no tilt | |
| `direction` along the screen up; bad input | a correct view; `ValueError`, `TypeError` | |

PMView: no type errors and no new eslint errors in `updateVisualization.ts`. This repo: 34 tests pass, lint is
clean.

## Run

As slurmweb:

```bash
make image && make viewer                           # make viewer copies ../pmview-viewer-quality/build
make run JOB=evals/viewer-quality/train.yaml        # round 3: about $0.4
```

## Result

Run `viewer-quality-train-20261009-165017`: $0.40, 27 min, 14 of 15 trials. OpenAI stopped vq-labels-6lu7 with
`bio_policy` after 4 tool calls (also in round 1). All trials used our PMView build. Reviews in
`ratings/viewer-quality-train-20261009-165017.json`.

| Case | Round 2 | Round 3 | Your note |
|---|---|---|---|
| chains-4hhb | 6 | 6 | much better; the protein a bit less visible |
| cleanup-1jpz | 10 | 10 | |
| compare-vrk | 6 | 9 | improvement, the view could be better |
| covalent-6oim (new prompt) | 6 | 9 | |
| deepsite-7y5k | 0 (bio flag) | 4 | quite bad, we regressed |
| glycans-6vxx | 9 | 9 | the protein could be less visible |
| hbonds-1iep | 6 | 8 | still a bit overcrowded |
| interface-1n8z | 8 | 5 | |
| labels-6lu7 | 7 | 0 (bio flag) | |
| pocket-1hsg | 10 | 10 | the rotation could show more of the ligand |
| pocket-1m17 | 10 | 8 | should be zoomed a bit more |
| poses-1iep | 7 | 7 | bad view |
| resistance-1m17 | 6 | 7 | |
| slide-3ptb | 8 | 8 | the ASP text is not readable; the benzamidine view is not the best |
| surface-1a52 | 6 | 6 | |
| Mean | 7.0 | 7.1 | |

Without labels-6lu7: 7.0 → 7.6. On the 11 cases that the two faults below did not touch: 7.7 → 7.8.

- Size: no thick sticks. Agents give `size` from 0.5 to 1.4.
- Camera: `direction` in 10 cases, `camera_turn` in 3, no errors. But a direction can be wrong: interface-1n8z
  (8 → 5) used the vector from HER2 to the Fab, which puts the Fab between the camera and the interface.
- Fault in the eval (found after the run): our PMView build checks the project against the account's project list.
  `app` is not in that list, so PMView opened the default project `carles-project`, and every `pmview_load`
  failed (`Could not fetch file carles-project/...`). The 3 cases with files: deepsite drew the map as spheres from
  a PDB that it wrote by hand; poses took 1IEP from RCSB, which has other coordinates than the poses (closest pose
  11.9 Å); compare-vrk aligned in Python. The fix is round 4, change 1.
- API errors (one retry each): `len(mol.reps)` 4, `scipy` 3, `camera_zoom(distance=)` 2, `label_fields` as one
  string 2, a mask selection 1.
