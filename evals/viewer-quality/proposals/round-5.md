# Round 5

Status: applied (uncommitted), run and reviewed: 6.7 / 10 (round 4: 8.3). Round 6 reverts change 1 (the screenshot code); change 2 stays.

Round 4 scored 8.3 / 10 (`proposals/round-4.md`, Result). This round removes causes, and adds no camera or style
feature. The agent works the viewer as the user does: it sees the canvas that the user sees, a selection in any form
that moleculekit takes works, a failed call leaves nothing behind, and the agent sees the result as soon as the action
is done. The skill and the prompt lose the lines that led to labels, balls and dark colours that nobody asked for.

Users get the PMView changes (1 and 2) only when the PMView team merges them. The PMAI size description of change 1
is correct only with the PMView change.

| Change | Round 4 cases | Where | State |
|---|---|---|---|
| 1. The screenshot is the canvas | all; camera lines in pocket-1hsg, interface, hbonds | PMView `src/molkitstar-ui/LLMChat/utils/utils.ts`; PMAI `plugins/viewer/tools.py` | applied, tested |
| 2. Masks and index arrays as selections; a failed view keeps nothing | surface, deepsite | PMView `public/static/assets/utils.py`; skill `SKILL.md`, `references/selection.md` | applied, tested |
| 3. Colour, not labels or `VDW`, for the subject | chains, labels, cleanup, covalent, slide, deepsite | skill `SKILL.md`, `references/representations.md` | applied, tested |
| 4. The image file is the saved view | slide | PMAI `plugins/viewer/viewer.md` | applied |
| 5. The palette colours are for charts | covalent, slide, pocket-1hsg, interface, compare-vrk | PMAI `plugins/viewer/viewer.md` | applied |
| 6. No wait before the look | all: 90 looks | PMAI `plugins/viewer/pmview.py`, `tests/test_tools.py`, `tests/test_cli.py` | applied, tested |

## 1. The screenshot is the canvas

The sidecar window is 1280 × 800 and the chat takes the right half, so the canvas is about 640 × 760. PMView's
`viewerScreenshotToFile` renders a canvas smaller than 960 × 540 at 1280 × 720 ("hd") with the same camera, and then
crops the empty margin (`autocrop`). Mol* keeps the height of the view, so the 16:9 image shows 2.1 times the width
that the user sees. All the screenshots go this way: the one with each prompt, `include_screenshot`,
`pmview_screenshot`, and the eval's `final-view.png`.

`final.png` (the browser window at the end) against `final-view.png` (what the agent and the review see):

| Case | On the screen | In the agent's image |
|---|---|---|
| resistance-1m17 | erlotinib cut at the left edge | erlotinib whole, with space around it |
| labels-3hs4 | the pocket and its labels fill the canvas | the pocket small, in the middle of the protein |
| interface-1n8z | the interface cut at the left edge | the whole complex |
| pocket-1hsg | the protein small in a black canvas | a 351 × 456 crop: the protein fills the image |

The agent cannot judge the zoom or the center: the crop removes the margin that shows them. Your baseline note "the
agent's screenshot and the final viewer image differ" has this cause. In the app, a canvas of 960 × 540 or more is
captured at its size, but it is cropped too.

The canvas is captured as it is, with no crop. The named sizes (`hd`, `full-hd`, `ultra-hd`) were 16:9 images: without
the crop they show more than the view, so they now keep the shape of the canvas and only add pixels. The "hd" fallback
stays for a hidden or thin canvas:

