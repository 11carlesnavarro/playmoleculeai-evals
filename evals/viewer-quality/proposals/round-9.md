# Round 9

Status: proposed, not applied.

## Where we are

Round 8 scored 8.07 on 14 cases (round 7: 9.0 on the same 14). 6 cases got worse, 2 better, 6 stayed the same.
With one run per case, a case moves 2.4 points on average from round to round, so this drop can be noise (sign test
p = 0.29). The traces show what happened:

| Case | Lost | What the trace shows |
|---|---|---|
| chains | 5 | Gold hemes inside an orange chain, on black. The agent picked the colours by name. |
| interface | 4 | It framed the whole complex, because "focusing clips other contents". The cropped image then moved the centred interface to the top right. |
| pocket-1hsg | 4 | It framed ligand and pocket, so more cartoon stayed in front of MK1. It saw "largely overlapping" and stopped. |
| labels-3hs4 | 4 | It cut the pocket sticks down to single atoms to clear the labels. The labels passed this time. |
| poses | 3 | The crystal ligand does not stand out (both rounds). |
| deepsite | 3 | "Top pocket in the centre": the camera target is 0.6 Å from it. Why it failed is not measured. |
| hbonds | 2 | No labels. Round 7 had none either and passed. |
| compare, pocket-1m17 | 1 each | Whole proteins in view; protein cartoon removed. |

Round 8 helped where it gave the agent new abilities. Labels beside their atoms fixed the labels line (+3), and the
map clip fixed the deepsite map line (+4). The camera numbers in the result went into code in 6 trials, and nobody
poked at object internals (11 times in round 7, 0 now). 47 camera calls and 10 `params` uses gave 0 errors. Skill
reads went from 60 to 23 calls.

## The idea

The agent should work the viewer as a person does. Three things still break that:

```
 the agent                        today                                   a person expects
 adds a backbone                  the camera jumps to the whole protein   the camera stays
 focuses on the interface         all 4 Å beyond it is cut away           the interface fills the view
 pans the camera 38 Å             the image looks the same (cropped)      the picture moves
```

## Change 1: the camera moves only when asked

Mol* moves the camera to the whole scene when new drawings lie outside the view. That suits a person who opens a
file, but code that adds a representation loses its camera:

- covalent step 18: adding a backbone moved the camera from 33.9 to 41.3 Å. "Oh no, the backbone representation
  unexpectedly changed the camera!" After that it sent the camera again with each change (14 `pmv.settings` calls).
- slide step 55: adding a backbone moved the camera to 72.8 Å, and the next step set it back.
- deepsite step 16: a focus in the same code as a map change put the target 38 Å from where the same focus put it
  at step 21. The cause is not measured, and we test it.

Change: code that changes a view keeps the camera. Only `focus`, `camera`, `camera_turn` and `camera_zoom` move it.
The first molecule in an empty viewer is still framed. PMView already does this when it shows several entries or
frames (`withCameraResetSuppressed`).

## Change 2: focus frames, clip cuts

Today `mol.focus(sel)` does two things: it frames `sel`, and it cuts away all that lies more than 4 Å in front of or
behind it. To keep the context, the agent focuses on more than the subject, so the subject gets small. Clipping is in
the reasoning of 11 trials in both rounds (44 steps in round 8). interface step 11: "focusing clips other contents ...
focus on the full protein instead".

```python
mol.focus('resname MK1')     # MK1 fills the view; the depth stays as it is
pmv.settings(clip=8)         # cut away what is more than 8 Å in front of or behind the center
pmv.settings(clip=False)     # the whole depth again (the default)
```

The skill then drops "cuts away the rest: focus on all that the view must show". It needs no rule like the deleted
"Focus on the subject". Risk: in round 7 the cut also hid the cartoon in front of MK1. Before we apply it, we render
pocket-1hsg and interface on this host with both behaviours.

## Change 3: one state, less noise

- `pmv.get_viewer_state()` gets the `camera`, as the result has. In round 8 code read `state['camera']` and failed 4
  times (compare, deepsite, interface, labels), so the agent copied the numbers from the text.
- A mask selection prints as ranges: `index 2301 to 2309 2410 to 2418` instead of every atom. About half of the new
  state text was these lists, and one hbonds result had 10,781 characters.
- Settings at the style's default leave the state: `size_theme` showed in 361 of 373 representations, and nobody set it.
- Bug: `print(mol.reps[i])` fails when the selection is a mask (labels step 11).

## Change 4: transparent images look black to the agent

`pmview_screenshot` saves with a transparent background by default. PMAI sends that PNG to OpenAI models as it is, and
they see black: slide spent 7 steps (60 s) on it and composited the image with PIL three times. Round 7 slide had the
same problem. The agent gets the image on white, as PMAI's chat completions path already does when it shrinks an
image. The file keeps its transparency.

## Change 5 (eval): grade the view the user sees

`final-view.png` comes from PMView's screenshot, which crops the empty margins (8 of 15 final views in round 8). The
user in the app sees the whole viewport. In interface the agent centred the interface in the viewport, and the crop put
it at the top right. Your decision of 2026-10-08 is that the grader sees the viewport the user sees. The sidecar will
take the canvas as shown. The ratings before round 9 are of the cropped images.

## Your decisions

1. **The agent's images.** They are cropped too: 68 of the 108 images in round 8. In deepsite a 38 Å pan did not show,
   and the agent concluded "the rendering doesn't consider the camera targeting". In slide `full-hd` gave 756×569.
   Should the image after each change show the whole viewport? The saved screenshots would keep the crop. In round 5
   you rejected the screenshot changes, and that set included this one.
2. **AGENT.md line 10** (reproducibility; still open). New evidence: covalent wrote a script and a figure that nobody
   asked for (steps 30 to 34, 92 s): "I could still offer a reproducible file".
3. **Measurement.** With one run per case, we cannot see a 1 point change. Options: 3 runs per case (about $1.10 a
   round, 45 images for you to rate), or build the judge now and check it against your 134 ratings.

## Not now

- A colour check (chains). Round 7's palette colours for that case were also closer than the palette's own limit. A
  check would change the agent's choice: not measured.
- The label rule in viewer.md. hbonds obeyed it and lost 2, round 7 hbonds obeyed it and passed, and resistance
  obeyed it and got 10.
- Several candidate views in one image, the visible share in each result, label layout by the viewer: no evidence
  yet that they change the result.
- Alignment of different sequences (compare: 18 steps, 270 s). MoleculeKit's `Molecule.align` may run in the viewer:
  not tested.

## How we will know

Compare round 9 with round 8 by rubric line: the framing lines (interface, pocket-1hsg, compare, poses), the steps
after a representation change, the camera errors, the state length, and the slide steps.
