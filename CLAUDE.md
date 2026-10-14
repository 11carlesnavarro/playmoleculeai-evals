# playmoleculeai-evals

Evals for playmoleculeAI. Harbor runs `pmai run` in one container per case, and pytest grades the trial. The work list is `docs/implementation-plan.md`. The README shows the layout and the commands: one folder per eval in `evals/<eval>/` (README.md, `cases/<case>/` = Harbor tasks, `*.yaml` = job files), container parts in `docker/`, run results in `results/`.

## Commands

- `make test`, `make lint`: unit tests and ruff (no Docker).
- `make image`: pmai-eval:latest (needs Docker and `../playmoleculeAI`). `make viewer`: pmai-viewer:latest (viewer cases), with the PMView build of `PMVIEW` (empty: the site's PMView).
- `make review` (the review page on port 8080, all runs; reviews saved in `evals/<eval>/ratings/<run>.json`); `make view` shows them as `human_reward`.
- `make run JOB=evals/<eval>/<job>.yaml [CASE=<case>]`, `make watch` (live), `make view` (shows `results/.view/`, built at each start: one job for each job file, each run one row and one Pareto point, hard links).
- Grade a hand run without Docker: `TRIAL_LOGS=<logs dir> REWARD_JSON=<file> uv run pytest evals/<eval>/cases/<case>/tests -p pmai_evals.reward` (see the README).

## Relevant paths

- **playmoleculeAI agentic code** (harness, agents, prompts, skills): `/fast_shared/users/carles/repos/carles/playmoleculeAI`
    - hill climb worktree (branch viewer-quality, from main e7db8d07, a worktree of the clone `playmoleculeAI-2`): `/fast_shared/users/carles/repos/carles/playmoleculeAI-2-viewer-quality`
- **acellera skills**: `/fast_shared/users/carles/repos/acellera/acellera-skills`
    - hill climb worktree (branch viewer-quality, from main 3100e83): `/fast_shared/users/carles/repos/acellera/acellera-skills-viewer-quality`
    - `make image` builds from the two worktrees now (Makefile PMAI, SKILLS, SKILLS_REF empty = the skills working tree). Both worktrees are group slpm, so slurmweb can build.
- **pmbackend** (reference only, we do not change it): `/fast_shared/users/carles/repos/carles/pmbackend`
- **playmolecule-viewer** (PMView frontend): `/fast_shared/users/carles/repos/carles/pmview` is the user's checkout: read only, never change it.
    - hill climb worktree (branch viewer-quality, from main 2d6c8c4): `/fast_shared/users/carles/repos/carles/pmview-viewer-quality`. Changes go here; then `npm run build` (as carles, node is in carles's PATH), and `make viewer` bakes its `build/` in pmai-viewer. The sidecar still opens the deployed site (backend, login) and serves only the PMView files from the build.
- **SQLite databases with traces**: `/fast_shared/users/carles/data/playmoleculeAIdata/data/databases`
    - dev: `/fast_shared/users/carles/data/playmoleculeAIdata/data/databases/dev/agent.db`
- **Analysis dashboard** (reference for reading data from the databases): `/fast_shared/users/carles/data/playmoleculeAIdata/dashboard`
- **playmolecule-tests** (tests and examples for running via Playwright from the browser): `/fast_shared/users/carles/repos/acellera/playmolecule-tests`
- **Old harness, old run results and the bixbench cases and data** (removed from the repo on 2026-10-05 and 2026-10-08): `/fast_shared/users/carles/data/playmoleculeAIdata/evals-archive-2026-10-05`

## Notes

- Keep the layout simple: a new eval gets its own folder in `evals/` with a README (what it measures, how to run it, its status). Update that README when the status changes.
- Human review: `make review` (local, no publish or export). Or the claude.ai page: https://claude.ai/artifact/HnJ572pU7neDbMSdmAUtnG (source `src/pmai_evals/review.html`, db collections `runs` and `ratings`). To add a run: `python -m pmai_evals.review collect results/<run> <scratchpad>/review`, publish review.html to that url with the run's files (root = that dir, not the `*.db.json`), then ArtifactData set `runs/<run>` from `<run>.db.json`. To read reviews: ArtifactData list `ratings` with out_dir, then `review export <out_dir>`. `make view` reads `evals/<eval>/ratings/` (the reward `human_reward`). A version holds at most 511 files: remove the files of runs already exported.
- `src/pmai_evals/trial.py`, `reward.py` and `judge.py` run in the grader venv in the image: keep `trial.py` and `reward.py` stdlib only.