```diff
 // src/molkitstar-ui/LLMChat/utils/utils.ts
-// "viewport" capture breaks when the viewer tab is hidden or a thin sliver, so
-// for a too-small canvas we fall back to Molstar's "hd" (1280×720) resolution.
-const MIN_VIEWPORT_WIDTH = 960;
-const MIN_VIEWPORT_HEIGHT = 540;
+// A screenshot shows the view as the user sees it: the whole canvas. The named
+// sizes keep the shape of the canvas, so they show the same view with more
+// pixels. "viewport" capture breaks when the viewer tab is hidden or a thin
+// sliver, so for such a canvas we fall back to Molstar's "hd" (1280×720).
+const MIN_VIEWPORT_SIDE = 200;
+const IMAGE_HEIGHT = { hd: 720, "full-hd": 1080, "ultra-hd": 2160 };
+const MAX_IMAGE_SIDE = 4096; // the largest custom size Molstar offers

-const resolveScreenshotResolutionName = (
-  resolution: ScreenshotResolution
-): string => {
-  if (resolution !== "viewport") return resolution;
+const screenshotResolution = (resolution: ScreenshotResolution) => {
   const gl = window.molstar?.canvas3d?.webgl?.gl;
-  const tooSmall =
-    (gl?.drawingBufferWidth ?? 0) < MIN_VIEWPORT_WIDTH ||
-    (gl?.drawingBufferHeight ?? 0) < MIN_VIEWPORT_HEIGHT;
-  return tooSmall ? "hd" : "viewport";
+  const width = gl?.drawingBufferWidth ?? 0;
+  const height = gl?.drawingBufferHeight ?? 0;
+  if (Math.min(width, height) < MIN_VIEWPORT_SIDE)
+    return { name: "hd" as const, params: {} };
+  if (resolution === "viewport")
+    return { name: "viewport" as const, params: {} };
+  const scale = Math.min(
+    IMAGE_HEIGHT[resolution] / height,
+    MAX_IMAGE_SIDE / Math.max(width, height)
+  );
+  return {
+    name: "custom" as const,
+    params: {
+      width: Math.round(width * scale),
+      height: Math.round(height * scale),
+    },
+  };
 };

 export const viewerScreenshotToFile = async (
   transparent: boolean = false,
-  resolution: ScreenshotResolution = "viewport",
-  autocrop: boolean = true
+  resolution: ScreenshotResolution = "viewport"
 ) => {
 ...
-      resolution: {
-        name: resolveScreenshotResolutionName(resolution),
-        params: {},
-        // eslint-disable-next-line @typescript-eslint/no-explicit-any
-      } as any,
+      resolution: screenshotResolution(resolution),
     });
-    if (autocrop) {
-      screenshotHelper.getPreview();
-      screenshotHelper.autocrop();
-    } else {
-      screenshotHelper.resetCrop();
-    }
+    screenshotHelper.resetCrop();
```

No caller passed `autocrop` (`saveScreenshot.ts`, `regenerateAnswer.ts`, `prepareMessageContent`). The typed result
also removes the `as any` cast.

PMAI, `pmview_screenshot`:

```diff
 # src/playmoleculeai/plugins/viewer/tools.py
-        "Output image size. 'viewport' matches the current canvas.",
+        "Image size. 'viewport' is the size of the viewer canvas; 'hd', 'full-hd' and "
+        "'ultra-hd' show the same view 720, 1080 and 2160 pixels high. The image is at "
+        "most 2000 pixels on its longest side.",
```

The 2000 pixel limit is PMView's (`downscaleDataUrl`, for the model), also before this round.

`final-view.png` becomes the canvas, the view that the sidecar's user sees. You rate round 5 on that image, so a part
of the change in the camera lines comes from the image alone.

## 2. Masks and index arrays as selections

The docstrings that agents print (`mol.reps.add.__doc__`, `mol.atomselect.__doc__`) say that a selection is a string,
a boolean mask or an index array. PMView refused the last two (`_rep_payload`), and the skill said so since round 2.
Round 4 still had 4 refused masks (deepsite 1, surface 3).

In surface-1a52 the refused mask stayed in the held representations (`hold=True`): `PmvViewer.view` dropped only the
refused one and raised, so the next call failed on the next held mask, also after the agent wrote strings. The agent
then read PMView's source with `inspect.getsource`: about half of its 30 calls went to this. The round 4 skill example
also needed `'index ' + ' '.join(...)` to draw a mask.

