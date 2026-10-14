# Implementation plan: PMAI evals on Harbor

The plan page shows the idea. This file is the work list. Do the phases in order. Each phase ends with something that runs.

| Phase | Result | Changes outside this repo |
|---|---|---|
| 0 | Tooling: Harbor installed, `make run` works | none |
| 1 | One case runs in Docker with Harbor and gets a reward | none |
| 2 | Four acellera-bench sets run with their old checks, unchanged | none |
| 3 | Models, configs and skills compared in one job | none |
| 4 | Eval account on the dev backend | one account (one time) |
| 5 | Viewer tasks: PMView sidecar, molecular-visualization ported | PMAI: `--viewer-id`, `--serve` (done) |
| 6 | PlayMolecule job tasks | PMAI: `--user`, `--wait-jobs` |
| 7 | Scale out, nightly run | none |

Facts checked in the code (Harbor 0.24.0 source, pmbackend, pmview, playmoleculeAI) are marked `[checked]`. Points to try first are marked `[verify]`.

## Layout

The README has the map of the repo. Since 2026-10-08, each eval has one folder in `evals/` (its cases, its job files and a README), the container parts are in `docker/`, and run results go to `results/`.

---

## Status (2026-10-08)

- Phases 0 and 1 are done. The files are the reference. The two sections below give only the changes from the first plan and the checks.
- Phase 2: 40 tasks ported, and the port gives the old scores on 480 old trials. In Docker, `acellera-sample` (one case per set, gpt-6-luna) gave reward 1.0 on 4 of 4 trials, for less than $0.01.
- `make image`, `make run` and `make view` work (run by the user as `slurmweb`, 2026-10-05). The first smoke trial got no reward:
  the `.env` OpenAI key is archived (401), and then `populate_context_post_run` crashed on the read only `agent.db`, which stopped the trial before the verifier. Both causes are known; the crash is fixed. Run the smoke job again with a working key.
