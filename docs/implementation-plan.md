# Implementation plan: PMAI evals on Harbor

The plan page shows the idea. This file is the work list. Do the phases in order. Each phase ends with something that runs.

| Phase | Result | Changes outside this repo |
|---|---|---|
| 0 | Tooling: Harbor installed, `make run` works | none |
| 1 | One case runs in Docker with Harbor and gets a reward | none |
| 2 | Four acellera-bench sets run with their old checks, unchanged | none |
| 3 | Models, configs and skills compared in one job | none |
| 4 | Eval account on the dev backend | one account (one time) |
| 5 | Viewer tasks: PMView sidecar, molecular-visualization ported | PMAI: `--serve`, `--viewer-id` |
| 6 | PlayMolecule job tasks | PMAI: `--user`, `--wait-jobs` |
| 7 | Scale out, nightly run | none |

Facts checked in the code (Harbor 0.24.0 source, pmbackend, pmview, playmoleculeAI) are marked `[checked]`. Points to try first are marked `[verify]`.

## Target layout

```text
playmoleculeai-evals/
├── Makefile                      image, viewer, run, test
├── .env.example                  keys and eval account (never committed: .env)
├── image/Dockerfile              pmai-eval: sandbox + pmai + grader
├── viewer/                       phase 5
│   ├── Dockerfile                pmai-viewer: pinned PMView build + Chromium + server
│   ├── server.py                 one origin for PMView: static, /v3 proxy, agent socket, files, control API
│   └── pmview.py                 page helpers, from the old src/pmai_evals/browser/ (archive)
├── config/<name>/agent_config.yaml   pmai configs, baked at /opt/pmai-config
├── src/pmai_evals/
│   ├── agent.py                  Harbor agent (host side)
│   ├── trial.py                  what tests ask about a trial (stdlib)
│   ├── reward.py                 pytest plugin: scores to reward.json
│   ├── judge.py                  LLM judge
│   └── legacy.py                 runs old checks.py functions unchanged
├── tasks/<set>/<case>/           Harbor tasks: the eval cases
├── experiments/*.yaml            Harbor job configs (results go to jobs/, gitignored)
├── scripts/cases_to_tasks.py     one time port from eval_sets/
├── scripts/legacy_test_case.py   test file copied into every ported task
├── scripts/compare_old.py        a job against the old runs in the archive
├── scripts/eval_account.py       phase 4
├── tests/                        unit tests for src/ and viewer/
└── eval_sets/                    deleted set by set, after each port is verified
```

---

## Status (2026-10-06)

- Phases 0 and 1 are done. The files are the reference. The two sections below give only the changes from the first plan and the checks.
- Phase 2: 40 tasks ported, and the port gives the old scores on 480 old trials. In Docker, `acellera-sample` (one case per set, gpt-6-luna) gave reward 1.0 on 4 of 4 trials, for less than $0.01.
- `make image`, `make run` and `make view` work (run by the user as `slurmweb`, 2026-10-05). The first smoke trial got no reward:
  the `.env` OpenAI key is archived (401), and then `populate_context_post_run` crashed on the read only `agent.db`, which stopped the trial before the verifier. Both causes are known; the crash is fixed. Run the smoke job again with a working key.