`public/static/assets/utils.py`:

```diff
+def _sel_text(sel):
+    """A selection as the viewer takes it: text. moleculekit also takes a
+    boolean mask or an array of atom indices, which become an index list."""
+    if sel is None or isinstance(sel, str):
+        return sel
+    sel = np.asarray(sel)
+    if sel.dtype == bool:
+        sel = np.flatnonzero(sel)
+    return "index " + " ".join(map(str, sel.astype(int).ravel()))
+
+
 def _rep_payload(described):
     """Turn moleculekit's representation description into a viz update."""
     style = _VIZ_STYLES.get(described["type"])
     if style is None:
         raise ValueError(f"The viewer cannot draw {described['type']!r}.")
-    sel = described["sel"]
-    if not isinstance(sel, str):
-        raise ValueError(
-            "The viewer needs a selection written as a string, not a mask or "
-            "an index array."
-        )
+    sel = _sel_text(described["sel"])
```

`mol.reps` keeps the mask as the agent wrote it, and the viewer's list has the text. The sync matches the two lists
by selection; an array compared with a string raises `ValueError: The truth value of an array ... is ambiguous`, and
the representations of that molecule stop following the viewer. So the key uses the text too, and the keys of the held
representations are made once per sync, not once per pair:

```diff
 def _rep_slot_key(sel, style):
 ...
-    return sel, MOLSTAR_STYLES.get(key, key)
+    return _sel_text(sel), MOLSTAR_STYLES.get(key, key)

 def _sync_molecule_reps(mol, reps):
-    pool = list(mol.reps.replist)
+    pool = [(_rep_slot_key(held.sel, held.style), held) for held in mol.reps.replist]
 ...
-        for i, held in enumerate(pool):
-            if _rep_slot_key(held.sel, held.style) == key:
+        for i, (held_key, _) in enumerate(pool):
+            if held_key == key:
 ...
-                claimed = pool.pop(i)
+                claimed = pool.pop(i)[1]
```

A call that fails keeps nothing that it held:

```diff
 # PmvViewer.view
             try:
                 payloads.append((rep, _rep_payload(_describe(mol, rep))))
             except ValueError:
                 if id(rep) in staged_ids:
-                    _forget_rep(mol, rep)
+                    # The call fails as a whole, and nothing it held stays
+                    # to fail the next one.
+                    mol._tempreps.replist.clear()
                     raise
                 continue
```

`_forget_rep` had no other caller and goes. `mol.viewer_select` resolves any selection already, but its check for an
empty string raised the same `ValueError` for a mask:

```diff
 # pmv_select
-    if selection == "":
+    if isinstance(selection, str) and selection == "":
```

Skill, `SKILL.md`:

```diff
 ## Selections

-A selection is a string in VMD syntax. The viewer does not take masks or index arrays.
+A selection is a string in VMD syntax, a boolean mask or an array of atom indices.
```

```diff
   pocket = mol.atomselect('protein and same residue as (within 6 of resname EST)')
-  behind = np.where(pocket & ((mol.coords[:, :, 0] - center) @ d < 0))[0]
-  mol.reps.add('index ' + ' '.join(map(str, behind)), 'Surf')
+  behind = pocket & ((mol.coords[:, :, 0] - center) @ d < 0)
+  mol.reps.add(behind, 'Surf')
```

`references/selection.md`:

```diff
-MoleculeKit selections follow VMD syntax. The viewer takes them as strings; `mol.atomselect(sel)` gives the same selection as a mask, for analysis in Python.
+MoleculeKit selections follow VMD syntax. `mol.atomselect(sel)` gives the same selection as a mask, for analysis in Python.
```

Other struggles of round 4 get no change:

