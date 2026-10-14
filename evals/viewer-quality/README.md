# Viewer quality

Does PlayMoleculeAI make a good PMView view? Each case is a viewer request from a real chat (dev, prod and open trace DBs). The score is the final view, as the user sees it. Cost, time and tool calls come from the trace. The goal is to hill climb: find what makes the views bad (the skill, the tools, PMView or the model) and fix it.

Plan page: https://claude.ai/artifact/Jy2kpxN4vz6aAkGjhQZZYH

## Files

```text
cases/<case>/instruction.md       the prompt (starts with "Use the viewer.")
cases/<case>/tests/rubric.txt     what a good view shows: "<points> <criterion>" a line, 10 points in all
cases/<case>/task.toml            keywords (category, "holdout"), source chats, VIEWER_PRELOAD, a file the prompt asks for
train.yaml                        job: the 15 hill climbing cases
holdout.yaml                      job: the 5 held-out cases, only to check that a gain is real
ratings/<run>.json                your reviews of a run (from the review page)
proposals/round-<n>.md            one hill climb round: status, evidence, the changes as diffs, result
```

## Run

```bash
make image && make viewer          # after a change to src/ or docker/; both build from the hill climb worktrees
make run JOB=evals/viewer-quality/train.yaml                       # 15 cases, gpt-6-luna: less than $1
make run JOB=evals/viewer-quality/train.yaml CASE=vq-pocket-1hsg   # one case
```

The image to rate: `results/<run>/<case>__<id>/artifacts/logs/artifacts/viewer/final-view.png`, kept after the turn. The views during the turn are in `steps/` in the same folder (only the views that changed). A file that the prompt asks for is under `artifacts/` at its path in the container (vq-slide-3ptb: `artifacts/app/figures/benzamidine.png`).

## Score

1. Now: you review each final view on the review page (see "Human review" in the main README). Each rubric
   line is yes or no; the score is the points of the yes lines, out of 10. The main request has 4 to 6 points.
2. Then: a judge (gpt-6.1-sol) sees the same image and rubric. We keep it only if it agrees with your yes and no marks.

Until the judge, Harbor gives no score: the job files turn the verifier off. A run ends with a mean of 0.000, and
your score is `human_reward` in `make view`.

## Cases

| Case | Category | Holdout |
|---|---|---|
| vq-active-site-1ca2 | residues (prompt in Spanish) | yes |
| vq-chains-4hhb | chains | |
| vq-cleanup-1jpz | pocket (preload) | |
| vq-compare-d2d3 | compare | yes |
| vq-compare-vrk | compare | |
| vq-contacts-1aq1 | pocket | yes |
| vq-covalent-6oim | figure (preload) | |
| vq-deepsite-7y5k | volume (input files) | |
| vq-dimer-5kir | figure (preload) | yes |
| vq-explain-1eve | open | yes |
| vq-glycans-6vxx | large | |
| vq-hbonds-1iep | interactions | |
| vq-interface-1n8z | interface | |
| vq-labels-3hs4 | labels | |
| vq-pocket-1hsg | pocket | |
| vq-pocket-1m17 | pocket | |
| vq-poses-1iep | poses (input file) | |
| vq-resistance-1m17 | residues | |
| vq-slide-3ptb | figure (also saves figures/benzamidine.png) | |
| vq-surface-1a52 | surface | |

## Status

- 2026-10-08: the 20 cases are done. One test run of vq-pocket-1hsg worked (reward 1.0: the view was saved).
- 2026-10-08: the baseline run `viewer-quality-train-20261008-145621` (gpt-6-luna, 15/15 finished, $0.41) is on the review page.
- 2026-10-09: the 15 baseline views are reviewed (`ratings/viewer-quality-train-20261008-145621.json`): mean 5.9 / 10.
  Most points are lost on the camera (the ligand or the key residues hidden or not in the center), on the key residues
  not drawn as sticks, on sticks and spheres too thick, and on labels that overlap. vq-covalent-6oim no longer asks
  for a dark background (the viewer background is always black).
- 2026-10-09: hill climb round 1, in the `viewer-quality` worktrees (uncommitted). Run `viewer-quality-train-20261009-122438`
  ($0.38, 15 trials) is on the review page. vq-labels-6lu7 failed: OpenAI flagged the prompt (SARS-CoV-2 Mpro) as biological risk.
  PMAI: `include_screenshot` returns the viewer state and the screenshot after a 1 s wait; `pmview_screenshot`
  returns the image; `pmai run --viewer-id` sends the viewer state and a screenshot with the prompt, as the app does;
  correct tool descriptions; `viewer.md`: the result is the view, look at it and correct it before the answer.
  Skills (pmview only): the camera, composing a view, the isovalue, the stick size.
