import asyncio
import json
import os
import shlex
import subprocess
from pathlib import Path
from types import SimpleNamespace

import yaml

from helpers import fake_viewer, make_db
from pmai_evals.agent import KEEP_VIEW, PmaiAgent

ROOT = Path(__file__).parent.parent


def run_script(tmp_path, **kwargs) -> str:
    agent = PmaiAgent(logs_dir=tmp_path, **kwargs)
    sent = []

    async def fake_exec(environment, command, **_):
        sent.append(command)

    agent.exec_as_agent = fake_exec
    asyncio.run(agent.run("it's a 'quoted' prompt", environment=None, context=None))
    return sent[0]


def script_line(tmp_path, start: str, **kwargs) -> str:
    return next(x for x in run_script(tmp_path, **kwargs).splitlines() if x.startswith(start))


def bash(block: str, cwd=None, **env) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ["PATH"], **env}
    return subprocess.run(["bash", "-c", block], env=env, cwd=cwd, text=True, capture_output=True)


def from_line(tmp_path, start: str) -> str:
    """The script from its first line that starts with `start`, with a fake pmai that prints its arguments
    and returns $RC."""
    lines = run_script(tmp_path, model_name="openai/gpt-6-luna").splitlines()
    first = next(i for i, x in enumerate(lines) if x.startswith(start))
    block = "\n".join(["set -e", 'pmai() { echo "$@"; return ${RC:-0}; }', *lines[first:]])
    return block.replace(KEEP_VIEW, "echo kept").replace(" > /logs/agent/events.jsonl", "")


def test_script(tmp_path):
    s = run_script(tmp_path, model_name="openai/gpt-6-luna")
    assert "cp -r /opt/pmai-config/. /logs/agent/home/" in s and "cd /app" in s
    assert "--config /logs/agent/home --model gpt-6-luna --output json" in s
    assert shlex.quote("it's a 'quoted' prompt") in s
    assert "> /logs/agent/events.jsonl || status=$?" in s
    assert "--model" not in run_script(tmp_path)  # no model: the config's default


def test_viewer(tmp_path):
    """VIEWER_URL (viewer tasks): /open, then --viewer-id. A 503 stops the script with the reason."""
    block, project = from_line(tmp_path, 'if [ -n "${VIEWER_URL'), tmp_path / "p1"
    project.mkdir()
    assert bash(block, project).stdout.startswith("run --config ")  # not a viewer task
    routes = {"/open?project=p1": (200, b"ready")}
    with fake_viewer(routes) as url:
        assert bash(block, project, VIEWER_URL=url).stdout.startswith("run --viewer-id eval --config ")
        routes["/open?project=p1"] = (503, b"no WebGL2: Mol* cannot draw")
        r = bash(block, project, VIEWER_URL=url)
    assert (r.returncode, r.stdout, r.stderr) == (1, "", "viewer /open: 503 no WebGL2: Mol* cannot draw\n")


def test_keeps_the_view(tmp_path):
    """After the turn, also a failed one, a viewer task keeps the final view. The exit code stays pmai's."""
    block = from_line(tmp_path, "pmai run")
    for env, kept in [({}, False), ({"VIEWER_URL": "http://viewer"}, True)]:  # not a viewer task, then one
        r = bash(block, RC="3", **env)
        assert (r.returncode, r.stdout.endswith("kept\n")) == (3, kept)


def test_provider_stop_is_an_api_error(tmp_path):
    """A provider stop ([LLM_FAILED]) is an UnknownApiError: the job runs the trial again."""
    out = ("Upgraded the config\n[LLM_FAILED] model=gpt-6-luna code=bio_policy message=This content was "
           "flagged for possible biological risk.\n")
    error = PmaiAgent(logs_dir=tmp_path)._classify_exec_error("pmai run", SimpleNamespace(
        return_code=1, stdout=out, stderr=None))
    assert type(error).__name__ == "UnknownApiError"
    assert type(PmaiAgent(logs_dir=tmp_path)._classify_exec_error("pmai run", SimpleNamespace(
        return_code=1, stdout="Traceback: KeyError", stderr=None))).__name__ == "NonZeroAgentExitCodeError"


def test_context(tmp_path):
    (tmp_path / "home").mkdir()
    make_db(tmp_path / "home" / "agent.db")

    ctx = SimpleNamespace()
    PmaiAgent(logs_dir=tmp_path).populate_context_post_run(ctx)
    assert (ctx.n_input_tokens, ctx.n_cache_tokens, ctx.n_output_tokens, ctx.cost_usd) == (10, 4, 2, 0.03)
    assert json.loads((tmp_path / "trajectory.json").read_text())["steps"]


def test_context_never_raises(tmp_path):
    """Harbor calls the hook before the verifier: an error there would stop the trial."""
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "agent.db").write_text("not a database")

    ctx = SimpleNamespace()
    PmaiAgent(logs_dir=tmp_path).populate_context_post_run(ctx)
    assert not vars(ctx)


def test_exit_trap_keeps_the_exit_code(tmp_path):
    """The trap chmods /logs/agent. Here it does not exist, so chmod fails, as on parts owned by the host."""
    lines = run_script(tmp_path).splitlines()
    head = "\n".join([lines[1], script_line(tmp_path, "trap ")])
    assert head.startswith("set -e")
    for end, code in [("true", 0), ("false", 1), ("exit 3", 3)]:
        assert subprocess.run(["bash", "-c", f"{head}\n{end}"]).returncode == code


def label(tmp_path, **kwargs) -> str:
    return PmaiAgent(logs_dir=tmp_path, model_name="gpt-6-luna", **kwargs).to_agent_info().name


def test_label(tmp_path):
    assert label(tmp_path) == "pmai"
    assert label(tmp_path, reasoning_effort="low") == "pmai-effort-low"


def test_reasoning_effort(tmp_path):
    """The script line sets the top level effort of the real config, not the effort of a model entry."""
    home = tmp_path / "logs/agent/home"
    home.mkdir(parents=True)
    default = (ROOT / "docker/agent_config.yaml").read_text()
    (home / "agent_config.yaml").write_text(default)
    line = script_line(tmp_path, "sed ", reasoning_effort="low")
    subprocess.run(["bash", "-c", line.replace("/logs/", f"{tmp_path}/logs/")], check=True)
    cfg = yaml.safe_load((home / "agent_config.yaml").read_text())
    assert cfg["reasoning"]["effort"] == "low" != yaml.safe_load(default)["reasoning"]["effort"]
    assert cfg["available_models"] == yaml.safe_load(default)["available_models"]
    assert "sed " not in run_script(tmp_path)  # no option: the config's effort