- Phase 3: done. `sa-models` and `skills-ab` ran in Docker (results in the phase 3 section). The image now has the skills (it had none before).
- Phase 4: done. The eval account is `carles` (the user's account, `PM_EMAIL` in `.env`); `scripts/eval_account.py check` logs in on the dev backend.
- The old harness is removed. All of it is in `/fast_shared/users/carles/data/playmoleculeAIdata/evals-archive-2026-10-05/`:
  - `repo-before-cleanup.tar.gz`: the repo before the cleanup (old src, tests, scripts, mining, development, docs, playwright). Not in it: `.env`, `playwright/.auth`, `.venv`, `.git`, bixbench fixtures.
  - `runs/`: the old run results (34 GB), the baseline for phase 2.
  - `git-head.txt`, `git-status.txt`.

## Phase 0. Tooling (done)

Files: `pyproject.toml`, `uv.lock`, `.env.example`, `.gitignore`, `.dockerignore`, `Makefile`.

Changes from the first plan:
- `pyproject.toml` is new, with one dependency: `harbor==0.24.0`. `anthropic`, `pytest` and `ruff` are dev only, because `judge.py` runs in the image.
- `.dockerignore` sends only `dist/`, `config/` and `src/` to the build. `eval_sets/` is 22 GB.
- `make image` builds the PMAI sdist first, then the wheel from it. A direct `uv build --wheel` reuses `playmoleculeAI/build/lib`, which still has `agents/builtin/{researcher,reviewer,scout}` (deleted from src). Then pmai fails on start: `researcher/AGENT.md: description: Unexpected keyword argument`.
- `make lint` is new. `make viewer` comes with phase 5.
- `make run` exports `.env`, because Harbor reads `${VAR}` in job files from the process env `[checked]`. `HARBOR_TELEMETRY=off`: telemetry is on by default and sends job ids, models and cost.

Checked: `uv run harbor --version` prints 0.24.0. `make -n` for all targets.

## Phase 1. Walking skeleton (done, smoke reward in Docker still to see)

Files: `config/default/agent_config.yaml`, `image/Dockerfile`, `src/pmai_evals/{agent,trial,reward,judge}.py`, `tasks/smoke/hello-file/`, `experiments/smoke.yaml`, `tests/`.

Changes from the first plan:
- `config/default`: `config_version: 1`. Without it, pmai rewrites the file on start and keeps a `.v0.bak`. No `codebase_search` and no `literature`: both start, but their tools fail in the container (no `SEARCH_URL` service, no literature data). Phase 3 can add them again with `SEARCH_URL` in the job env, if the container can reach the service.
- `agent.py`: `--model` only when the job sets a model. Else pmai uses the default of the config.
- `trial.py`: `TRIAL_LOGS` (default `/logs/agent`) sets the folder of `home/agent.db` and `work_dir`. With it, the task tests grade a hand run on the host (see the README).
- `judge.py`: the request streams, with adaptive thinking. An empty answer is FAIL.
- `experiments/smoke.yaml`: `${ANTHROPIC_API_KEY:-}`. Harbor stops the job when a `${VAR}` is not set `[checked]`, and the smoke task has no judge.
- On the host, the trial files from the container belong to `nobody` (NFS root squash). `agent.db` is in WAL mode, so a reader must create `agent.db-shm`: `trial.q` reads a copy when the folder is read only. The agent script makes `/logs/agent` writable on exit, so the host user can delete `jobs/`. `populate_context_post_run` never raises: Harbor calls it before the verifier.
- Unit tests: also `test_agent.py` (the script and `populate_context_post_run`) and `test_judge.py` (a fake client). `test_reward.py` also checks that a setup error gives 0.

Checked:

| Check | Result |
|---|---|
| `make test`, `make lint` | 7 passed, clean |
| `Task.is_valid_dir`, `JobConfig` with `extra="forbid"`, agent class, preflight, dataset tasks | all OK |
| Agent script: `bash -n`, and the viewer probe with no sidecar | OK; the probe fails in 0.2 s, no extra flags |
| `pmai run` from the PMAI source venv, `config/default`, smoke prompt | exit 0, `hello.txt` OK, 45 events |
| `pmai run` from the wheel, in a new Python 3.12 venv, outside the source tree | exit 0 |
| Smoke tests on both runs with `TRIAL_LOGS`, also in a venv with only pytest | reward 1.0 |
| `populate_context_post_run` on the real `agent.db` | 6334 in, 3145 cached, 47 out, $0.00037 |

Hand run gotchas:
- From the PMAI source tree, `load_dotenv()` loads `playmoleculeAI/.env`, which sets `PMAI_HOME=/home/slurmweb/...`. Set `PMAI_HOME` yourself. The image installs the wheel, so this does not occur there.
- The `OPENAI_API_KEY` in the `.env` of this repo is from an archived OpenAI project (401 `not_authorized_invalid_project`). Put a working key there before `make run`.

Next:

```bash
docker run --rm $SANDBOX id        # [verify] not root: restore USER in image/Dockerfile
make image && docker run --rm pmai-eval:latest pmai --help
make run JOB=experiments/smoke.yaml && make view
```

**Done when:** `harbor view` shows hello-file with reward 1.0, tokens and cost.

---

## Phase 2. Port the eval sets with the old checks (done)

Only `molecular-visualization` reads viewer data (`viewer_state`, `viewer_selection`, `load_system`) `[checked]`. The other four acellera-bench sets read only the final answer and the project files. They run now, without a viewer.

Behaviour note: in these runs the viewer tools are offered but fail with "No viewer is connected" `[checked]`. The agent uses moleculekit in bash. Phase 5 runs them again with the viewer.

Files: `src/pmai_evals/legacy.py`, `scripts/legacy_test_case.py`, `scripts/cases_to_tasks.py`, `scripts/compare_old.py`, `experiments/acellera-{sample,noviewer}.yaml`, `tasks/{structure-analysis,cheminformatics-analysis,retrieval-and-selection,3d-reasoning}/` (40 tasks), `tests/test_legacy.py`.

Changes from the first plan:
- `legacy.py` has only what these four sets use: `PYTHON_CHECK_TYPE`, `AssertionResult`, `RunArtifact` (`project_files_dir`, `final_answer`) and `check()`. Phase 5 adds the viewer methods, and bixbench adds `Settings` and `AssertionConfigError` (code in the first version of this file, commit 5ab2416).
- `cases_to_tasks.py` stops on a set whose checks read viewer data (phase 5). A `preload.viewer.pdb_ids` is not loaded (`rs-numbering`: the prompt names 1TTR). It copies to `tests/fixtures/` only the files that the checks read (`FIXTURES / "ground_truth.json"`).
- The grader venv in the image has `rdkit`: `cheminformatics-analysis` compares SMILES with it, and without it a correct but different SMILES gets 0 with no error.
- `cheminformatics-analysis` is the old `bioactivity-and-sar` (same case ids).
- Ruff does not check `tasks/*/*/tests/checks.py`: old code, copied unchanged.

Checked: the old trials graded again with the ported tasks, with no model and no Docker. For each old trial, an `agent.db` with its `final_answer.md`, `work_dir` = its `project_files/`, and the task tests in a venv with only pytest and rdkit:

| Old runs (archive) | Trials | Assertions | Same score as the old `grade.json` |
|---|---|---|---|
| all acellera-bench runs of the four sets (`stap`, `stap-mini`, `stap-noviewer`, `stap-base`) | 480 | 708 (617 pass, 70 fail, 21 partial) | 480 of 480 |

### 2.4 Run in Docker (done)

The regrade above already shows that the grading is the same. What Docker adds: the task images (`COPY` to `/app`), `pmai run` in the sandbox image, and the grader in the container. One trial per set covers that:

```bash
make image                       # again: the grader venv now has rdkit
make run JOB=experiments/acellera-sample.yaml        # 4 trials, gpt-6-luna, a few cents
uv run python scripts/compare_old.py jobs/acellera-sample
```

`compare_old.py` costs nothing: it reads the job `result.json` files and the old `grade.json` files, and prints the mean reward per case, old and new. A trial with no verifier result is an infra error, not a 0.

**Done when:** the 4 trials have a reward, and each failure has a known cause.

Result (2026-10-05): reward 1.0 on dr-0001, rs-uniprot, sa-0071 and sar-descriptors, 0 tool errors, 14 to 62 s for each agent run. Harbor marked each trial with `NonZeroAgentExitCodeError`: the exit trap ran `chmod` on parts of `/logs/agent` that belong to the host user, and with `set -e` that failure became exit 1. Fixed: the trap keeps the exit code (`|| true`, then `exit $rc`).

Each `make run` writes a new `jobs/<job file>-<date>/`. A fixed `job_name` made Harbor resume the old job and keep its finished trials, also the failed ones. `make run NAME=<old job>` resumes a job on purpose.

Optional: `experiments/acellera-noviewer.yaml` runs all 40 tasks once with `gpt-6-luna` (about $0.60). The old runs used `gpt-5.4`, so the pass rates show the model change too. A run with `gpt-5.4` and 3 seeds, as the old runs, costs about $45: do it only if the user asks.

Default for eval runs: `gpt-6-luna` and `n_attempts: 1`, as few tasks as answer the question.

### 2.5 Delete the old harness (done on 2026-10-05)

The old harness, `mining/`, `development/`, the old docs and scripts are removed (see Status). Still to do: remove each `eval_sets/acellera-bench/<set>` after its tasks run in Docker (2.4).

bixbench: later. Its fixtures are 16 GB and 5.8 GB. Do not copy them into tasks: bind mount them read only in the job file.

---

## Phase 3. The matrix (done)

Files: `config/no-skills/`, `experiments/{sa-models,skills-ab}.yaml`, the `reasoning_effort` option and the arm label (`to_agent_info`) in `src/pmai_evals/agent.py`, the skills in `image/Dockerfile` and `make image`.

```text
config/
├── default/agent_config.yaml
└── no-skills/agent_config.yaml      same as default, skills plugin removed
```

| Job | Arms (label in `make view`) | Trials |
|---|---|---|
| `experiments/sa-models.yaml` | `pmai-effort-xhigh` gpt-6-luna, `pmai-effort-xhigh` glm-5.3-flash, `pmai-effort-low` gpt-6-luna | 30 |
| `experiments/skills-ab.yaml` | `pmai` (image skills), `pmai-no-skills`; both gpt-6-luna | 20 |

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
make run JOB=experiments/sa-models.yaml      # needs FIREWORKS_API_KEY in .env
make run JOB=experiments/skills-ab.yaml
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

### How it works

PMView sends every call to its own origin: `location.origin + /v3/...` `[checked]`. There is no setting for the backend URL or the agent URL. So the sidecar is that origin:

| Path from PMView | Goes to |
|---|---|
| `/` and assets | the pinned PMView build (from the `pmweb` image) |
| `/v3/agent/ws/<any id>` | `ws://main:8100/v1/ws/eval` (our `pmai run --serve --viewer-id eval`) |
| `/v3/file/<project>/<path>` GET, PUT | the shared project folder; GET falls back to the backend |
| every other `/v3/...` | the dev backend, with the eval account cookies |

The agent socket protocol `[checked]`: agent sends `{"type": "pmview_command", "tool_name", "arguments", "chat_id", "command_id"}`, PMView replies `{"type": "pmview_result", "command_id", "output" | "error"}`. There is no hello message: the id in the path is the viewer id. pmai waits 30 s for a socket, then fails the command.

### 5.1 PMAI: `--serve` and `--viewer-id` (playmoleculeAI `src/playmoleculeai/cli.py`)

Today `pmai run` sets `viewer_id=None` and only enters the lifespan, so `/v1/ws/{id}` is not served `[checked]`.

```python
@asynccontextmanager
async def serving(app, port: int):
    """Serve the API while the turn runs (sandbox proxy, viewer socket). Also runs the lifespan."""
    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        if task.done():
            task.result()  # raises the startup error
        await asyncio.sleep(0.05)
    try:
        yield
    finally:
        server.should_exit = True
        await task
```

```diff
     client = ClientContext(
-        viewer_id=None,
+        viewer_id=args.viewer_id,
         user_ip="",
         user_bucket=user_bucket,
         project=project,
-        user_id=getpass.getuser(),
+        user_id=args.user or getpass.getuser(),
     )
-    async with app.router.lifespan_context(app):
+    async with serving(app, config.port) if args.serve else app.router.lifespan_context(app):
```

```python
run_parser.add_argument("--serve", action="store_true",
                        help="Serve the API on the config port during the turn.")
run_parser.add_argument("--viewer-id", help="Viewer session for pmview tools. Needs --serve.")
run_parser.add_argument("--user", help="PlayMolecule user id for backend calls. Default: OS user.")
```

Test in PMAI: `pmai run --serve` answers `GET /v1/...` during the turn, and the port is free after it.

### 5.2 `viewer/pmview.py`

Take `src/pmai_evals/browser/{observers.py,viewer_loader.py,locators.py}` and `_io.py` from the archive (`tar -xzf repo-before-cleanup.tar.gz ./src/pmai_evals/browser ./src/pmai_evals/_io.py`) and put them into this one file. Inline `parse_json_lenient` and `BrowserError`. Keep:

```python
READY = "window.pyodideWorkerReady && window.molstar"
def parse_json_lenient(text): ...  # from _io.py
VIEWER_STATE_JSON = ...       # from observers.py
VIEWER_SELECTION_JSON = ...   # from observers.py
SCREENSHOT_DATA_URI = ...     # from observers.py
async def wait_for_system(page, identifier, timeout_s=60): ...   # was _wait_for_identifier
async def export_viewer_state(page, dest_dir) -> Path: ...       # returns the zip path
```

### 5.3 `viewer/server.py`

```python
"""Viewer sidecar: one origin for PMView, and a control API for the agent and the verifier.

:8080  PMView origin: static build, /v3 proxy, agent socket, project files
:9000  control: /healthz /open /state /selection /shot /export
"""

import asyncio
import base64
import os
import re
import tempfile
from http.cookies import SimpleCookie
from pathlib import Path

import aiohttp
from aiohttp import web
from playwright.async_api import async_playwright

import pmview

BACKEND = os.environ["PM_BACKEND_URL"]                   # http://computer19.acellera.lan:8002
AGENT_WS = os.environ.get("AGENT_WS", "ws://main:8100/v1/ws/eval")
STATIC = Path(os.environ.get("PMVIEW_STATIC", "/srv/pmview")).resolve()
FILES = Path(os.environ.get("FILES_ROOT", "/files")).resolve()   # <project>/<path>, as in the backend bucket
ORIGIN = "http://localhost:8080"
COOKIE_PATHS = {"access_token": "/v3", "refresh_token": "/v3/auth/refresh-token", "csrf_token": "/"}
HOP = {"host", "origin", "referer", "content-length", "transfer-encoding", "connection", "content-encoding"}


def safe_path(root: Path, rel: str) -> Path | None:
    p = (root / rel).resolve()
    return p if p.is_relative_to(root) else None


def local_cookie(header: str) -> str:
    """Backend cookies carry the dev Domain and Secure: drop both so they stay on our origin."""
    return re.sub(r";\s*(Domain=[^;]*|Secure)(?=;|$)", "", header, flags=re.I)


async def login(http: aiohttp.ClientSession) -> SimpleCookie:
    async with http.get(f"{BACKEND}/v3/auth/csrf") as r:
        csrf = (await r.json())["csrf_token"]
    form = {"username": os.environ["PM_EMAIL"], "password": os.environ["PM_PASSWORD"]}
    async with http.post(f"{BACKEND}/v3/auth/login", data=form,
                         headers={"X-CSRF-Token": csrf, "Cookie": f"csrf_token={csrf}"}) as r:
        r.raise_for_status()
        return r.cookies


# ---- :8080, the PMView origin -------------------------------------------------

async def proxy(request: web.Request) -> web.StreamResponse:
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    async with request.app["http"].request(request.method, BACKEND + request.rel_url.path_qs,
                                           headers=headers, data=await request.read(),
                                           allow_redirects=False) as r:
        resp = web.StreamResponse(status=r.status)
        for k, v in r.headers.items():
            if k.lower() not in HOP:
                resp.headers.add(k, local_cookie(v) if k.lower() == "set-cookie" else v)
        await resp.prepare(request)
        async for chunk in r.content.iter_any():  # SSE too
            await resp.write(chunk)
        return resp


async def file_get(request: web.Request) -> web.StreamResponse:
    p = safe_path(FILES, request.match_info["path"])
    return web.FileResponse(p) if p and p.is_file() else await proxy(request)


async def file_put(request: web.Request) -> web.Response:  # pmview_save
    p = safe_path(FILES, request.match_info["path"])
    if p is None:
        raise web.HTTPForbidden()
    form = await request.post()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(form["file"].file.read())
    return web.json_response({})  # [verify] the shape sendToBackend.ts expects


async def agent_ws(request: web.Request) -> web.WebSocketResponse:
    """PMView's agent socket goes to our pmai, whatever session id PMView picked."""
    browser = web.WebSocketResponse()
    await browser.prepare(request)
    while True:  # pmai serves only during `pmai run`: keep PMView connected and retry
        try:
            agent = await request.app["http"].ws_connect(AGENT_WS)
            break
        except aiohttp.ClientError:
            if browser.closed:
                return browser
            await browser.send_str('{"type":"ping"}')  # PMView reconnects after 31 s of silence
            await asyncio.sleep(1)

    async def pump(src, dst):
        async for msg in src:
            if msg.type == aiohttp.WSMsgType.TEXT:
                await dst.send_str(msg.data)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                await dst.send_bytes(msg.data)

    await asyncio.wait([asyncio.create_task(pump(browser, agent)), asyncio.create_task(pump(agent, browser))],
                       return_when=asyncio.FIRST_COMPLETED)
    await agent.close()
    await browser.close()
    return browser


async def spa(request: web.Request) -> web.FileResponse:
    p = safe_path(STATIC, request.match_info["path"])
    return web.FileResponse(p if p and p.is_file() else STATIC / "index.html")


# ---- :9000, control ---------------------------------------------------------

async def open_project(request: web.Request) -> web.Response:
    """Called by the agent before `pmai run`: load PMView on the project, preload structures."""
    ctx, page = request.app["ctx"], request.app["page"]
    await ctx.add_cookies([{"name": "PM_PROJECT", "value": request.query["project"],
                            "domain": "localhost", "path": "/"}])
    await page.goto(ORIGIN)
    await page.wait_for_function(pmview.READY, timeout=300_000)
    for pdb in os.environ.get("PRELOAD_PDB", "").split():
        await page.evaluate("id => window.handleLoadPDB(id)", pdb)
        await pmview.wait_for_system(page, pdb)
    for f in os.environ.get("PRELOAD_FILES", "").split():
        await page.evaluate("f => window.dispatchTool({tool_name: 'pmview_load', arguments: {files: [f]}})", f)
        await pmview.wait_for_system(page, Path(f).stem)
    return web.Response(text="ok")


async def healthz(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def state(request: web.Request) -> web.Response:  # the Python side returns loose JSON
    return web.json_response(pmview.parse_json_lenient(await request.app["page"].evaluate(pmview.VIEWER_STATE_JSON)))


async def selection(request: web.Request) -> web.Response:
    return web.json_response(pmview.parse_json_lenient(await request.app["page"].evaluate(pmview.VIEWER_SELECTION_JSON)))


async def shot(request: web.Request) -> web.Response:
    uri = await request.app["page"].evaluate(pmview.SCREENSHOT_DATA_URI)
    return web.Response(body=base64.b64decode(uri.split(",", 1)[1]), content_type="image/png")


async def export(request: web.Request) -> web.FileResponse:
    return web.FileResponse(await pmview.export_viewer_state(request.app["page"], Path(tempfile.mkdtemp())))


async def start_browser(app: web.Application) -> None:
    app["http"] = aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar())
    cookies = await login(app["http"])
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
    app["ctx"] = await browser.new_context(viewport={"width": 1280, "height": 800})
    await app["ctx"].add_cookies([{"name": k, "value": cookies[k].coded_value, "domain": "localhost", "path": p}
                                  for k, p in COOKIE_PATHS.items()])
    app["page"] = await app["ctx"].new_page()


async def main() -> None:
    origin = web.Application()
    origin.add_routes([
        web.get("/v3/agent/ws/{id}", agent_ws),
        web.get("/v3/file/{path:.*}", file_get),
        web.put("/v3/file/{path:.*}", file_put),
        web.route("*", "/v3/{path:.*}", proxy),
        web.get("/{path:.*}", spa),
    ])
    control = web.Application()
    control.add_routes([
        web.get("/healthz", healthz),
        web.get("/open", open_project), web.get("/state", state), web.get("/selection", selection),
        web.get("/shot", shot), web.get("/export", export),
    ])
    await start_browser(origin)
    for key in ("http", "ctx", "page"):
        control[key] = origin[key]
    for app, port in ((origin, 8080), (control, 9000)):
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", port).start()
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
```

`[verify]` items in this file:
- `pmview_run_python` needs `window.term` (the Console tab). If it is missing after `/open`, click the Console tab once.
- The access JWT lives `auth.jwt_expiration` minutes. PMView refreshes on 401 through the proxy, and `local_cookie` keeps the new cookie on our origin.
- `PM_PROJECT` decides the project; without it PMView asks `GET /v3/default-project` `[checked]`.

### 5.4 `viewer/Dockerfile`

```dockerfile
# The PMView version under test: pin this digest for release runs.
FROM europe-southwest1-docker.pkg.dev/repositories-368911/acellera-docker-apps/pmweb:latest AS pmweb

FROM mcr.microsoft.com/playwright/python:v1.58.0-noble
RUN pip install --no-cache-dir "aiohttp>=3.10"
COPY --from=pmweb /usr/share/nginx/html /srv/pmview
COPY viewer/ /srv/viewer/
WORKDIR /srv/viewer
EXPOSE 8080 9000
CMD ["python", "server.py"]
```

PMView loads jQuery, jquery.terminal, Pyodide 0.29.3, prismjs and fonts from CDNs at run time `[checked]`, so the sidecar needs internet.

### 5.5 `scripts/viewer_compose.yaml`

Harbor runs `docker compose` with the process env, so `${VAR}` works here `[checked]`. The named volume is filled from the image's `/app` on first use.

```yaml
services:
  main:
    volumes: ["project:/app"]
    depends_on:
      viewer: {condition: service_healthy}
  viewer:
    image: pmai-viewer:latest
    environment:
      PM_BACKEND_URL: ${PM_BACKEND_URL}
      PM_EMAIL: ${PM_EMAIL}
      PM_PASSWORD: ${PM_PASSWORD}
      PRELOAD_PDB: "@PDB@"
      PRELOAD_FILES: "@FILES@"
    volumes: ["project:/files/app"]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:9000/healthz')"]
      interval: 5s
      retries: 60
volumes:
  project:
```

### 5.6 Try the sidecar without Harbor

```bash
make viewer
docker run --rm -p 8080:8080 -p 9000:9000 --env-file .env \
  -e AGENT_WS=ws://host.docker.internal:8100/v1/ws/eval --add-host host.docker.internal:host-gateway \
  -v /tmp/t1:/files pmai-viewer:latest
curl "localhost:9000/open?project=app"
cd /tmp/t1/app && pmai run --serve --viewer-id eval --config /tmp/t1/home --prompt "Load PDB 1CRN in the viewer"
curl localhost:9000/state; curl -o shot.png localhost:9000/shot
```

### 5.7 Port molecular-visualization

```bash
uv run python scripts/cases_to_tasks.py eval_sets/acellera-bench/molecular-visualization tasks/molecular-visualization
make viewer && make run JOB=experiments/viewer.yaml
```

`experiments/viewer.yaml` is `acellera-noviewer.yaml` with `tasks/molecular-visualization`. Run the four phase 2 sets again with the viewer: add the compose file to them (`scripts/viewer_compose.yaml` with empty preloads).

### 5.8 Unit tests: `tests/test_viewer_server.py`

Add `aiohttp` to the `dev` extra: this test imports `viewer/server.py`.

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "viewer"))
from server import local_cookie, safe_path  # noqa: E402


