# playmoleculeai-evals

Evals for playmoleculeAI. Harbor runs `pmai run` in one container per case, and pytest grades the trial. The status and the next steps are in `docs/implementation-plan.md`. The README shows the layout and the commands: one folder per eval in `evals/<eval>/` (README.md, `cases/<case>/` = Harbor tasks, `*.yaml` = job files), container parts in `docker/`, run results in `results/`.

## Commands

- `make test`, `make lint`: unit tests and ruff (no Docker).
- `make image`: pmai-eval:latest (needs Docker, and the checkouts of the README Setup or `local.mk`). `make viewer`: pmai-viewer:latest (viewer cases), with the PMView build of `PMVIEW` (empty: the site's PMView).
- `make review` (the review page on port 8080, all runs; reviews saved in `evals/<eval>/ratings/<run>.json`); `make view` shows them as `human_reward`.
- `make run JOB=evals/<eval>/<job>.yaml [CASE=<case>]`, `make watch` (live), `make view` (shows `results/.view/`, built at each start: one job for each job file, each run one row and one Pareto point, hard links).
- Grade a hand run without Docker: `TRIAL_LOGS=<logs dir> REWARD_JSON=<file> uv run pytest evals/<eval>/cases/<case>/tests -p pmai_evals.reward` (see the README).

## Notes

- Keep the layout simple: a new eval gets its own folder in `evals/` with a README (what it measures, how to run it, its status). Update that README when the status changes.
- Working notes and local tools stay in the repo but out of git (see `.gitignore`): `evals/<eval>/proposals/`, `evals/<eval>/judge/`, `local.mk`, `CLAUDE.local.md`.
- Runs and judge calls cost money: give the cost and ask before you start one.
- Human review: `make review` (local). `make view` reads `evals/<eval>/ratings/` (the reward `human_reward`).
- `src/pmai_evals/trial.py`, `reward.py` and `judge.py` run in the grader venv in the image: keep `trial.py` and `reward.py` stdlib only.
