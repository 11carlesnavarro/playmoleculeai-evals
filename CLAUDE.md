# playmoleculeai-evals

Evals for playmoleculeAI. Harbor runs `pmai run` in one container per case, and pytest grades the trial. The work list is `docs/implementation-plan.md`. The README shows the layout and the commands.

## Commands

- `make test`, `make lint`: unit tests and ruff (no Docker).
- `make image`: pmai-eval:latest (needs Docker and `../playmoleculeAI`). `make viewer`: pmai-viewer:latest (viewer tasks).
- `make run JOB=experiments/smoke.yaml`, `make view`.
- Grade a hand run without Docker: `TRIAL_LOGS=<logs dir> REWARD_JSON=<file> uv run pytest tasks/<set>/<case>/tests -p pmai_evals.reward` (see the README).

## Relevant paths

- **playmoleculeAI agentic code** (harness, agents, prompts, skills): `/fast_shared/users/carles/repos/carles/playmoleculeAI`
- **acellera skills**: `/fast_shared/users/carles/repos/acellera/acellera-skills`
- **pmbackend** (reference only, we do not change it): `/fast_shared/users/carles/repos/carles/pmbackend`
- **playmolecule-viewer** (PMView frontend, reference only, we do not change it): `/fast_shared/users/carles/repos/carles/pmview`
- **SQLite databases with traces**: `/fast_shared/users/carles/data/playmoleculeAIdata/data/databases`
    - dev: `/fast_shared/users/carles/data/playmoleculeAIdata/data/databases/dev/agent.db`
- **Analysis dashboard** (reference for reading data from the databases): `/fast_shared/users/carles/data/playmoleculeAIdata/dashboard`
- **playmolecule-tests** (tests and examples for running via Playwright from the browser): `/fast_shared/users/carles/repos/acellera/playmolecule-tests`
- **Old harness and old run results** (removed from the repo on 2026-10-05): `/fast_shared/users/carles/data/playmoleculeAIdata/evals-archive-2026-10-05`

## Notes

- `eval_sets/` is the old case format, kept for the port (phase 2). Its `checks.py` files import old modules that are now in the archive; the port rewrites them to `pmai_evals.legacy`.
- `src/pmai_evals/trial.py`, `reward.py` and `judge.py` run in the grader venv in the image: keep `trial.py` and `reward.py` stdlib only.
