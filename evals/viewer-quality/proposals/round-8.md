# Round 8

Status: applied, run (`viewer-quality-train-20261014-150617`) and reviewed: mean 8.07. See Result.

## Where we are

Round 7 scored 9.07 out of 10, the best so far. It lost 14 points in five cases:

| Case | Lost | Why |
|---|---|---|
| labels-3hs4 | 3 | The labels sit on top of the atoms. |
| resistance | 3 | A label nobody asked for: white text with a white outline. |
| deepsite | 4 | The agent cut the map down to one pocket. You wanted the whole map with the top pocket highlighted. |
| poses | 3 | The grey crystal ligand does not stand out on white. One pose is dark blue, like the nitrogens. |
| compare | 1 | The view shows the whole protein instead of the pocket. |

## The idea

Round 7 showed that new abilities help more than new rules. Round 8 gives the agent two things a person at the
viewer has: the side panel (what is drawn, where the camera is) and every setting that Mol* has. It also deletes
two sentences that push the agent in one direction.

```
                 today                                     round 8
  agent ── code ──▶ viewer                  agent ── code ──▶ viewer
  agent ◀── picture + system names          agent ◀── picture + every representation + camera

  a new Mol* setting = we write a wrapper   a new Mol* setting = the agent passes it by name
```

## Change 1: the agent sees what is drawn, not only the picture

Today the agent gets a picture and the system names. To know what it drew, it prints objects and docstrings, and it
gets confused. In 11 trials it read the state in the same code as a change and got the old state back (13 times).
In resistance it then believed that `reps.remove()` had failed.

What changes: each result lists the representations and the camera (the values below are an example).

```
today:    Viewer state: {"systems": {"81fd…": {"name": "4hhb", "visible": true, "type": "structure"}}}

round 8:  Viewer state: {"systems": {"81fd…": {"name": "4hhb", "visible": true, "type": "structure",
            "representations": [
              {"sel": "protein and chain A", "style": "cartoon", "color": "#1151a0", "opacity": 0.58},
              {"sel": "resname HEM", "style": "Licorice", "color": "element", "c_atom_color": "#ed5f10", "size": 1.4}]}},
          "camera": {"position": [12.1, 4.0, 76.3], "target": [12.1, 4.0, 8.3], "up": [0, 1, 0]}}
```

The viewer's Python already builds this list (`get_viewer_state()`), so the tool and the code see the same state.
Three small fixes go with it:

```python
print(mol.reps[1])
# today:   <moleculekit.representations._Representation object at 0x20f2c48>
# round 8: {'sel': 'resname HEM', 'style': 'Licorice', 'color': 'element', 'c_atom_color': '#ed5f10', 'size': 1.4}

mol.reps.remove(0)
print(pmv.get_viewer_state())
# today:   the old state, with no warning
# round 8: the same, plus "Note: changes apply when this code ends. The result shows them."

len(vol.reps), vol.reps[0]    # today: errors on maps. Round 8: works as on molecules.
```

### The camera, in Mol*'s own terms

Today the agent cannot read the camera, and "up" means two things. In `camera_turn(right=30, up=15)` it is degrees
toward the top of the screen. In the first draft of `pmv.camera(up=...)` it was a vector. The agent did not know
either (covalent: "is the Molstar scene y-up?").

Mol* stores the camera as three vectors in the structure's coordinates: Å, the same x, y, z as `mol.coords`.

```
                          up: the structure direction that points to the top of the screen
                          ▲
                          │
  position ●──────────────┼──────────────▶ ● target
  (the camera)       view direction = target − position      (the center of the screen)
```

The state reports these three vectors, and `pmv.camera()` sets any of them, as Mol* takes them:

```python
pmv.camera(position=[40.0, 12.5, 8.3], target=[12.1, 4.0, 8.3], up=[0, 0, 1])
# the camera stands at (40.0, 12.5, 8.3) Å, looks at (12.1, 4.0, 8.3), and the structure's z axis points to the top
```

Turns move the camera around the target, in degrees. The names and signs are those of the VTK camera
(`vtkCamera.Azimuth`, `Elevation`, `Roll`), checked with VTK 9.7.1. `camera_turn(right=, up=)` becomes:

