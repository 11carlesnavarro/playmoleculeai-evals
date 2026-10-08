# playmoleculeai-evals

Evals for PlayMoleculeAI. [Harbor](https://github.com/laude-institute/harbor) starts one container per case, `pmai run` drives the chat inside it, and pytest grades what is left.

```text
harbor run ──► trial container (pmai-eval image)
                 ├─ pmai run --prompt "<instruction.md>"   tools run here, local backend
                 ├─ /logs/agent/home/agent.db              trace, production schema
                 │    └► agent/trajectory.json (host)      the trace in make view (trajectory.py)
                 └─ /tests/test.sh ──► pytest ──► /logs/verifier/reward.json
```

## Where things are

```text
evals/                        WHAT we test: one folder per eval
├── viewer-quality/           the final PMView image, rated by hand (20 cases)
├── acellera-bench/           40 cases from the old harness, graded by code
└── smoke/                    one case: does a run work at all
    each eval has:
    ├── README.md             what it measures, how to run it, its status
    ├── cases/<case>/         one case (a Harbor task, see "A case" below)
    └── *.yaml                job files: which cases, agent, model, attempts
results/                      WHAT came out: one folder per run (not in git)
docker/                       WHAT runs in the containers
├── eval/Dockerfile           pmai-eval: sandbox + pmai (/opt/pmai) + grader (/opt/grader) + skills
├── viewer/                   pmai-viewer: the PMView site in headless Chromium, next to the trial
│                             (server.py, Dockerfile, compose.yaml: each viewer case has a copy)
└── configs/<name>/           pmai agent configs, baked at /opt/pmai-config
src/pmai_evals/               the Python code
├── agent.py                  the Harbor agent: runs pmai in the trial (host side)
├── trial.py                  what a test asks about a trial: answer, tool calls, cost, viewer
├── reward.py                 pytest plugin: one score per test, reward = mean
├── judge.py                  LLM judge for what code cannot check
├── trajectory.py             the trace in make view
└── legacy.py                 the old checks.py functions (acellera-bench)
scripts/                      watch.py (make watch), eval_account.py (the eval account)
tests/                        unit tests (make test)
docs/implementation-plan.md   the work list and the status
```

## Run

```bash
cp .env.example .env              # add the keys
make image                        # pmai-eval:latest (needs Docker and ../playmoleculeAI)
make viewer                       # pmai-viewer:latest, for viewer cases only
make run JOB=evals/viewer-quality/train.yaml
make run JOB=evals/viewer-quality/train.yaml CASE=vq-pocket-1hsg     # one case only
make watch                        # in a second shell: each call, message and new viewer image
make view                         # browse the results
```

A run writes `results/<eval>-<job file>-<date>/`, with one folder for each trial (`<case>__<id>/`):

```text
agent/events.jsonl                pmai's output as it runs (make watch reads it)
agent/trajectory.json, images/    the trace in make view (written after the turn)
artifacts/logs/artifacts/viewer/  viewer cases: final-view.png, steps/NNN.jpg, events.jsonl
verifier/                         reward.json and the test output
result.json                       reward, cost, error (written at the end)
```

## A case

```text
evals/smoke/cases/hello-file/
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
mkdir -p /tmp/t/logs/home /tmp/t/app && cp docker/configs/default/agent_config.yaml /tmp/t/logs/home/
echo /tmp/t/app > /tmp/t/logs/work_dir
# PMAI_HOME: a source checkout of pmai else takes it from playmoleculeAI/.env
(cd /tmp/t/app && PMAI_HOME=/tmp/t/logs/home pmai run --config /tmp/t/logs/home --model gpt-6-luna \
  --output json --prompt "$(cat evals/smoke/cases/hello-file/instruction.md)" > /tmp/t/logs/events.jsonl)
TRIAL_LOGS=/tmp/t/logs REWARD_JSON=/tmp/t/reward.json \
  uv run pytest evals/smoke/cases/hello-file/tests -q -p pmai_evals.reward && cat /tmp/t/reward.json
```

To grade a Harbor trial again, set `TRIAL_LOGS=<trial>/agent`. A viewer task then reads the viewer snapshot in `<trial>/artifacts/logs/artifacts/viewer/snapshot/` and needs no viewer (old checks also need `uv run --with "moleculekit<1.12"`).
