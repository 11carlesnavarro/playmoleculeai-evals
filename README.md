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
└── review.py, review.html    human review: a run on the review page, and the reviews back
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
artifacts/logs/artifacts/viewer/  viewer cases: final-view.png (kept after the turn), steps/NNN.jpg, events.jsonl
artifacts/<path>                  the files that task.toml lists in `artifacts`
verifier/                         reward.json and the test output (none when the job turns the verifier off)
result.json                       reward, cost, error (written at the end)
```

## Human review

`make review` opens the review page on this machine (port 8080, like `make view`: run one at a time, or set `PORT=`). It lists every run in `results/`. For each case it shows the prompt, the images of the trial (the final view first), the answer, cost, time, test scores and the tool calls. You mark each line of the case's `tests/rubric.txt` yes or no, like an exam: the score is the points of the yes lines, out of 10. A case with no rubric gets one line, "The result does what the prompt asks", worth 10. You can add a note. Each click is saved in `evals/<eval>/ratings/<run>.json`.

The same page is also on claude.ai (https://claude.ai/artifact/HnJ572pU7neDbMSdmAUtnG, private to you), to review away from this machine. There Claude publishes the run and reads the reviews back:

```bash
uv run python -m pmai_evals.review collect results/<run> <dir>   # Claude publishes <dir> with the page
uv run python -m pmai_evals.review export <dir of review docs>    # evals/<eval>/ratings/<run>.json + summary
```

In `make view`, the review score is the reward `human_reward` (score / 10): a column in Overview and Rollouts, and a Y axis in Pareto. The run's value is the mean of the reviewed trials only. Overview also shows each run's `cost_usd` and `minutes`. A job file can turn the verifier off (`verifier: {disable: true}`) when the eval has no score yet, as viewer-quality until its judge: then `make view` shows no verifier rewards for any of its runs.

Harbor draws a Pareto chart inside one job, and each `make run` is a new job. So `make view` shows one job for each job file (for example `viewer-quality-train`), with all its runs in it: one row and one Pareto point for each run, named by the run's date (`pmai 10-08 14:56`). It builds these jobs in `results/.view/` each time it starts, from hard links to the runs' files (no space). Restart `make view` to see new trials; `make watch` follows a run live.

`tests/rubric.txt`: what a good result shows, one `<points> <criterion>` a line, the points add up to 10. Give a crucial line many points (5 or 6): if it fails, the score is bad.

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

To grade a Harbor trial again, set `TRIAL_LOGS=<trial>/agent`. A viewer task then reads the final view in `<trial>/artifacts/logs/artifacts/viewer/final-view.png` and needs no viewer.