```python
pmv.camera_turn(azimuth=30)    # around the screen's vertical axis: the camera moves to the right
pmv.camera_turn(elevation=15)  # around the screen's horizontal axis: the camera moves to the top
pmv.camera_turn(roll=90)       # around the line of sight: the picture turns a quarter turn counterclockwise
```

Yaw and pitch are not used: in camera terms (VTK too) they turn the camera in place, so it looks away from the target.

Only our worktree has `camera_turn`, so no old names stay. `mol.focus(sel, direction=d)` keeps its meaning: the
camera stands on the side `d` of the selection, so `position = target + distance * d`.

## Change 2: every Mol* setting, by its Mol* name

Today the agent can only use the settings that we wrapped one by one (`size`, `opacity`, `label_style`, and in round 7
`Interactions`, `settings`, `visible`). Mol* has many more, such as label leader lines and clipping, and the agent
needs them. deepsite could not clip the map in the viewer, so it cut a copy of the map file instead: steps 7 to 43
(458 s) are mostly that, with 17 sandbox calls and 4 reloads.

What changes: a `params` argument passes any Mol* setting of that style, and `pmv.params()` lists them.

```python
pmv.params('Labels')
# attachment    'middle-center'  where the label sits: on its atom, or beside it ('top-right', 'bottom-left', ...)
# tether        True             a line from the atom to a label beside it
# tetherLength  0 to 20 (3)      how far beside the atom
# offsetZ       0 to 10 (0)      move the label toward the camera, in front of the sticks
# borderWidth   0 to 0.5 (0.2)   outline around the letters
# ...

# Labels beside their atoms, each with a short line to its atom (labels-3hs4, resistance)
mol.reps.add('name CA and resid 92 94 96', 'Labels',
             params={'attachment': 'bottom-left', 'offsetZ': 2})

# Show only the part of a map within 8 Å of the top pocket (deepsite)
top.reps.update(0, color='#2dd4bf', params={'clip': {'objects': [
    {'type': 'sphere', 'invert': True, 'position': [23.4, 37.4, -25.3], 'scale': [16, 16, 16]}]}})
```

The viewer checks each name against Mol*'s own list. A wrong name gives a note with the right names. These settings
only change how things are drawn. They go through the same checked messages as today, so the code still cannot
reach the page, the project or the account.

## Change 3: delete text that pushes the agent

| Text today | Change | Why |
|---|---|---|
| Skill: "Focus on the subject, not on the whole molecule, so that it fills the view." | Delete | It pushes the agent to close ups. deepsite: "I initially showed a global view, but the top pocket was too small." |
| Skill: "A label in the view covers the atoms behind it, and labels in a pocket overlap." | Replace with how to put a label beside its atom (change 2) | Labels lost 6 points |
| Palette skill: "use whenever choosing colours to ... distinguish entities" | Say it is for charts and plots | Agents read it in 9 of 15 trials and used its chart colours on molecules (poses) |
| pmview skill description | Add: `Molecule('1abc')` downloads a structure | Agents read the database skills in 11 trials (about 5,600 tokens each time) to load a PDB entry |
| `mol.reps.add` docstring | Add `Interactions` | hbonds read the MoleculeKit source to find it |

## Change 4: one bug from round 7

```python
mol.view(sel='protein', style='cartoon', hold=True, name='Spike')   # today the name is lost
mol.view(sel='resname NAG', style='Licorice')                        # round 8: the system is "Spike"
```

MoleculeKit stops at `hold=True` before it reads `name`. This happened in 4 of 9 trials. PMView will keep the name.

## Not now

More than one surface per map (one surface per map is built into 11 PMView files; loading the map twice tests the
need first), `Interactions` by kind, Biopython in the viewer, a colour for each SDF entry, automatic label placement,
play and pause.

## Your decision

`AGENT.md` line 10 asks the agent to make the work reproducible (scripts, READMEs). Because of it, the agent writes
files even when the user only asks for a view: 26 write and edit calls in round 7, against 5 in round 6. Keep it, or
apply it only to analysis tasks?

## How we will know

Compare round 8 with round 7 by rubric line: the label lines (labels-3hs4, resistance), the deepsite map, the pose
colours, the compare zoom, and the camera lines of all cases (change 3 deletes a camera sentence). Also count the
steps that only read the state, the sandbox calls in deepsite, and the cost (round 7: $0.32).