- 2026-10-09: round 1 reviewed (`ratings/viewer-quality-train-20261009-122438.json`): mean 5.9 / 10, the same as the
  baseline. Better: pocket-1hsg, pocket-1m17, slide, labels. Worse: compare-vrk, covalent, interface, cleanup.
  Causes: the agent sets stick `size` 0.8 to 1.45 (normal 0.15; the scale is only in references/styles.md, which
  3 of these 4 cases did not read); labels you did not want; palette colours dark on the dark background and the
  same for a residue and its protein; subjects still hidden (the agent looks 2 to 14 times, but PMView gives no
  way to read or set the camera direction). vq-covalent-6oim asks for "a figure for a paper": the agent made a
  file with molecule-render and gave the viewer little care.
- 2026-10-09: round 2, run `viewer-quality-train-20261009-143543` ($0.37, 28 min, 14/15: OpenAI flagged
  vq-deepsite-7y5k as biological risk). Not reviewed yet. The pmview skill is rewritten from the round 1 evidence (SKILL.md 139 → 72
  lines; references `representations.md`, `selection.md`, `volumes.md`; `styles.md`, the coding guidelines, the
  "do not set unless asked" rules and the palette link are removed). Facts it adds: the viewer docstring is wrong on
  `size` (it says 1 is normal; sticks draw at 0.15, cartoon at 0.2); selections must be strings (7 errors);
  `label_fields` is a list (5 errors); the background is black; labels cover what is behind them.
- 2026-10-09: round 2 reviewed (`ratings/viewer-quality-train-20261009-143543.json`): mean 7.0 / 10 (7.5 without
  vq-deepsite-7y5k, which OpenAI stopped), from 5.9. Better: pocket-1hsg 6 → 10, pocket-1m17 6 → 10, compare-vrk
  1 → 6, covalent 3 → 6, poses 5 → 7, cleanup 7 → 10. Worse: hbonds 8 → 6. Still wrong: sticks and spheres too big
  in 6 cases (agents that did not open representations.md, or that make the subject bigger to make it stand out),
  labels nobody asked for, the camera (surface from the side).
- 2026-10-09: round 3 applied and tested on this host, not run (`proposals/round-3.md`). The sidecar serves the
  PMView build of the worktree `pmview-viewer-quality` (`make viewer`); the backend is still the site's. PMView:
  `size=1` is the normal size of each style (before, sticks drew 6.7 times too thick); `mol.focus(sel, direction=...)`
  and `pmv.camera_turn(right=, up=)`; a camera call after `mol.focus` in the same run is no longer lost. Skill: plain
  "A good view" text (colour, not size, for the subject; residue names in the answer, not as labels); the new camera
  calls. vq-covalent-6oim asks for the view, not "a high-quality figure".
- 2026-10-09: round 3 run `viewer-quality-train-20261009-165017` ($0.40, 27 min, 14/15: OpenAI flagged
  vq-labels-6lu7 again) and reviewed (`ratings/viewer-quality-train-20261009-165017.json`): mean 7.1 / 10 (7.6
  without labels-6lu7), from 7.0. No thick sticks; covalent 6 → 9, compare-vrk 6 → 9, hbonds 6 → 8; interface 8 → 5
  (the camera direction put the Fab in front of the interface). Eval fault: our PMView build switched to the
  account's default project (`app` is not in its project list), so `pmview_load` failed in the 3 cases with files
  (deepsite, poses, compare-vrk). Details in `proposals/round-3.md`.
- 2026-10-09: round 4 applied and tested on this host, not run (`proposals/round-4.md`). The sidecar adds the trial
  project to the account's project list, so `pmview_load` works with our PMView build. Skill: no `lig - pocket`
  camera example; a pocket surface drawn only behind the ligand; label contrast; labels in the user's numbering
  (change `mol.resid`). PMView: `mol.focus` keeps 2 Å around the selection (was 4 Å); `pmv.camera_zoom(distance)`.
  vq-labels-6lu7 is now vq-labels-3hs4 (carbonic anhydrase II, acetazolamide), not comparable with the old case.
