# playmoleculeai-evals

Evals for PlayMoleculeAI. [Harbor](https://github.com/laude-institute/harbor) starts one container per case, `pmai run` drives the chat inside it, and pytest grades what is left.

```text
harbor run ──► trial container (pmai-eval image)
                 ├─ pmai run --prompt "<instruction.md>"   tools run here, local backend
                 ├─ /logs/agent/home/agent.db              trace, production schema
                 └─ /tests/test.sh ──► pytest ──► /logs/verifier/reward.json
```

## Run

```bash
cp .env.example .env              # add the keys
make image                        # pmai-eval:latest (needs Docker and ../playmoleculeAI)
make run JOB=experiments/smoke.yaml
make view                         # results in jobs/<job file>-<date>/
uv run python scripts/compare_old.py jobs/<job>   # old harness vs new, per case
```

## Layout

```text
image/Dockerfile                  sandbox image + pmai (/opt/pmai) + grader (/opt/grader) + skills
config/<name>/agent_config.yaml   pmai configs, baked at /opt/pmai-config
src/pmai_evals/agent.py           the Harbor agent (host side)
src/pmai_evals/trial.py           what a test asks about a trial: answer, tool calls, cost
src/pmai_evals/reward.py          pytest plugin: one score per test, reward = mean
src/pmai_evals/judge.py           LLM judge for what code cannot check
src/pmai_evals/legacy.py          runs the old eval_sets checks.py functions unchanged
tasks/<set>/<case>/               the cases: instruction.md, task.toml, environment/, tests/
experiments/*.yaml                Harbor job files: datasets x agents (config, skills) x models
scripts/cases_to_tasks.py         one time port: eval_sets/<set> -> tasks/<set>
scripts/compare_old.py            a job against the old harness runs (archive)
scripts/eval_account.py           the eval account on the dev backend: signup, verify, check
eval_sets/                        the old case format; removed set by set after its port is compared
docs/implementation-plan.md       the work list, phase by phase
```

## A case

```text
tasks/smoke/hello-file/
├── instruction.md        the user prompt
├── task.toml             image, timeouts, network
├── environment/          input files (Dockerfile FROM pmai-eval:latest + COPY), else .gitkeep
└── tests/
    ├── test.sh           PYTHONPATH=/opt exec /opt/grader/bin/pytest /tests -q -p pmai_evals.reward
    └── test_case.py
```

```python
from pmai_evals import trial
from pmai_evals.judge import judge


def test_file():
    assert (trial.WORK / "hello.txt").read_text().strip() == "hello from pmai"


def test_answer_is_clear():
    assert judge("Says that the file exists.", text=trial.answer())
```

## Grade a hand run (no Docker)

`trial.py` reads `$TRIAL_LOGS` (default `/logs/agent`), so a test can run against a local `pmai run`:

```bash
mkdir -p /tmp/t/logs/home /tmp/t/app && cp config/default/agent_config.yaml /tmp/t/logs/home/
echo /tmp/t/app > /tmp/t/logs/work_dir
# PMAI_HOME: a source checkout of pmai else takes it from playmoleculeAI/.env
(cd /tmp/t/app && PMAI_HOME=/tmp/t/logs/home pmai run --config /tmp/t/logs/home --model gpt-6-luna \
  --output json --prompt "$(cat tasks/smoke/hello-file/instruction.md)" > /tmp/t/logs/events.jsonl)
TRIAL_LOGS=/tmp/t/logs REWARD_JSON=/tmp/t/reward.json \
  uv run pytest tasks/smoke/hello-file/tests -q -p pmai_evals.reward && cat /tmp/t/reward.json
```