- Phase 3: done. `sa-models` and `skills-ab` ran in Docker (results in the phase 3 section). The image now has the skills (it had none before).
- Phase 4: done. The eval account is `carles` (the user's account, `PM_EMAIL` in `.env`); `scripts/eval_account.py check` logs in on the dev backend.
- Phase 5: `pmai run --viewer-id` is in playmoleculeAI. The sidecar opens the deployed PMView site; the image, the compose file, the agent script change and the `trial.py` viewer functions are done, with unit tests. The 5.8 try passed on computer19 against production, with one pmai turn (2026-10-07). 5.7: molecular-visualization is ported (10 tasks, preload, field adapter); the grading path passed against production with no model. `evals/acellera-bench/viewer.yaml` on Harbor (2026-10-08): mv-1jpz, mv-2ity and mv-7fab all reward 1.0, about $0.003 a turn. 5.9: the trace in `make view`. Next: the full set (10 tasks).
- Viewer quality (2026-10-08): 20 cases in `evals/viewer-quality/cases`, from the trace mining. Next: the baseline run, then the user rates the images.
- Human review (2026-10-08): `src/pmai_evals/review.py` and `review.html`, one review page for any eval run (README, "Human review"). The baseline viewer-quality run is on it.
- New layout (2026-10-08): `tasks/` and `experiments/` became `evals/<eval>/cases/` and `evals/<eval>/*.yaml`; `image/`, `viewer/` and `config/` are in `docker/`; `jobs/` is `results/`. `eval_sets/` and the port scripts (`cases_to_tasks.py`, `legacy_test_case.py`, `compare_old.py`) are removed: they are in git history. Paths in the done phases below use the new names.
- acellera-bench is removed (2026-10-13): its 50 cases with their old `checks.py`, `legacy.py` and its test. Its code checks gave 1.0 to views that nobody can read; viewer-quality grades the image. All of it is in git history (commit 16d8fca). The grader venv no longer installs pandas, rdkit and moleculekit, which only the old checks used. The phases below keep their old paths.
- The old harness is removed. All of it is in `/fast_shared/users/carles/data/playmoleculeAIdata/evals-archive-2026-10-05/`:
  - `repo-before-cleanup.tar.gz`: the repo before the cleanup (old src, tests, scripts, mining, development, docs, playwright). Not in it: `.env`, `playwright/.auth`, `.venv`, `.git`, bixbench fixtures.
  - `runs/`: the old run results (34 GB), the baseline for phase 2.
  - `git-head.txt`, `git-status.txt`.
  - `eval_sets/`: bixbench and bixbench-verified, cases and fixtures (22 GB), moved here on 2026-10-08 for the bixbench port.

## Phase 0. Tooling (done)

Files: `pyproject.toml`, `uv.lock`, `.env.example`, `.gitignore`, `.dockerignore`, `Makefile`.

Changes from the first plan:
- `pyproject.toml` is new, with one dependency: `harbor==0.24.0`. `anthropic`, `pytest` and `ruff` are dev only, because `judge.py` runs in the image.
- `.dockerignore` sends only `dist/`, `docker/` and `src/` to the build (the repo once had 22 GB of bixbench data).
- `make image` builds the PMAI sdist first, then the wheel from it. A direct `uv build --wheel` reuses `playmoleculeAI/build/lib`, which still has `agents/builtin/{researcher,reviewer,scout}` (deleted from src). Then pmai fails on start: `researcher/AGENT.md: description: Unexpected keyword argument`.
- `make lint` is new. `make viewer`: phase 5.
- `make run` exports `.env`, because Harbor reads `${VAR}` in job files from the process env `[checked]`. `HARBOR_TELEMETRY=off`: telemetry is on by default and sends job ids, models and cost.

Checked: `uv run harbor --version` prints 0.24.0. `make -n` for all targets.

## Phase 1. Walking skeleton (done, smoke reward in Docker still to see)

Files: `docker/configs/default/agent_config.yaml`, `docker/eval/Dockerfile`, `src/pmai_evals/{agent,trial,reward,judge}.py`, `evals/smoke/cases/hello-file/`, `evals/smoke/hello-file.yaml`, `tests/`.

Changes from the first plan:
- `docker/configs/default`: `config_version: 1`. Without it, pmai rewrites the file on start and keeps a `.v0.bak`. No `codebase_search` and no `literature`: both start, but their tools fail in the container (no `SEARCH_URL` service, no literature data). Phase 3 can add them again with `SEARCH_URL` in the job env, if the container can reach the service.
- `agent.py`: `--model` only when the job sets a model. Else pmai uses the default of the config.
- `trial.py`: `TRIAL_LOGS` (default `/logs/agent`) sets the folder of `home/agent.db` and `work_dir`. With it, the task tests grade a hand run on the host (see the README).
- `judge.py`: the request streams, with adaptive thinking. An empty answer is FAIL.
- `evals/smoke/hello-file.yaml`: `${ANTHROPIC_API_KEY:-}`. Harbor stops the job when a `${VAR}` is not set `[checked]`, and the smoke task has no judge.
- On the host, the trial files from the container belong to `nobody` (NFS root squash). `agent.db` is in WAL mode, so a reader must create `agent.db-shm`: `trial.q` reads a copy when the folder is read only. The agent script makes `/logs/agent` writable on exit, so the host user can delete `results/`. `populate_context_post_run` never raises: Harbor calls it before the verifier.
- Unit tests: also `test_agent.py` (the script and `populate_context_post_run`) and `test_judge.py` (a fake client). `test_reward.py` also checks that a setup error gives 0.

Checked:

| Check | Result |
|---|---|
| `make test`, `make lint` | 7 passed, clean |
| `Task.is_valid_dir`, `JobConfig` with `extra="forbid"`, agent class, preflight, dataset tasks | all OK |
| Agent script: `bash -n`, and the viewer probe with no sidecar | OK; the probe fails in 0.2 s, no extra flags |
| `pmai run` from the PMAI source venv, `docker/configs/default`, smoke prompt | exit 0, `hello.txt` OK, 45 events |
| `pmai run` from the wheel, in a new Python 3.12 venv, outside the source tree | exit 0 |
| Smoke tests on both runs with `TRIAL_LOGS`, also in a venv with only pytest | reward 1.0 |
| `populate_context_post_run` on the real `agent.db` | 6334 in, 3145 cached, 47 out, $0.00037 |

Hand run gotchas:
- From the PMAI source tree, `load_dotenv()` loads `playmoleculeAI/.env`, which sets `PMAI_HOME=/home/slurmweb/...`. Set `PMAI_HOME` yourself. The image installs the wheel, so this does not occur there.
- The `OPENAI_API_KEY` in the `.env` of this repo is from an archived OpenAI project (401 `not_authorized_invalid_project`). Put a working key there before `make run`.

Next:

```bash
docker run --rm $SANDBOX id        # [verify] not root: restore USER in docker/eval/Dockerfile
make image && docker run --rm pmai-eval:latest pmai --help
make run JOB=evals/smoke/hello-file.yaml && make view
```

**Done when:** `harbor view` shows hello-file with reward 1.0, tokens and cost.

---

## Phase 2. Port the eval sets with the old checks (done)

Only `molecular-visualization` reads viewer data (`viewer_state`, `viewer_selection`, `load_system`) `[checked]`. The other four acellera-bench sets read only the final answer and the project files. They run now, without a viewer.

Behaviour note: in these runs the viewer tools are offered but fail with "No viewer is connected" `[checked]`. The agent uses moleculekit in bash. Phase 5 runs them again with the viewer.

Files: `src/pmai_evals/legacy.py`, `scripts/legacy_test_case.py`, `scripts/cases_to_tasks.py`, `scripts/compare_old.py`, `evals/acellera-bench/{sample,noviewer}.yaml`, `evals/acellera-bench/cases/{structure-analysis,cheminformatics-analysis,retrieval-and-selection,3d-reasoning}/` (40 tasks), `tests/test_legacy.py`.

Changes from the first plan:
- `legacy.py` has only what these four sets use: `PYTHON_CHECK_TYPE`, `AssertionResult`, `RunArtifact` (`project_files_dir`, `final_answer`) and `check()`. Phase 5 adds the viewer methods, and bixbench adds `Settings` and `AssertionConfigError` (code in the first version of this file, commit 5ab2416).
- `cases_to_tasks.py` stops on a set whose checks read viewer data (phase 5). A `preload.viewer.pdb_ids` is not loaded (`rs-numbering`: the prompt names 1TTR). It copies to `tests/fixtures/` only the files that the checks read (`FIXTURES / "ground_truth.json"`).
- The grader venv in the image has `rdkit`: `cheminformatics-analysis` compares SMILES with it, and without it a correct but different SMILES gets 0 with no error.
- `cheminformatics-analysis` is the old `bioactivity-and-sar` (same case ids).
- Ruff does not check `evals/acellera-bench/cases/*/*/tests/checks.py`: old code, copied unchanged.

Checked: the old trials graded again with the ported tasks, with no model and no Docker. For each old trial, an `agent.db` with its `final_answer.md`, `work_dir` = its `project_files/`, and the task tests in a venv with only pytest and rdkit:

| Old runs (archive) | Trials | Assertions | Same score as the old `grade.json` |
|---|---|---|---|
| all acellera-bench runs of the four sets (`stap`, `stap-mini`, `stap-noviewer`, `stap-base`) | 480 | 708 (617 pass, 70 fail, 21 partial) | 480 of 480 |

### 2.4 Run in Docker (done)

The regrade above already shows that the grading is the same. What Docker adds: the task images (`COPY` to `/app`), `pmai run` in the sandbox image, and the grader in the container. One trial per set covers that:

```bash
make image                       # again: the grader venv now has rdkit
make run JOB=evals/acellera-bench/sample.yaml        # 4 trials, gpt-6-luna, a few cents
uv run python scripts/compare_old.py results/acellera-sample
```

`compare_old.py` costs nothing: it reads the job `result.json` files and the old `grade.json` files, and prints the mean reward per case, old and new. A trial with no verifier result is an infra error, not a 0.

**Done when:** the 4 trials have a reward, and each failure has a known cause.

Result (2026-10-05): reward 1.0 on dr-0001, rs-uniprot, sa-0071 and sar-descriptors, 0 tool errors, 14 to 62 s for each agent run. Harbor marked each trial with `NonZeroAgentExitCodeError`: the exit trap ran `chmod` on parts of `/logs/agent` that belong to the host user, and with `set -e` that failure became exit 1. Fixed: the trap keeps the exit code (`|| true`, then `exit $rc`).

Each `make run` writes a new `results/<eval>-<job file>-<date>/`. A fixed `job_name` made Harbor resume the old job and keep its finished trials, also the failed ones. `make run NAME=<old job>` resumes a job on purpose.

Optional: `evals/acellera-bench/noviewer.yaml` runs all 40 tasks once with `gpt-6-luna` (about $0.60). The old runs used `gpt-5.4`, so the pass rates show the model change too. A run with `gpt-5.4` and 3 seeds, as the old runs, costs about $45: do it only if the user asks.

Default for eval runs: `gpt-6-luna` and `n_attempts: 1`, as few tasks as answer the question.

### 2.5 Delete the old harness (done on 2026-10-05)

The old harness, `mining/`, `development/`, the old docs and scripts are removed (see Status). `eval_sets/` and the port scripts are removed too (2026-10-08, in git history).

bixbench: later. Its old cases and fixtures (16 GB and 5.8 GB) are in the archive, `eval_sets/`. Do not copy the fixtures into cases: bind mount them read only in the job file.

---

## Phase 3. The matrix (done)

Files: `docker/configs/no-skills/`, `evals/acellera-bench/{sa-models,skills-ab}.yaml`, the `reasoning_effort` option and the arm label (`to_agent_info`) in `src/pmai_evals/agent.py`, the skills in `docker/eval/Dockerfile` and `make image`.

```text
docker/configs/
├── default/agent_config.yaml
└── no-skills/agent_config.yaml      same as default, skills plugin removed
```

| Job | Arms (label in `make view`) | Trials |
|---|---|---|
| `evals/acellera-bench/sa-models.yaml` | `pmai-effort-xhigh` gpt-6-luna, `pmai-effort-xhigh` glm-5.3-flash, `pmai-effort-low` gpt-6-luna | 30 |
| `evals/acellera-bench/skills-ab.yaml` | `pmai` (image skills), `pmai-no-skills`; both gpt-6-luna | 20 |

Changes from the first plan:
- `n_attempts: 1`, no `job_name` (`make run` names each job). pass@3 is a `make run` with `n_attempts: 3` when a result needs it.
- The image had no skills: the sandbox image is built with `SKILLS=none`, and no `SKILL.md` reached the agent in the phase 2 trials `[checked]`. `make image` now puts `acellera-skills/skills` at `SKILLS_REF` (default `main`, as the production agent image) in `/home/.pmai/skills`, and prints the skills commit. `PMAI_HOME=/home/.pmai` is the org skills folder of the skills plugin `[checked]`.
- No arm for a skills branch: the first plan mounted an acellera-skills checkout as a third arm. The checkout is on `main`, the same as the image, so the arm tested nothing and is removed (code in commit 2686b68: an agent option that replaced `$PMAI_HOME/skills` with a mounted folder). Harbor's own `skills:` field does not work for this: it wants `SKILL.md` in each child folder `[checked]`.
- Reasoning effort is the agent option `reasoning_effort`, not a config folder: the script sets `reasoning.effort` in the copied config. Harbor's viewer reads this kwarg and shows a "Reasoning effort" column on the job page `[checked]`.
- Harbor's job summary groups the results by `agent_info.name` + model, and the viewer shows the job file `name`. The agent sets `agent_info.name`: `pmai`, then the config folder if it is not `default`, then `effort-<level>`. A test checks that each job file `name` is the same.
- `sa-models` needs `FIREWORKS_API_KEY` (glm-5.3-flash). In `skills-ab` it is optional (`${FIREWORKS_API_KEY:-}`).

Checked without Docker: pmai loads the configs, Harbor loads both job files, the labels resolve, unit tests for the label, the effort option, and `no-skills` = `default` without the skills plugin.

To run (each job less than $1):

```bash
make image                                   # again: the image now has the skills
make run JOB=evals/acellera-bench/sa-models.yaml      # needs FIREWORKS_API_KEY in .env
make run JOB=evals/acellera-bench/skills-ab.yaml
make view
```

**Done when:** `harbor view` shows the arms side by side with reward, tokens and cost.

Result (2026-10-06, 1 attempt per task):

| Job | Arm | Mean reward | Cost |
|---|---|---|---|
| sa-models | `pmai-effort-xhigh` gpt-6-luna | 0.75 | $0.08 |
| sa-models | `pmai-effort-xhigh` glm-5.3-flash | 0.69 (2 timeouts at 1800 s) | $0.34 |
| sa-models | `pmai-effort-low` gpt-6-luna | 0.68 | $0.06 |
| skills-ab | `pmai` (21 skills offered; `pdb`, `data-retrieval` read in 9 of 10) | 0.79 | $0.17 |
| skills-ab | `pmai-no-skills` | 0.68 | $0.17 |

With 1 attempt on 10 tasks, a difference of about 0.1 is noise: the removed third skills-ab arm had the same skills as `pmai` and got 0.88. sa-1858 (Nirmatrelvir in SARS-CoV-2 Mpro) gets OpenAI `bio_policy` refusals with gpt-6-luna in most trials.

---

## Phase 4. Eval account (done)

Facts `[checked]` in pmbackend:
- Login: `GET /v3/auth/csrf`, then `POST /v3/auth/login` (form `username`=email, `password`, header `X-CSRF-Token` = the `csrf_token` cookie).
- The access token works as a cookie (`access_token="Bearer <jwt>"`) or as an `Authorization: Bearer <jwt>` header. The script uses the header: httpx does not send `Secure` cookies over plain http.
- Signup: `POST /v3/auth/signup` JSON (`username`, `email`, `password`, `institution_name`, `country`, `city`, `affiliation`). It returns 403 if `auth.allowed_emails` is set and the email is not in it. Email verification is on by default: a code goes to the email, then `POST /v3/auth/verify/mail` with a login token.
- After the verification, the account joins the group whose `email_patterns` match the email, if there is one.
- PMView opens a modal if the user has no `country`.
- No captcha, no 2FA, no API key. The access JWT expires after `auth.jwt_expiration` minutes.
- Job bucket name: `config["bucket"]`, default `{user_id}-jobs`.

File: `scripts/eval_account.py` (`check`, `signup`, `verify CODE`). It reads `PM_BACKEND_URL` (default: the dev backend), `PM_EMAIL` and `PM_PASSWORD` from `.env`.

Result (2026-10-06): `check` with the old harness account (`PM_EMAIL`, `PM_PASSWORD`) on `http://computer19:8002` logs in:

| Field | Value |
|---|---|
| user_id, username | `carles` |
| group | `carles` (personal) |
| country | Spain |
| default project | `carles-project` |
| priorities | normal, 2gpus, general, low |

Decision (2026-10-06, the user): the eval account is this account, `carles`. Phase 6 jobs go to its bucket (`carles-jobs` by default) and use its credit. For a dedicated account later: `signup`, then `verify CODE`, with that account in `PM_EMAIL` and `PM_PASSWORD`.

Still to settle in phase 6:
- If the dev backend enforces credits, an admin grants credit with `POST /v3/admin/groups/{id}/grants`.
- The bucket folder on computer19 (`$PM_DATA_STORAGE/<bucket>`). It is not visible from ws12.

**Done when:** `check` prints the user with a country. Done.

---

## Phase 5. Viewer sidecar

Plan page with diagrams: https://claude.ai/artifact/RUsrHQRhikRFa3q8DMA7gb

### How it works

Each viewer task gets a second container, `viewer`. It opens the deployed PMView site (`PMVIEW_URL`, default `https://acellera.playmolecule.ai`) in headless Chromium and logs in as the eval account. We have no PMView files and read no PMView code: the browser loads the site as a user does.

Playwright takes only two things away from the site, in the browser:

| Request from PMView | Goes to |
|---|---|
| socket `/v3/agent/ws/<id>` (`route_web_socket`) | the sidecar, not the site's agent. It keeps this socket for the whole trial. |
| `/v3/file/<project>/<path>` GET, PUT (`route`) | the trial's project folder (`/files/<project>`, a shared volume), not the site's bucket |
| all else (app, login, CDNs, other projects) | the site, as for a user |

One trial:

1. The sidecar starts Chromium with WebGL on the CPU (SwiftShader), checks WebGL2, and logs in with a `fetch` in the page, so Chromium keeps the cookies.
2. The agent script calls `GET viewer:9000/open?project=app`. The sidecar sets the `PM_PROJECT` cookie, opens the site and waits until PMView runs `print('ready')` through `pmview_run_python`: the socket is up and Pyodide has started. Else 503 with the reason.
3. On 200 the script adds `--viewer-id eval`. The sidecar connects to `ws://main:8100/v1/ws/eval` while pmai serves it and passes pmai's messages to PMView. Each result goes back to the one that sent the command.
4. After pmai exits, the sidecar keeps the PMView socket (a ping every 25 s). The tests call `POST viewer:9000/python` and read the viewer with `pmv.get_viewer_state()`: the API that the agent uses. If PMView breaks this API, the agent breaks too, and the eval must find it.
5. On `docker compose down`, the sidecar saves `final.png` next to `events.jsonl` in the artifacts folder.

The site:
- `acellera.playmolecule.ai` serves a PMView build (`/assets/index-<hash>.js`) `[checked]`. The `ready` event in `events.jsonl` records the script names, so the hash is the PMView version under test.
- `dev.acellera.playmolecule.ai` serves the PMView source through the Vite dev server (`/@vite/client`, `/src/index.jsx`) `[checked]`: the code can change during a run.
- `PM_EMAIL` must log in on the site. The eval account `carles` logs in on dev and on production `[checked]`.

PMView facts, seen on the dev site with Playwright `[checked]`:
- Socket messages: `pmview_command` `{tool_name, arguments, chat_id, command_id}` gets `pmview_result` `{command_id, output | error}`; `ping` gets `pong`. There is no hello message.
- PMView opens its agent socket about 1 s after the first one again. A result can come on the new socket.
- Before Pyodide is ready, `pmview_run_python` returns at once with output `{success: false, error: "The Python engine is still starting (20%)..."}`. Python was ready after 13 s on ws12.
- `pmview_load` of a project file sends `GET /v3/file/<project>/<path>`. `pmview_save` sends `PUT /v3/file/<project>/<dir>/<name>`, a multipart form with the field `file`.
- jQuery, Pyodide 0.29.3 and other scripts come from CDNs, so the sidecar needs internet.
- From the pmview code (cab37c5), not seen: PMView drops a socket with no message for 31 s and connects again.

Failures are infra errors, not a score of 0:

| Risk | Guard |
|---|---|
| No WebGL2: Mol* draws a flat image and shows no error | WebGL2 gate at start: read the renderer name |
| Login fails, site down | `broken` with the reason: `/open` gives 503 |
| PMView not ready (Pyodide, CDNs) | `/open` waits for the socket and a Python probe, at most `READY_TIMEOUT` (300 s). Else 503 with the last reason and the last failed request. |
| Page crash, browser gone | Playwright events set `broken`. Then `/open`, `/python` and `/screenshot` give 503. |
| No message on the socket for 31 s | the sidecar pings every 25 s. Checked: a command after 70 s with no other message works. |
| PMView not connected when pmai sends a command | after 30 s, an error result goes to pmai: "The viewer is not connected." |
| A service worker answers a request: the routes do not see it | the context blocks service workers |

No Playwright trace: a trace records the login form (with the password) and the auth cookies `[checked]`. The sidecar logs the socket URL without its query (it has the csrf token).

### 5.1 PMAI: `--viewer-id` (done)

In playmoleculeAI `cli.py` (d5a3f3fb, pushed by the user). `pmai run --viewer-id ID` serves the API during the turn (on `AGENT_PORT`, else the YAML port) and sends viewer commands to the viewer that connects at `/v1/ws/ID`. The chat records the viewer id, as for a browser chat. `--serve` serves the API with no viewer (phase 6).

### 5.2 `docker/viewer/server.py` and `tests/test_viewer_server.py` (done)

The files are the reference. Environment: `PMVIEW_URL`, `PM_EMAIL`, `PM_PASSWORD`, `AGENT_WS` (compose sets `ws://main:8100/v1/ws/eval`; the default `ws://localhost:8100/v1/ws/eval` is for 5.8), `VIEWER_PRELOAD` (JSON `{"pdb_ids", "files"}`), `FILES_ROOT`, `EVIDENCE_DIR`, `READY_TIMEOUT`.

Control API on `:9000`:

| Call | Result |
|---|---|
| `GET /healthz` | 200 when the browser has started, or failed to start. Compose then starts `main`. |
| `GET /open?project=P` | 200 `ready`, or 503 with the reason. A 503 also when `FILES_ROOT/P` is missing. After a 503 every call gives the same 503. |
| `POST /python` (body: code) | `{stdout, stderr, result}`. 502: PMView gave an error. Any other error: infra error. |
| `GET /screenshot` | PNG |

Checked:

| Check | Result |
|---|---|
| Unit tests: fake PMView socket and fake pmai (ping, each result to its sender, a new PMView socket, a test command after pmai exits, 503 without PMView, project files GET and PUT) | 4 passed in 0.6 s |
| `server.py` on ws12 against `dev.acellera.playmolecule.ai`: Playwright 1.58.0, its Chromium | login 200; `/open` ready in 13.8 s; `Molecule('1crn')` as cartoon in `pmv.get_viewer_state()`; `pmview_load` of a project file and `pmview_save` back to the project folder; a command after 70 s idle; `/screenshot` PNG; no csrf token and no password in `events.jsonl` |

The image on computer19 against production (2026-10-07, by the user, 5.8 with `--network host`) `[checked]`:
- `/healthz` ok, `/open` ready, `/python` ran, `/screenshot` PNG.
- One `pmai run --viewer-id eval` turn (gpt-6-luna, in `pmai-eval:latest`): `run_bash` downloaded 1CRN to `structures/`, `pmview_load` loaded it from the trial folder through the route, `pmview_run_python` set the style. After the turn, `pmv.get_viewer_state()` gave the system `1CRN_assembly1.pdb` with style `cartoon`.

Not checked yet: a Harbor trial with `docker/viewer/compose.yaml`.

### 5.3 `docker/viewer/Dockerfile` and `make viewer` (written)

`make viewer` builds `pmai-viewer:latest`: the Playwright 1.58.0 image and `server.py`. The image has Chromium in `/ms-playwright`, but not the Python package, so the Dockerfile installs `playwright==1.58.0` (the same version as the browsers) and `aiohttp`. No PMView files: the site serves them.

### 5.4 `docker/viewer/compose.yaml` (written)

Each viewer task has `environment/docker-compose.yaml`, a copy of `docker/viewer/compose.yaml` (`cases_to_tasks.py` writes it; `tests/test_tasks.py` fails when a copy is old). Not a link: Harbor refuses a link out of the task for a git dataset, and its environment hash skips links. Harbor adds a task's compose file to the trial, so a viewer task always gets its viewer, and other tasks in the same job start no browser. The job file needs nothing.

- Harbor runs compose with the process env, so `${PM*}` come from `.env` (`make run` exports it) `[checked]`. Harbor sets `HOST_ARTIFACTS_PATH` from its own `/logs/artifacts` mount `[checked]`.
- `main` gets `VIEWER_URL=http://viewer:9000` and starts only when the viewer is healthy. The viewer gets `AGENT_WS=ws://main:8100/v1/ws/eval`: 8100 is `port` in the pmai config. Not `AGENT_PORT`: it moves only the port that pmai listens on, and the tools still call back on the config port (playmoleculeAI `core/installation.py:12`). A fix in pmai can use one port for both.
- A task's `[environment] env` goes to compose: `VIEWER_PRELOAD`, for example `{"pdb_ids": ["1JPZ"], "files": ["pseudo_oxo.pdb"]}`, goes to the viewer. Each viewer task sets it, empty when there is no preload, so a value in `.env` cannot get in. After ready, `/open` loads them as the agent does: each PDB id with `Molecule(id).view()`, the files with `pmview_load`. A failed load is a 503, and all of `/open` stays within `READY_TIMEOUT`.
- The project is a named volume: `/app` in `main`, `/files/app` in `viewer`. Docker fills it from the image's `/app` on first use. Harbor's `down --volumes` removes it.
- The viewer container needs internet: the site and the CDNs.
- The sidecar writes `viewer/events.jsonl` and `viewer/final.png` straight to the trial's artifacts folder (on the host: `<trial>/artifacts/logs/artifacts/viewer/`) `[checked]`. Harbor collects sidecar artifacts before the verifier, which is too early for `final.png` `[checked]`. `os.umask(0)` in `server.py`: on NFS the files belong to nobody, and the host user must still delete them.

### 5.5 `agent.py`: stop on 503 (written)

The script opens the viewer only when `VIEWER_URL` is set: other tasks run as before. A 503 from `/open` stops the script with the reason on stderr; no answer stops it with a traceback. That is an infra error: Harbor records `NonZeroAgentExitCodeError` and still runs the verifier `[checked]`, and `trial.py` then raises `InfraError` (5.6).

### 5.6 `trial.py`: the viewer through the agent's API (written)

Removed on 2026-10-14, when no test read the viewer any more (viewer-quality grades `final-view.png`): the first viewer read saves a snapshot of the viewer after the turn in `/logs/artifacts/viewer/snapshot/` (on the host: `<trial>/artifacts/logs/artifacts/viewer/snapshot/`): `state.json`, `selection.json` and `systems/<uuid>.cif` for each structure. The tests read the snapshot, so a later grade on the host (`TRIAL_LOGS=...`) needs no viewer `[checked]`. `viewer_python` and `viewer_screenshot` still use the live viewer. A system that PMView cannot write gives `systems/<uuid>.error`: only the checks that need it fail.

| Old check reads | New, in `trial.py` | Through |
|---|---|---|
| `artifact.viewer_state()` | `viewer_state()` | `pmv.get_viewer_state()`, from the snapshot |
| `artifact.viewer_selection()` | `viewer_selection()` | `pmv.get_viewer_selection()`, from the snapshot. Before the first selection it raises `TypeError`: `{}`. |
| `artifact.load_system(name)` | `viewer_system(uuid)`: the path of the mmCIF file | `pmv.get_system(uuid)`, written as mmCIF (the PDB writer needs networkx, which Pyodide does not have) `[checked]`. 3 systems with 5TBY (2.2 MB): 5.9 s. |
| final screenshot | `viewer_screenshot()` | `GET /screenshot` |
| | `viewer_python(code)` | `POST /python`: `{stdout, stderr, result}` |

Errors:

| From the sidecar | In the test | Trial |
|---|---|---|
| no `VIEWER_URL`, no answer, any HTTP error but 502 | `InfraError` (in `reward.py`) | no `reward.json`: Harbor raises `RewardFileNotFoundError`, so the trial is an error, not 0 `[checked]`. The plugin prints the reasons. |
| 502 (the PMView tool failed), a Python error in PMView | `RuntimeError` with the reason | the test fails: PMView broke the API that the agent uses |

### 5.7 Port molecular-visualization

The old checks read other field names. An adapter in `legacy.py` maps them:

| Old field | New field |
|---|---|
| `moleculeID` | the key of `systems` |
| `type` | `style` |
| `selection` | `sel` |
| `color_value` (int, or none for a scheme) | `color`: `"#rrggbb"` (PMView stores `blue` as `#0000ff`) or a scheme name (`element-symbol`) `[checked]`. The adapter gives the string as it is (the checks parse it) or none. |
| a list of systems | a dict of systems by uuid. The adapter gives the structures only (no volumes), the newest first: the checks take the first match, and that is then the agent's own copy, not a preloaded one. A name that is `None` gives `""`. |
| a rep of a hidden system | `visible: false` on the system: the adapter makes its reps not visible |
| `load_system(name)`, `system_files()` from the export zip | the systems in the viewer by name without the extension, through `pmv.get_system(uuid)` as mmCIF |

```bash
uv run python scripts/cases_to_tasks.py eval_sets/acellera-bench/molecular-visualization evals/acellera-bench/cases/molecular-visualization
make image viewer   # both changed: legacy.py and trial.py are in pmai-eval, server.py in pmai-viewer
make run JOB=evals/acellera-bench/viewer.yaml
```

`evals/acellera-bench/viewer.yaml`: mv-1jpz (a preload and a viewer selection), mv-2ity (colors and styles), mv-7fab (a selection). gpt-6-luna, 1 attempt, less than $0.05. The full set only after that sample passes.

- The old cases preloaded `pdb_ids` and `files` in the viewer: now `VIEWER_PRELOAD` (mv-1ca2, mv-1jpz). The files also go to the project, as before.
- `legacy.check` raises `InfraError` again: an infra error gives no reward, not a 0.
- Checked on ws12 against production, with no model (2026-10-07): the preload of 1JPZ and `pseudo_oxo.pdb` loaded both (names `1jpz` and `pseudo_oxo.pdb`); the mv-1jpz selection made through `/python`; then the ported check through `legacy.py` and `trial.py` gave 1.0, and 1.0 again from the snapshot with no viewer `[checked]`.
- The old checks find a system by its name without the extension. An agent that loads `1CA2_assembly1.pdb` for "1CA2" fails them, as in the old harness.

### 5.8 Try the sidecar without Harbor

One `pmai run` turn on the host with gpt-6-luna: less than $0.01.

```bash
make viewer
mkdir -p /tmp/t1/app /tmp/t1/home /tmp/t1/artifacts && cp docker/configs/default/agent_config.yaml /tmp/t1/home/
# host network: on computer19 a -p port mapping connects but never answers (2026-10-07)
docker run --rm --name pmai-viewer-try --network host --env-file .env \
  -v /tmp/t1:/files -v /tmp/t1/artifacts:/logs/artifacts pmai-viewer:latest
# second shell
curl "localhost:9000/open?project=app"   # "ready", else 503 with the reason
# pmai is not on the computer19 host: use the one in pmai-eval:latest
docker run --rm --network host -e OPENAI_API_KEY -v /tmp/t1:/tmp/t1 -w /tmp/t1/app pmai-eval:latest \
  pmai run --viewer-id eval --config /tmp/t1/home --model gpt-6-luna \
  --prompt "Download PDB 1CRN and show it in the viewer as cartoon"
curl --data "import json; print(json.dumps(pmv.get_viewer_state(), default=str))" localhost:9000/python
curl -o /tmp/t1/shot.png localhost:9000/screenshot
```

`/tmp/t1/artifacts/viewer/events.jsonl` has the sidecar events. `-e PMVIEW_URL=...` opens another site.

### 5.9 The trace in `make view` (written)

`make view` shows the steps of a trial only from `agent/trajectory.json` (Harbor's ATIF format). `src/pmai_evals/trajectory.py` writes it from `agent.db`; `agent.py` calls it after each turn, for all tasks. Each step has the model's text, its reasoning summary, each tool call with its arguments (for example the Python of `pmview_run_python`), the output, and the images (files in `agent/images/`; ATIF wants a path). Only the main chat: a subagent's steps stay in `agent.db`.

Viewer tasks: after each of pmai's commands, the sidecar logs `pmai_result` (before pmai gets the result) and 1 s later saves a JPEG of the page in `viewer/steps/`. The step of that command shows it: a result comes back before pmai saves its response in `agent.db`, so the screenshot goes to the first response saved after it.

For trials that are done: `uv run python -m pmai_evals.trajectory results/<job>/<trial> ...`. The 3 trials of the first `evals/acellera-bench/viewer.yaml` run (2026-10-08, all reward 1.0) have it, without the sidecar screenshots (the sidecar took none then). The running `make view` served the trace and its images `[checked]`.

**Done when:** molecular-visualization passes on Harbor at the old harness rate, and nobody opens a browser.

---

## Viewer quality: the first hill climbing eval

The old viewer tasks check the viewer state, so a view nobody can read still gets 1.0. This eval grades the final image: the viewport as the user sees it. Plan, with the trace mining: https://claude.ai/artifact/Jy2kpxN4vz6aAkGjhQZZYH (2026-10-08).

- `evals/viewer-quality/cases/`: 20 cases from real chats (`[metadata] source` in each `task.toml`). Each prompt says to use the viewer. `tests/rubric.txt`: what a good image shows, one "<points> <criterion>" a line, 10 points in all; the score is the points of the yes lines.
- After the turn, the agent wrapper keeps the image (`agent.py`, also after a failed turn): `trial.final_image()` -> `artifacts/logs/artifacts/viewer/final-view.png` (the sidecar's `/screenshot`, PMView's viewport screenshot). A file that the prompt asks for is a Harbor artifact in `task.toml`.
- No score until the judge (2026-10-13): the job files turn the verifier off, and the cases have no tests. Harbor ends a run with a mean of 0.000; the score is `human_reward` in `make view`, which shows no verifier rewards for the runs of a job file with the verifier off (also the older runs, which had a reward 1.0 that said only "saved").
- `evals/viewer-quality/train.yaml`: the 15 hill climbing cases. `evals/viewer-quality/holdout.yaml`: the 5 held-out cases (keyword `holdout`), only to check that a gain is real.
- No trajectory case yet: one image cannot show that frames are aligned.

Steps:

1. The cases (written). 2. Baseline run, gpt-6-luna. 3. The user rates the final images against the rubric. 4. A judge (gpt-6.1-sol) that agrees with the ratings. 5. Hill climb: one change a round (skill, tools, model; PMView issues go to its team). 6. Freeze a regression set. 7. The same cases with MoleculeKit `mol.render`.

---

## Phase 6. PlayMolecule jobs

### How it works

- With a local sandbox, pmai sets `PM_EXECUTOR` and `PM_REGISTRIES` to its own `/v1/backend` relay. The relay adds `Authorization: Bearer $BACKEND_SERVICE_TOKEN` and `X-On-Behalf-Of: <user id>` `[checked]`. This needs `--serve`.
- The backend writes job outputs to `<storage>/<bucket>/<project>/<job>`. Local storage reads the disk on each request, so files that other processes write are served at once `[checked]`.
- So the trial mounts the eval bucket at the same path, and the agent's cwd is `<bucket>/eval-<trial>`. The job writes there, and the agent and the verifier read there.

### 6.1 PMAI: `--wait-jobs` (playmoleculeAI `cli.py`)

Jobs are rows in the `jobs` table with `root_chat_id` and `notified_at` `[checked]`. Today the stream ends when the session is idle, and PM jobs do not keep it open.

```python
def pending_jobs(engine, root_chat_id: str) -> bool:
    with Session(engine) as s:
        return s.exec(select(Job).where(Job.root_chat_id == root_chat_id,
                                        Job.notified_at.is_(None))).first() is not None
```

```python
        code = await follow(events)  # the current print loop, as a function
        root = chat.root_chat_id or chat.chat_uid
        while args.wait_jobs and (pending_jobs(runtime.db_engine, root) or runtime.is_active(root)):
            await asyncio.sleep(10)
            if stream := await runtime.stream_agent(root):  # the job notice woke the agent
                code = await follow(stream)
```

`[verify]` in PMAI: after the notice, `runtime.stream_agent(root)` returns the new turn's stream.

### 6.2 `docker/configs/pm/agent_config.yaml`

```yaml
port: 8100              # AGENT_API_URL defaults to http://localhost:8100/v1
sandbox:
  backend_type: local
plugins:
  playmolecule:
    backend_endpoint: http://computer19.acellera.lan:8002/v3
```

### 6.3 `evals/pm/smoke.yaml`

```yaml
job_name: pm-smoke
datasets:
  - path: evals/pm/cases
environment:
  mounts:   # the eval bucket, same path inside and outside (example path)
    - {type: bind, source: /data/pm/1234-jobs, target: /data/pm/1234-jobs}
agents:
  - import_path: pmai_evals.agent:PmaiAgent
    model_name: gpt-6-luna
    kwargs:
      pmai_config: /opt/pmai-config/pm
      work: /data/pm/1234-jobs/eval-$HOSTNAME     # one project per trial
      flags: --serve --wait-jobs --user carles
    env:
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      BACKEND_SERVICE_TOKEN: ${BACKEND_SERVICE_TOKEN}
```

For viewer tasks with jobs, mount the same bucket in the sidecar: `volumes: ["/data/pm/1234-jobs:/files"]`.

### 6.4 `evals/pm/cases/proteinprepare/tests/test_case.py`

```python
from pmai_evals import trial


def test_used_the_app():
    assert any("proteinprepare" in c["arguments"] for c in trial.tool_calls("run_bash"))


def test_job_output():
    assert list(trial.WORK.glob("*/output.pdb"))  # [verify] the app's output name


def test_answered_after_the_job():
    assert "output.pdb" in trial.answer()
```

**Done when:** a proteinprepare job runs on the cluster, the agent answers the job notice, and the verifier reads the output.

---

## Phase 7. Scale out (later)

```toml
# task.toml: grade in a clean container, regrade old trials without a new agent run
artifacts = ["/app", "/logs/agent/home/agent.db"]

[verifier]
environment_mode = "separate"
```

```bash
harbor run -c evals/nightly.yaml -e modal -n 32     # only tasks with no bucket and no PM jobs
0 2 * * * cd ~/playmoleculeai-evals && make run JOB=evals/nightly.yaml
```

Every trial keeps a production `agent.db`: the analysis dashboard can load them as they are.

---

## Risks

| Risk | Phase | Action |
|---|---|---|
| Provider keys and the service token are in the container env. The local backend gives `os.environ` to bash, so the agent can read them. | 1, 6 | Eval only keys. Later: strip them in `LocalBackend`. |
| The sandbox image user is not root | 1 | Restore `USER` in `docker/eval/Dockerfile`; set `[agent].user` if needed. |
| Bucket file owner: the backend and the cluster must read what the container writes | 6 | Run the agent as the bucket owner uid (`[agent].user`). |
| SwiftShader WebGL is slow, Pyodide takes time to load | 5 | `/open` waits up to 5 min. Measured on ws12: ready in 14 s. |
| PMView changes under us | 5 | We test what the site serves. The `ready` event records its build (script hash). Use production, not the dev site (Vite dev server). |
| Harbor 0.x changes fast | all | Keep `harbor==0.24.0`; read the changelog before an upgrade. |
| Named compose volumes stay after a trial | 5 | `docker volume prune` in the nightly job. |