## Applied

- Change 1: the result state gives each structure's `representations` (from `get_viewer_state()` in the viewer's
  Python, without the arguments at their defaults), each map's `volumeParameters` (isovalue, its range, colour,
  opacity), and `camera` (`position`, `target`, `up`). User messages get the same state. `print(mol.reps[i])` and
  `print(vol.reps[0])` give a dict. `get_viewer_state()` prints the note when changes wait. `len(vol.reps)` and
  `vol.reps[0]` work. `pmv.camera(position=, target=, up=)`; `pmv.camera_turn(azimuth=, elevation=, roll=)`.
- Change 2: `params=` on `reps.add`, `reps.update`, `mol.view` and `vol.reps.update`; `None` sets a setting back to
  its default. PMView sends Mol*'s list of settings to the viewer's Python at start, so a wrong name or value fails at
  the call, with the right names. Settings that an argument sets (`alpha`, `sizeFactor`, `labelFields`, `isoValue`)
  are refused with the argument's name. `pmv.params(style)` prints the settings. A change in the map panel keeps the
  map's `params` (tested with the isovalue box; the colour and opacity controls not tested).
- Change 3: all five text changes. The pmview skill describes the camera, `params`, label placement and map
  clipping. `AGENT.md` is not changed: your decision is open.
- Change 4: the name given with `hold=True` stays.
- Tested on this host (sidecar on port 8799, PMView build, 1IEP and 7Y5K with its map): the camera numbers match VTK
  9.7.1 (azimuth 30, elevation 15, roll 90); labels with `attachment` sit beside their atoms with a line; a clip
  sphere with `invert` keeps only the map inside it (`scale` is the diameter, Mol* shader) and `None` removes it;
  wrong names and values fail at the call and leave the representation as it was; PMAI's tools return the new state.
  PMAI tests pass. tsc, eslint and ruff errors are only in lines that were there before.
- Found in the test and fixed: Pyodide passes `None` as `undefined`, so `None` did not reset a setting; Pyodide's
  Python 3.13 removes the indent of docstrings, so the docstring additions did not apply.
- Seen in the test, not changed: `get_viewer_state()` right after `pmview_load` can miss the new objects for about
  0.3 s. Not measured in runs.

Run, as slurmweb: `make image && make viewer && make run JOB=evals/viewer-quality/train.yaml` (about $0.3 to $0.4).

## Result

Mean 8.07 on 14 cases (surface-1a52 has one empty check; round 7: 9.0 on the same 14). 15/15 trials, $0.36 (round 7:
$0.32), agent time 4,289 s (3,989 s). 6 cases worse, 2 better, 6 the same: a sign test gives p = 0.29, so the drop can
be noise.

- Better: deepsite 6 → 7 (the map clip kept compact pockets), resistance 7 → 10 (no label; `pmv.visible` checked
  Thr790). labels-3hs4 passed the readability line with labels beside their atoms (`attachment`, `tether`, `offsetZ`).
- Worse: chains 10 → 5 (gold hemes inside an orange chain, on black; no palette read), interface 10 → 6 (framed the
  whole complex, "focusing clips other contents"; the crop put the centred interface at the top right), pocket-1hsg
  10 → 6 (framed ligand and pocket; more cartoon in front), labels-3hs4 7 → 6 (sticks cut to single atoms), hbonds
  10 → 8 (no labels; round 7 had none and passed), pocket-1m17 10 → 9 (cartoon removed).
- Same: poses 7 (the crystal ligand does not stand out), compare 9 (whole proteins).
- Changes: no reads of object internals (round 7: 11); the name with `hold=True` kept 12 of 12; map representations
  work; 10 `params` uses and 47 camera calls, 0 errors; skill read calls 60 → 23 (palette 9 → 1 trials, data-retrieval
  11 → 1). 10 of 15 trials cost less; slide, covalent and labels-3hs4 cost more.
- Faults: the camera is in the result but not in `pmv.get_viewer_state()` (4 KeyErrors); mask selections print every
  atom index (about half of the new state text); `print(mol.reps[i])` fails for a mask; `size_theme` shows in 361 of
  373 representations. A representation change can move the camera (covalent, slide), and 68 of 108 images to the
  agent are cropped (both also in round 7). Causes and the next changes: `round-9.md`.
