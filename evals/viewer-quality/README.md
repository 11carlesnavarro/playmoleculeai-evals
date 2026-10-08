# Viewer quality

Does PlayMoleculeAI make a good PMView view? Each case is a viewer request from a real chat (dev, prod and open trace DBs). The score is the final view, as the user sees it. Cost, time and tool calls come from the trace. The goal is to hill climb: find what makes the views bad (the skill, the tools, PMView or the model) and fix it.

Plan page: https://claude.ai/artifact/Jy2kpxN4vz6aAkGjhQZZYH

## Files

```text
cases/<case>/instruction.md       the prompt (starts with "Use the viewer.")
cases/<case>/tests/rubric.txt     what a good view shows; line 1 is the gate: if it fails, the view fails
cases/<case>/tests/test_case.py   saves final-view.png; the reward says only that it was saved
cases/<case>/task.toml            keywords (category, "holdout"), source chats, VIEWER_PRELOAD
train.yaml                        job: the 15 hill climbing cases
holdout.yaml                      job: the 5 held-out cases, only to check that a gain is real
```

## Run

```bash
make image && make viewer          # after a change to src/ or docker/
make run JOB=evals/viewer-quality/train.yaml                       # 15 cases, gpt-6-luna: less than $1
make run JOB=evals/viewer-quality/train.yaml CASE=vq-pocket-1hsg   # one case
```

The image to rate: `results/<run>/<case>__<id>/artifacts/logs/artifacts/viewer/final-view.png`. The views during the turn are in `steps/` in the same folder (only the views that changed).

## Score

1. Now: you rate each final view by hand against its rubric.
2. Then: a judge (gpt-6.1-sol) sees the same image and rubric. We keep it only if it agrees with your ratings.

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
| vq-labels-6lu7 | labels | |
| vq-pocket-1hsg | pocket | |
| vq-pocket-1m17 | pocket | |
| vq-poses-1iep | poses (input file) | |
| vq-resistance-1m17 | residues | |
| vq-slide-3ptb | figure (also saves figures/benzamidine.png) | |
| vq-surface-1a52 | surface | |

## Status

- 2026-10-08: the 20 cases are done. One test run of vq-pocket-1hsg worked (reward 1.0: the view was saved).
- Next: the baseline run of train.yaml, then a page where you rate the images.
