# playmoleculeai-evals

Evals for PlayMoleculeAI. [Harbor](https://github.com/laude-institute/harbor) starts one container per case, `pmai run` drives the chat inside it, and pytest grades what is left.

```text
harbor run ──► trial container (pmai-eval image)
                 ├─ pmai run --prompt "<instruction.md>"   tools run here, local backend
                 ├─ /logs/agent/home/agent.db              trace, production schema
                 │    └► agent/trajectory.json (host)      the trace in make view (trajectory.py)
                 └─ /tests/test.sh ──► pytest ──► /logs/verifier/reward.json
```

Words: a **case** is one task (a prompt and its checks); a **job file** names cases, the agent and the model; a
**run** is one `make run` of a job file; a **trial** is one case in a run. Viewer cases also get the **sidecar**: a
second container with PMView in headless Chromium, which the agent drives as a user's browser.

## Setup

You need Docker with compose, [uv](https://docs.astral.sh/uv/), rsync, and access to the Acellera image registry: the
image starts from the production sandbox image (`SANDBOX` in the Makefile), so log in once with
`gcloud auth configure-docker europe-southwest1-docker.pkg.dev`. A PMView build also needs Node.js.

The images contain code from other repos. Clone them next to this one:

```text
playmoleculeai-evals/   this repo
playmoleculeAI/         git@github.com:Acellera/playmoleculeAI.git   make image: pmai
acellera-skills/        git@github.com:Acellera/acellera-skills.git  make image: the skills of your local main
pmview/                 git@github.com:Acellera/pmview.git           optional, make viewer: a PMView build
```

`make image` takes what these checkouts have: pull them first. Other folders, branches or a PMView build go in
`local.mk` (not in git), which the Makefile reads:

```make
PMAI = ../playmoleculeAI-my-branch
# the skills working tree, with its changes (default: main)
SKILLS_REF =
# its build/ (npm ci && npm run build there first); empty: the PMView of the site
PMVIEW = ../pmview
```

Then copy `.env.example` to `.env` and add the keys (ask the team for an OpenAI key for evals). All evals need
`OPENAI_API_KEY`. Viewer cases also need internet access and a PlayMolecule account (`PM_EMAIL`, `PM_PASSWORD`) on
`PMVIEW_URL`; your own account does. Its profile must have a country, else PMView opens a dialog that blocks the
viewer. The sidecar uses the account only to log in: it serves the trial's files to PMView itself, so they do not go
to the account.

`uv sync && make test` checks the Python code only (no Docker, keys or checkouts needed). `make help` lists the
commands and their settings.

## Where things are

```text
evals/                        WHAT we test: one folder per eval
├── viewer-quality/           the final PMView image, rated by hand (20 cases)
└── smoke/                    one case: does a run work at all
    each eval has:
    ├── README.md             what it measures, how to run it, its status
    ├── cases/<case>/         one case (a Harbor task, see "Add an eval")
    ├── *.yaml                job files: which cases, agent, model, attempts
    └── ratings/<run>.json    the human reviews of a run (make review)
results/                      WHAT came out: one folder per run (not in git)
docker/                       WHAT runs in the containers
├── eval/Dockerfile           pmai-eval: sandbox + pmai (/opt/pmai) + grader (/opt/grader) + skills
├── viewer/                   pmai-viewer: the sidecar (server.py, Dockerfile, compose.yaml: each viewer case
│                             has a copy)
└── agent_config.yaml         the pmai agent config, baked at /opt/pmai-config
src/pmai_evals/               the Python code
├── agent.py                  the Harbor agent: runs pmai in the trial (host side)
├── trial.py                  what a test asks about a trial: answer, tool calls, cost, viewer
├── reward.py                 pytest plugin: one score per test, reward = mean
├── judge.py                  LLM judge for what code cannot check
├── trajectory.py             the trace in make view
└── review.py, review.html    human review: the review page, and make view's jobs
scripts/watch.py              make watch
tests/                        unit tests (make test)
docs/implementation-plan.md   the status and the next steps
```

## Run

```bash
make image                        # pmai-eval:latest: again after a change to pmai, the skills, src/ or docker/
make viewer                       # pmai-viewer:latest, for viewer cases only
make run JOB=evals/viewer-quality/train.yaml
make run JOB=evals/viewer-quality/train.yaml CASE=vq-pocket-1hsg     # one case only
make watch                        # in a second shell: each call, message and new viewer image
make view                         # browse the results
```

A run pays for its model calls: the 15 viewer-quality train cases cost less than $1 with gpt-6-luna. It writes
`results/<eval>-<job file>[-<case>]-<date>/`; `make run JOB=... NAME=<that folder name>` continues a stopped run
(Harbor keeps its finished trials). Each trial has a folder `<case>__<id>/`:

```text
agent/events.jsonl                pmai's output as it runs (make watch reads it)
agent/trajectory.json, images/    the trace in make view (written after the turn)
artifacts/logs/artifacts/viewer/  viewer cases: final-view.png (kept after the turn), steps/NNN.jpg, events.jsonl
artifacts/<path>                  the files that task.toml lists in `artifacts`
verifier/                         reward.json and the test output (none when the job turns the verifier off)
result.json                       reward, cost, error (written at the end)
```

## Human review

`make review` opens the review page on this machine, on 127.0.0.1:8080 (like `make view`: run one at a time, or set `PORT=`; from another machine, tunnel the port with `ssh -L`). It lists every run in `results/`. For each case it shows the prompt, the images of the trial (the final view first), the answer, cost, time, test scores and the tool calls. You mark each line of the case's `tests/rubric.txt` yes or no, like an exam: the score is the points of the yes lines, out of 10. A case with no rubric gets one line, "The result does what the prompt asks", worth 10. You can add a note. Each click is saved in `evals/<eval>/ratings/<run>.json`, with your user name. A case of a run has one review: a new review replaces the old one, also from another reviewer.

The same page can be a claude.ai artifact, to review away from this machine: ask Claude Code to publish a run there,
and to read the reviews back. It uses these two commands:

```bash
uv run python -m pmai_evals.review collect results/<run> <dir>      # the run's files for the page
uv run python -m pmai_evals.review export <dir of review docs>      # evals/<eval>/ratings/<run>.json
```

In `make view`, the review score is the reward `human_reward` (score / 10): a column in Overview and Rollouts, and a Y axis in Pareto. The run's value is the mean of the reviewed trials only. Overview also shows each run's `cost_usd` and `minutes`. A job file can turn the verifier off (`verifier: {disable: true}`) when the eval has no score yet, as viewer-quality now: then `make view` shows no verifier rewards for any of its runs.

Harbor draws a Pareto chart inside one job, and each `make run` is a new job. So `make view` shows one job for each job file (for example `viewer-quality-train`), with all its runs in it: one row and one Pareto point for each run, named by the run's date (`pmai 10-08 14:56`). A run of one case (`CASE=`) is a job of its own. `make view` builds these jobs in `results/.view/` each time it starts, from hard links to the runs' files (no space). Restart it to see new trials; `make watch` follows a run live.

## Add an eval

```text
evals/<eval>/
├── README.md                 what it measures, how to run it, its status
├── <job>.yaml                copy evals/smoke/hello-file.yaml: set datasets.path to evals/<eval>/cases and keep
│                             the agent name pmai
└── cases/<case>/             one Harbor task
    ├── instruction.md        the user prompt
    ├── task.toml             copy the one of a similar case (viewer cases need more memory and time): set
    │                         name "acellera/<case>" and keywords (the eval name, a category, "holdout" for a
    │                         held-out case)
    ├── environment/          no input files: an empty .gitkeep, and docker_image = "pmai-eval:latest" in
    │                         task.toml. Input files: a Dockerfile (FROM pmai-eval:latest, COPY ... /app/) and no
    │                         docker_image, else Harbor uses the image and skips the Dockerfile
    └── tests/
        ├── test.sh           PYTHONPATH=/opt exec /opt/grader/bin/pytest /tests -q -p pmai_evals.reward
        ├── test_case.py      the checks: each test is one score from 0 to 1, the reward is their mean
        │                     (a skipped test does not count)
        └── rubric.txt        optional, for human review: "<points> <criterion>" a line, whole points, 10 in all
```

A viewer case also has `environment/docker-compose.yaml`, a copy of `docker/viewer/compose.yaml`, and under
`[environment]` in `task.toml` the structures to open before the turn (or `""` for none):

```toml
env = { VIEWER_PRELOAD = "{\"pdb_ids\": [\"1HSG\"]}" }
```

The viewer-quality cases have only a rubric, no tests: their job files turn the verifier off. `make test` checks the
cases and the job files: each task.toml parses and has one image, viewer cases have the current compose copy, the job
files find their cases, a scored case has `tests/test.sh`, and each rubric adds up to 10. Give a crucial rubric line
many points (5 or 6): if it fails, the score is bad.

What a test can ask (`src/pmai_evals/trial.py`, `reward.py`, `judge.py`):

```python
from pmai_evals import trial
from pmai_evals.judge import judge
from pmai_evals.reward import InfraError, partial

trial.WORK                      # the agent's working folder
trial.answer()                  # its last message; trial.tag("answer") is the text in <answer>...</answer>
trial.tool_calls("name")        # its tool calls (all when no name); trial.tool_errors(): the failed ones
trial.usage()                   # tokens and cost_usd
trial.final_image()             # viewer cases: the final view, a PNG
trial.viewer_python("code")     # viewer cases: run code in PMView, as the agent's pmview_python
judge("criterion", files=[...], text="...")   # True or False (gpt-6.1-sol), the reason in /logs/verifier/judge.md
partial(0.5)                    # this test scores 0.5, not pass or fail
raise InfraError("...")         # the setup failed, not the agent: no reward, not a 0
```

A test that calls `judge` needs the key in the verifier too. In the job file:

```yaml
verifier:
  env:
    OPENAI_API_KEY: ${OPENAI_API_KEY}
```

The smoke case (`evals/smoke/cases/hello-file/tests/test_case.py`):

```python
from pmai_evals import trial


def test_file():
    assert (trial.WORK / "hello.txt").read_text().strip() == "hello from pmai"


def test_answer():
    assert trial.tag() == "done"


def test_no_tool_errors():
    assert not trial.tool_errors()
```

## Grade a hand run (no Docker)

`trial.py` reads `$TRIAL_LOGS` (default `/logs/agent`), so a test can run against a local `pmai run`. You need pmai
on your PATH (from your playmoleculeAI checkout) and `OPENAI_API_KEY` in the shell. The turn costs model calls, and
the agent's tools run on your machine, in `/tmp/t/app`:

```bash
mkdir -p /tmp/t/logs/home /tmp/t/app && cp docker/agent_config.yaml /tmp/t/logs/home/
echo /tmp/t/app > /tmp/t/logs/work_dir
# PMAI_HOME: pmai's home for this run (else a source checkout takes it from playmoleculeAI/.env)
(cd /tmp/t/app && PMAI_HOME=/tmp/t/logs/home pmai run --config /tmp/t/logs/home --model gpt-6-luna \
  --output json --prompt "$(cat evals/smoke/cases/hello-file/instruction.md)" > /tmp/t/logs/events.jsonl)
TRIAL_LOGS=/tmp/t/logs REWARD_JSON=/tmp/t/reward.json \
  uv run pytest evals/smoke/cases/hello-file/tests -q -p pmai_evals.reward && cat /tmp/t/reward.json
```

To grade a Harbor trial again, set `TRIAL_LOGS=<trial>/agent`. A viewer task then reads the final view in `<trial>/artifacts/logs/artifacts/viewer/final-view.png` and needs no viewer. A test that reads `trial.WORK` cannot run again: Harbor does not keep `/app`, only the files that task.toml lists in `artifacts`.