| Struggle | Cases | Why no change |
|---|---|---|
| `pmv.get_viewer_state()` after a change in the same run shows the state before it | 23 runs in 14 cases | The skill says it, and the tool returns the new state with the screenshot. |
| `len(mol)` | 2 | moleculekit's class, not PMView. |
| Analysis in the sandbox (Bio.PDB, scipy) | compare-vrk 28 calls, interface 16 | compare-vrk scored 10. It costs time, not quality. |

## 3. Colour, not labels or `VDW`, for the subject

Your notes of rounds 1 to 4:

- Big balls: chains-4hhb in rounds 1, 2 and 4, resistance in round 1, labels-3hs4 in round 4. In round 4 both are
  `VDW` on one metal atom: Fe at size 1.35, then 0.55; Zn at 0.8, then 0.4. `VDW` draws atoms at their van der Waals
  radius, so the ball is still much thicker than the sticks around it. chains loses the heme line (4 points). The
  agent takes `VDW` to show an ion, but `Licorice` draws an atom with no bonds as a ball too (Test).
- Labels nobody asked for: cleanup and hbonds (round 1), pocket-1hsg and pocket-1m17 (round 2), slide (ASP 189) and
  deepsite (TOP) in round 4. covalent loses its label line (an unasked CYS 12). The skill sentence "A label helps for
  one or two atoms that the user must find in the view, such as a mutated residue" gives the reason: the agent labels
  the one residue that the prompt names.
- One colour for all atoms hides them: cleanup loses the iron line (the heme in `#E6A23C`); chains drew the hemes in
  one orange and added the Fe ball to show the iron; covalent drew Cys12 and the ligand in one `#3c95bf` (carbon line
  fails). Your note on compare-vrk: "colours chosen at random; the default colours were simpler".

`SKILL.md`, "A good view":

```diff
-- Give the subject a colour that nothing else in the view has. A bigger size does not help: thick sticks and spheres cover the atoms around them. The background is black: dark colours sink into it, light colours stand out.
-- Name the residues in the text answer, for example "ASP25, GLY27, ASP29". A label in the view covers the atoms behind it, and labels in a pocket overlap. A label helps for one or two atoms that the user must find in the view, such as a mutated residue.
+- Give the subject a colour that nothing else in the view has, and leave the rest in the viewer's colour schemes (`secondary-structure`, `chain-id`, `element`). For sticks, colour the carbons and keep the element colours of the other atoms (`color='element', c_atom_color=...`): one colour for all atoms hides which one is a metal, an oxygen or a nitrogen. The background is black: dark colours sink into it, light colours stand out.
+- A bigger size does not help: thick sticks cover the atoms around them, and so does `VDW`, which draws each atom at its van der Waals radius. `Licorice` draws an atom with no bonds, such as a metal ion, as a ball at the scale of the sticks, in its element colour.
+- Name the residues in the text answer, for example "ASP25, GLY27, ASP29". A label in the view covers the atoms behind it, and labels in a pocket overlap.
```

`references/representations.md` loses what `SKILL.md` now says (why to colour the carbons, the black background),
and keeps the fact that the call needs:

```diff
 - `color` takes a scheme (`element`, `chain-id`, `secondary-structure`, ...), an SVG colour name or `#rrggbb`.
-- `c_atom_color` colours the carbons and keeps the element colours of the other atoms. It applies when the representation is coloured by element. Two molecules with different carbon colours stay different, and each still shows its N, O and S.
-- The background is black. Dark colours, such as navy or maroon, sink into it. Light and saturated colours stand out.
+- `c_atom_color` colours the carbons. It applies only when `color` is `element`.
 - `opacity` below 1 shows what is behind.
```

The labels case asks for labels, and the numbering line ("to label in the user's numbering, change `mol.resid`")
stays. resistance passed its Thr790 line with a label in round 4; the line also passes with "sticks with a distinct
colour".

## 4. The image file is the saved view

slide-3ptb asks for "a clear image ... for a slide, and save it as figures/benzamidine.png". `viewer.md` says "An
image file is a different result, made when the user asks for a file", and the agent made the file away from the
viewer: about 30 offline renders, 43 `view_image`, 95 calls, 15.9 min, $0.10 (a third of the run). Then it set the
viewer to match the file, with the ASP 189 label of the file (the clean line fails). `pmview_screenshot` saves the
view; no case called it in round 4.

```diff
 # src/playmoleculeai/plugins/viewer/viewer.md
