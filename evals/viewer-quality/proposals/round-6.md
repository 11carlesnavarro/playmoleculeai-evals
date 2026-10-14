# Round 6

Status: applied (uncommitted), run (`viewer-quality-train-20261013-184940`) and reviewed: mean 7.4. See Result.

Round 5 scored 6.7 (`round-5.md`, Result). This round removes the PMView changes that break other code or
did not help, gives the browser a window where PMView captures the canvas as it is, and makes the agent draw
only what the user asks for.

| Change | Evidence | Where |
|---|---|---|
| 1. PMView: remove what breaks or does not help | see the table | PMView `utils.py`, `utils.ts`, `updateVisualization.ts`; PMAI `tools.py` |
| 2. Browser window 2560 × 1440 | at 1280 × 800 the canvas is 640 px wide | `docker/viewer/server.py` |
| 3. Only what the user asks | unasked labels in 7 cases, surfaces in 3, `VDW` iron in chains | PMAI `viewer.md`, skill `SKILL.md` |
| 4. No colour-scheme advice | poses: secondary-structure cartoon, 3 points | skill `SKILL.md` |

## 1. PMView: remove what breaks or does not help

| PMView change | Verdict | Why |
|---|---|---|
| relative `size` (round 3) | keep | notes on big sticks or balls: 3, 4, 6 cases in the baseline and rounds 1, 2; 0 in round 3; since then only `VDW` metals (2, 1). It makes moleculekit's docstring true ("sensible size at 1"), which agents print and follow; main's skill text (0.15, 0.3) did not stop the baseline. Main's skill must change with it. |
| screenshot sizes, no crop (round 5) | remove | changes every user's saved screenshot (no crop, new `hd` shapes); the eval does not need it with change 2 |
| `camera_zoom(distance)` | keep the docstring, keep the name `factor` | main's skill names it `factor`: `camera_zoom(factor=...)` raises after the rename (no such call in our traces) |
| focus margin 2 Å | Mol*'s default, 4 Å | a tuned number; round 4 camera lines net -1 |
| masks and index arrays | keep | the docstring takes them; refused masks cost surface-1a52 half its calls |
| a failed view keeps nothing | keep | a refused held rep failed every later call |
| `focus(direction)`, focus at once, `camera_turn` | keep | round 3 direction about +1 point; the surface cutaway (+4) needs the direction |

```diff
-def _camera_zoom(distance, smooth=False):
+def _camera_zoom(factor, smooth=False):
-  const radius = Math.max(sphere.radius + 2, 5);
+  const radius = Math.max(sphere.radius + 4, 5); // Mol*'s focusLoci defaults
```
`utils.ts`: `viewerScreenshotToFile` as in main. PMAI `pmview_screenshot`: the round 5 size text goes back to
"'viewport' matches the current canvas."

## 2. Browser window

PMView captures the canvas as it is only when the canvas is at least 960 × 540. Under that, it renders 1280 × 720
and crops: the agent sees a wider view than the user. With the chat at half the window, 1920 × 1080 gives 959 px.
Tested on this host with the site's PMView: at 2560 × 1440 the canvas is 1279 × 1437, and `pmview_screenshot` gives
that view.

```diff
-        self.context = await chromium.new_context(viewport={"width": 1280, "height": 800},
+        # a QHD screen: the canvas (half the window) is wide enough for PMView to capture it as it is
+        self.context = await chromium.new_context(viewport={"width": 2560, "height": 1440},
```

## 3. Only what the user asks

Round 5 removed the skill sentence that invited labels; labels stayed (7 cases, round 4: 6). The rule goes in the
prompt. `viewer.md`:
```diff
+- Show what the user asks for, and nothing more: no labels, surfaces, distances or spheres that the user did not ask for.
```
`SKILL.md`, "A good view":
```diff
-- A bigger size does not help: thick sticks cover the atoms around them, and so does `VDW`, which draws each atom at its van der Waals radius. `Licorice` draws an atom with no bonds, such as a metal ion, as a ball at the scale of the sticks, in its element colour.
+- Draw atoms as sticks (`Licorice`). `VDW` spheres cover the atoms around them: use them only when the user asks. A metal ion in `Licorice` is a small ball.
-- A surface around the subject hides it from every side, ...
+- When the user asks for a surface around the subject: a whole surface hides it from every side, ...
```

## 4. No colour-scheme advice

```diff
-- Give the subject a colour that nothing else in the view has, and leave the rest in the viewer's colour schemes (`secondary-structure`, `chain-id`, `element`). For sticks, ...
+- Give the subject a colour that nothing else in the view has. For sticks, ...
```

## For the PMView team

A canvas under 960 × 540 (a 1920 screen with the chat open) gives a screenshot wider than the view.

## Run

As slurmweb: `make image && make viewer && make run JOB=evals/viewer-quality/train.yaml` (about $0.4). The image
is again a different size (1279 × 1437), so compare it with round 5 by rubric line, not by the mean alone.

## Result

Mean 7.4 (round 5: 6.7, round 4: 8.3); 7.9 without glycans, which OpenAI stopped (`bio_policy`) before any viewer
call. Agent reviews of all 15 traces: `round-7.md`, Round 6 causes.

- Better: pocket-1hsg 5 → 10 (the agent removed the cartoon), resistance 5 → 10, poses 6 → 10, labels 5 → 9,
  deepsite 3 → 6, hbonds 8 → 10, interface 9 → 10.
- Worse: chains 10 → 6 (no `VDW` iron, as change 3 asks; cartoon opacity 0.86 hides 2 hemes; round 5: 0.30),
  compare-vrk 8 → 6 (labels), glycans 9 → 0 (the stop).
- covalent still 0: the bond is drawn, but the camera looks along the long axis of the ligand (31 overlapping atom
  pairs, round 4: 3), and Cys12 and the ligand have one colour.
- Change 3: labels nobody asked for in 4 of 14 trials (round 5: 7); a marker sphere stayed in deepsite.
- Time: median 4.6 min (round 5: 3.1). The model decoded at 82 tokens/s (round 5: 109) for the same tokens; at round
  5 speed the median is 3.5 min. The bigger image adds about 0.8 s and 1,400 prompt tokens to each look.
- Eval: deepsite ends on the Tables tab (the agent loaded `output.csv`), so the user sees a table; the agent and the
  review see the 3D canvas. slide spent 27.6 min on offline renders after `pmview_screenshot(full-hd)` gave 699 × 540
  (cause not checked).