def test_safe_path(tmp_path):
    assert safe_path(tmp_path, "app/a.pdb") == tmp_path / "app/a.pdb"
    assert safe_path(tmp_path, "../etc/passwd") is None


def test_local_cookie():
    h = 'access_token="Bearer x"; Domain=dev.acellera.playmolecule.ai; HttpOnly; Path=/v3; Secure; SameSite=strict'
    assert local_cookie(h) == 'access_token="Bearer x"; HttpOnly; Path=/v3; SameSite=strict'
```

**Done when:** molecular-visualization passes on Harbor at the old harness rate, and nobody opens a browser.

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

### 6.2 `config/pm/agent_config.yaml`

```yaml
port: 8100              # AGENT_API_URL defaults to http://localhost:8100/v1
sandbox:
  backend_type: local
plugins:
  playmolecule:
    backend_endpoint: http://computer19.acellera.lan:8002/v3
```

### 6.3 `experiments/pm-smoke.yaml`

```yaml
job_name: pm-smoke
datasets:
  - path: tasks/pm
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

### 6.4 `tasks/pm/proteinprepare/tests/test_case.py`

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
harbor run -c experiments/nightly.yaml -e modal -n 32     # only tasks with no bucket and no PM jobs
0 2 * * * cd ~/playmoleculeai-evals && make run JOB=experiments/nightly.yaml
```

Every trial keeps a production `agent.db`: the analysis dashboard can load them as they are.

---

## Risks

| Risk | Phase | Action |
|---|---|---|
| Provider keys and the service token are in the container env. The local backend gives `os.environ` to bash, so the agent can read them. | 1, 6 | Eval only keys. Later: strip them in `LocalBackend`. |
| The sandbox image user is not root | 1 | Restore `USER` in `image/Dockerfile`; set `[agent].user` if needed. |
| Bucket file owner: the backend and the cluster must read what the container writes | 6 | Run the agent as the bucket owner uid (`[agent].user`). |
| SwiftShader WebGL is slow, Pyodide takes time to load | 5 | `/open` waits up to 5 min; measure once. |
| PMView changes under us | 5 | Pin the `pmweb` digest in `viewer/Dockerfile`. |
| Harbor 0.x changes fast | all | Keep `harbor==0.24.0`; read the changelog before an upgrade. |
| Named compose volumes stay after a trial | 5 | `docker volume prune` in the nightly job. |