-- When the user asks to see something, the result is the view: what the viewer shows when you finish. An image file is a different result, made when the user asks for a file.
+- When the user asks to see something, the result is the view: what the viewer shows when you finish. When the user also wants an image file of it, `pmview_screenshot` saves the view to the file.
```

## 5. The palette colours are for charts

The palette skill ("Use whenever choosing colours to encode data or distinguish entities") was read in 10 of 15
cases. Its colours pass its validator on a light surface (`--surface "#F2F5FA"`). In the viewer: navy `#1151a0`
sticks in slide (clean line fails), `#3c95bf` for both Cys12 and the ligand in covalent (2 lines fail), `#bc8000`
residues next to an `#ed5f10` ligand in pocket-1hsg, navy HER2 in interface. Your note on compare-vrk: "something
simple and clean to start". The 5 cases that did not read the palette scored 9.8 on average, the 10 that read it 7.6;
the harder cases are among the 10, so the palette is not the only cause.

```diff
 # src/playmoleculeai/plugins/viewer/viewer.md
+- The palette skill's colours are made for charts on light pages. On the viewer's black background its dark colours disappear.
```

The skill line of change 3 says which colours to use in the viewer.

## 6. No wait before the look

A computer use agent acts, then looks at the result at once. Our look (`include_screenshot`) first waits 1 s, then
reads the state and takes the screenshot. Round 1 added the wait as a precaution, with no failure behind it. PMView
already answers a tool call after the change is drawn:

- `executePythonScript` returns after the draw queue is empty (`awaitVisualizationQueueDrained`, PMView commit
  e6d1509, in main).
- Camera moves are instant: `camera.setState(..., 0)`; `smooth` is off by default.
- The screenshot draws the pending frame first (`animationLoop.tick`).

Test on this host (the sidecar with the round 4 build): after each action, the state and the screenshot at once
against the same 1.5 s later.

| Action | Call time | Screenshot at once against 1.5 s later | State |
|---|---|---|---|
| `Molecule('1hsg')`, `mol.view()` | 2.6 s | 1.5 % of the pixels, only along the edges; the same picture | the same |
| `reps.add` `VDW`, `reps.update` colour | 0.2 to 0.3 s | the same | the same |
| `mol.focus`, `camera_turn`, `camera_zoom` | under 0.1 s | the same | the same |
| `reps.add` `Surf` (within 8 Å of MK1) | 0.9 s | the same | the same |
| `reps.remove()`, `reps.add` cartoon | 0.4 s | the same | the same |
| `pmview_load` 3PTB.pdb, first and second | 1.3 s, 0.7 s | edges only; the same | the same |

Round 4 had 90 looks (83 of 141 `pmview_run_python` calls and all 7 `pmview_load` calls), so the wait cost 90 s,
about 6 s per case.

```diff
 # src/playmoleculeai/plugins/viewer/pmview.py
-import asyncio
-
 from playmoleculeai.core.items import InputImage
 from playmoleculeai.plugins.viewer.websocket import ConnectionRegistry

-# ponytail: a fixed wait for the canvas to draw the last change; replace it with a
-# "rendered" signal from the frontend if it gets one
-RENDER_WAIT = 1.0
-
 ...
     async def look(self, chat_id: str | None) -> tuple[dict, list[InputImage]]:
         """What the user sees: the viewer state and, when structures are loaded,
-        a screenshot (the same pair the frontend sends with each user message)."""
-        await asyncio.sleep(RENDER_WAIT)
+        a screenshot (the same pair the frontend sends with each user message).
+        PMView answers a tool call after it has drawn the change."""
         state = await self.execute("pmview_viewer_state", {}, chat_id)
```