- 2026-10-09: round 4 run `viewer-quality-train-20261009-181219` ($0.33, 30 min, 15/15; no OpenAI stop) is on the review
  page. `pmview_load` worked in all 4 cases with files. The baseline images are off the page (511 file limit; its
  reviews are in `ratings/`).
- 2026-10-09: round 4 reviewed (`ratings/viewer-quality-train-20261009-181219.json`): mean 8.3 / 10 (8.2 on the 14
  cases of round 3, from 7.6). Better: surface 6 → 10 (the surface behind the ligand), poses 7 → 10, resistance 7 → 10
  (Thr790 in your numbering). Worse: pocket-1hsg 10 → 5 (residues in front of the ligand, camera far). Still wrong:
  `VDW` balls on metals, labels nobody asked for, the palette colours. The screenshot that the agent and the review see
  is not the canvas on the screen: PMView renders a small canvas at 1280 × 720 and crops it.
- 2026-10-13: round 5 applied and tested on this host, not run (`proposals/round-5.md`). PMView: the screenshot is
  the whole canvas, with no crop, and the named sizes keep its shape; a selection can be a mask or an index array; a
  failed `mol.view` keeps nothing that it held. PMAI: no 1 s wait before the look; `pmview_screenshot` saves the view
  when the user wants a file; the palette colours are for charts on light pages. Skill: colour the carbons of the
  subject and keep the schemes for the rest; `Licorice`, not `VDW`, for an ion; no labels the user did not ask for.
- 2026-10-13: round 5 run `viewer-quality-train-20261013-160804` ($0.37, 28 min, 15/15). All 15 final views are the
  whole canvas (639 × 797). The review page now shows only the final view of each case, so all runs fit on it.
- 2026-10-13: round 5 reviewed (`ratings/viewer-quality-train-20261013-160804.json`): mean 6.7 / 10. Part of the drop
  is the image: round 4 rated a render 2.1 times wider than the canvas. Still wrong: labels nobody asked for (7 cases),
  `VDW` iron, surfaces nobody asked for. Round 6 proposed (`proposals/round-6.md`): the screenshot size patch leaves PMView
  (relative `size` stays: it ended the notes on thick sticks), a 2560 × 1440 browser window, and only what the user asks.
- 2026-10-13: round 6 applied and tested on this host, not run (`proposals/round-6.md`). PMView: the screenshot code
  is main's again, `pmv.camera_zoom(factor)` keeps main's name, `mol.focus` keeps Mol*'s 4 Å. The sidecar window is
  2560 × 1440, so the canvas (1279 × 1437) is large enough for PMView to capture it as it is. PMAI prompt: show only
  what the user asks. Skill: sticks, `VDW` only when asked, a surface only when asked, no colour-scheme advice.
- 2026-10-13: round 6 run `viewer-quality-train-20261013-184940` ($0.41, 47 min, 15/15 final views; OpenAI stopped
  vq-glycans-6vxx as biological risk). The trials take longer (median 4.6 min, round 5: 3.1): the model was slower.
- 2026-10-14: round 6 reviewed (`ratings/viewer-quality-train-20261013-184940.json`): mean 7.4 / 10 (7.9 without
  glycans). Better: pocket-1hsg, resistance, poses, labels, deepsite. Worse: chains (hemes behind the cartoon),
  compare-vrk (labels). covalent still 0 (camera along the ligand). Details in `proposals/round-6.md`, Result.
- 2026-10-14: round 7 proposed (`proposals/round-7.md`), from agent reviews of the round 6 traces and the chats: the
  round 6 causes (a lost camera call, focus clipping, the hidden Tables tab, labels, the palette skill); `pmview_python`
  returns the new view, `pmview_look`; `Interactions`, `pmv.visible`, `pmv.settings`.
- 2026-10-14: round 7 applied and tested on this host, not run (`proposals/round-7.md`, Applied). PMAI comes from the
  worktree `playmoleculeAI-2-viewer-quality`. A provider stop runs the trial once more.
- 2026-10-13: no Harbor reward until the judge. The reward was 1.0 when the view was saved, so it said nothing. The
  job files turn the verifier off, the agent wrapper keeps the final view after the turn, vq-slide-3ptb lists its
  file as a Harbor artifact, and `make view` shows no verifier rewards for the runs of this eval (also the old ones).
- Later: the judge (gpt-6.1-sol), checked against the reviews.
