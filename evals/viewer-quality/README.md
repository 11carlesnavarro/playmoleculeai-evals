# Viewer quality

Does PlayMoleculeAI make a good PMView view? Each case is a viewer request from a real chat (dev, prod and open trace DBs). The score is the final view, as the user sees it. Cost, time and tool calls come from the trace. The goal is to hill climb: find what makes the views bad (the skill, the tools, PMView or the model) and fix it.

## Files

```text
cases/<case>/instruction.md       the prompt (starts with "Use the viewer.")
cases/<case>/tests/rubric.txt     what a good view shows: "<points> <criterion>" a line, 10 points in all
cases/<case>/task.toml            keywords (category, "holdout"), source chats, VIEWER_PRELOAD, a file the prompt asks for
train.yaml                        job: the 15 hill climbing cases
holdout.yaml                      job: the 5 held-out cases, only to check that a gain is real
ratings/<run>.json                your reviews of a run (from the review page)
```

## Run

```bash
make image && make viewer          # after a change to src/, docker/ or the checkouts (README, Setup)
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

The hill climb (rounds 1 to 10) changed PMAI, the skills and PMView on a branch `viewer-quality` of each (PMAI
from main e7db8d07, acellera-skills from main 3100e83, PMView from main 2d6c8c4). The branches are not pushed yet:
a build from main gives round 0. All runs: gpt-6-luna, one attempt, the 15 train cases; the score is the mean of
the reviews (0 to 10).

| Round | Run (`viewer-quality-train-`) | Score | Cost | Main change |
|---|---|---|---|---|
| 0 | 20261008-145621 | 5.93 | $0.41 | baseline: production PMAI, skills and PMView |
| 1 | 20261009-122438 | 5.87 | $0.38 | the agent looks at the view (screenshot) and corrects it |
| 2 | 20261009-143543 | 7.00 | $0.37 | pmview skill rewritten from the round 1 traces |
| 3 | 20261009-165017 | 7.07 | $0.40 | PMView build in the sidecar: `size=1` is normal, camera calls |
| 4 | 20261009-181219 | 8.33 | $0.33 | the trial project opens; pocket surface, labels |
| 5 | 20261013-160804 | 6.73 | $0.37 | the whole canvas in the screenshot (round 4 rated a larger render) |
| 6 | 20261013-184940 | 7.40 | $0.41 | 2560 × 1440 window; show only what the user asks |
| 7 | 20261014-115559 | 9.07 | $0.32 | `pmview_python` returns the view; `pmv.visible`, interactions |
| 8 | 20261014-150617 | 8.07 (14 cases) | $0.36 | camera by name (azimuth, elevation, roll), Mol* params |
| 9 | 20261014-192525 | 9.20 | $0.22 | camera kept, focus frames, the whole viewport |
| 10 | 20261015-113920 | not reviewed | $0.32 | framing of SDF and trajectories; molecule colours from the palette skill |

Round 10 is the last round of this kind. Next: the judge, checked against these reviews, and final runs of the
first and the current versions (see `docs/implementation-plan.md`).

Notes:
- vq-covalent-6oim asks for the view, not "a high-quality figure", since round 3; vq-labels-6lu7 became
  vq-labels-3hs4 in round 4 (OpenAI stopped the old prompt as biological risk).
- No Harbor reward until the judge: the job files turn the verifier off, and the trial keeps its final view.