`tests/test_tools.py` (fixture `pmview_env`) and `tests/test_cli.py` (`test_run_serves_the_viewer_socket`) lose
`monkeypatch.setattr("playmoleculeai.plugins.viewer.pmview.RENDER_WAIT", 0)`.

`pmv.get_viewer_state()` inside the same run still gives the state before the code: the code runs first, and PMView
draws after it. The skill line on this stays.

## Test

On this host, 2026-10-13: the sidecar (127.0.0.1:8799) with the new PMView build. Python went through `/python` as
the agent sends it, the screenshot through `pmview_screenshot`, and the canvas on the page through Playwright
(`.msp-viewport canvas`).

| Check | Result |
|---|---|
| 1HSG: the screenshot against the canvas on the page | both 639 × 797, the same view (2 % of the pixels differ, at the edges of the atoms) |
| `hd`, `full-hd`, `ultra-hd` | 577 × 720, 866 × 1080, 1604 × 2000 (the 2000 pixel limit); each the same view as the canvas |
| `mol.view(sel=mask, style='Licorice', hold=True)`, then `mol.view(sel='resname MK1', ...)`, then `mol.reps.add(index_array, 'Lines')` | all three drawn |
| `mol.reps.update(0, color='red')`: the viewer reports the change, and the sync runs | `mol.reps` keeps the mask and takes `#ff0000` from the viewer; no error in the page |
| `mol.viewer_select(mask, mode='set')` | selected (before: `ValueError`) |
| a held `resname XXX`, then `mol.view(sel='resname MK1', style='VDW')`, then `mol.view(sel='resname MK1', style='Licorice')` | the second call raises `Selection 'resname XXX' is empty`; the third draws only MK1: `mol.reps` is the cartoon and MK1 in `Licorice` |
| the surface example of `SKILL.md` on 1A52, chain A | the cup behind estradiol, as in round 4 |
| the zinc of 3HS4 in `Licorice`, then in `VDW` | `Licorice`: a small ball between the three histidines; `VDW`: a ball that covers them and the sulfonamide nitrogen |
| PMView `npm run build`, `tsc`, ESLint | the build passes; no type error and no new lint error in the changed files |
| PMAI `tests/test_tools.py`, `tests/test_cli.py`, ruff | 46 passed, 13 skipped; ruff passes |

## Run

As slurmweb:

```bash
make image && make viewer                           # the skill, PMAI and the PMView build
make run JOB=evals/viewer-quality/train.yaml        # round 5: about $0.3
```

## Result

Run `viewer-quality-train-20261013-160804`: $0.37, 28 min, 15/15, no error. Reviewed: mean 6.7 (round 4: 8.3).

| Case | R4 | R5 | Lines lost or won |
|---|---|---|---|
| covalent-6oim | 8 | 0 | centre, bond, carbon colours, label: ball-and-stick, a surface and a Cys12 label |
| labels-3hs4 | 10 | 5 | the label boxes cover the inhibitor and overlap |
| pocket-1m17 | 10 | 5 | a Met769 label covers erlotinib |
| resistance-1m17 | 10 | 5 | Thr790 colour, front, muted protein |
| poses-1iep | 10 | 6 | secondary-structure cartoon, crowded |
| compare-vrk | 10 | 8 | not zoomed, one colour for both |
| chains-4hhb | 6 | 10 | hemes visible; the iron is `VDW` again (your note) |
| interface-1n8z | 6 | 9 | zoomed; labels on every residue (your note) |

The others moved by 1 or less. Change 1 changed the image: round 4 rated a 16:9 render 2.1 times wider than the
canvas, and its page shots show the same views cut at the sides. Change 3 did not stop labels (7 cases, round 4: 6)
or `VDW` (chains). Change 4: slide 95 calls and 16 min down to 39 and 9, same score. Change 5: the palette was read in
5 cases (round 4: 9).
