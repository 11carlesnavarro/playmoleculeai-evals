import asyncio
import json
import os
import shlex
import subprocess
from pathlib import Path

import yaml

from pmai_evals.agent import PmaiAgent
from test_trial import fake_viewer, make_db


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


def test_script(tmp_path):
    s = run_script(tmp_path, model_name="openai/gpt-6-luna", flags="--backend local")
    assert "cp -r /opt/pmai-config/default/. /logs/agent/home/" in s
    assert 'FLAGS="--backend local"' in s
    assert "--config /logs/agent/home --model gpt-6-luna --output json" in s
    assert shlex.quote("it's a 'quoted' prompt") in s
    assert s.rstrip().endswith("> /logs/agent/events.jsonl")


def test_viewer(tmp_path):
    """VIEWER_URL (viewer tasks): /open, then --viewer-id. A 503 stops the script with the reason."""
    lines = run_script(tmp_path, flags="--backend local").splitlines()
    start = next(i for i, x in enumerate(lines) if x.startswith("FLAGS="))
    block = "\n".join(["set -e", *lines[start : lines.index("fi", start) + 1], 'echo "$FLAGS"'])
    project = tmp_path / "p1"
    project.mkdir()

    def run(**env):
        env = {"PATH": os.environ["PATH"], **env}
        return subprocess.run(["bash", "-c", block], env=env, cwd=project, text=True, capture_output=True)

    assert run().stdout == "--backend local\n"  # not a viewer task
    routes = {"/open?project=p1": (200, b"ready")}
    with fake_viewer(routes) as url:
        assert run(VIEWER_URL=url).stdout == "--backend local --viewer-id eval\n"
        routes["/open?project=p1"] = (503, b"no WebGL2: Mol* cannot draw")
        r = run(VIEWER_URL=url)
    assert (r.returncode, r.stdout, r.stderr) == (1, "", "viewer /open: 503 no WebGL2: Mol* cannot draw\n")


def test_no_model(tmp_path):
    s = run_script(tmp_path, pmai_config="/opt/pmai-config/pm", work="/data/p1")
    assert "--model" not in s
    assert "cd /data/p1" in s and "/opt/pmai-config/pm/." in s


def test_context(tmp_path):
    (tmp_path / "home").mkdir()
    make_db(tmp_path / "home" / "agent.db")

    class Ctx:
        pass

    ctx = Ctx()
    PmaiAgent(logs_dir=tmp_path).populate_context_post_run(ctx)
    assert (ctx.n_input_tokens, ctx.n_cache_tokens, ctx.n_output_tokens, ctx.cost_usd) == (10, 4, 3, 0.25)
    assert json.loads(json.dumps(vars(ctx)))  # plain numbers, as Harbor stores them


def test_context_never_raises(tmp_path):
    """Harbor calls the hook before the verifier: an error there would stop the trial."""
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "agent.db").write_text("not a database")

    class Ctx:
        pass

    ctx = Ctx()
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
    assert label(tmp_path, pmai_config="/opt/pmai-config/no-skills") == "pmai-no-skills"
    assert label(tmp_path, reasoning_effort="low") == "pmai-effort-low"


def test_reasoning_effort(tmp_path):
    """The script line sets the top level effort of the real config, not the effort of a model entry."""
    home = tmp_path / "logs/agent/home"
    home.mkdir(parents=True)
    default = Path("config/default/agent_config.yaml").read_text()
    (home / "agent_config.yaml").write_text(default)
    line = script_line(tmp_path, "sed ", reasoning_effort="low")
    subprocess.run(["bash", "-c", line.replace("/logs/", f"{tmp_path}/logs/")], check=True)
    cfg = yaml.safe_load((home / "agent_config.yaml").read_text())
    assert cfg["reasoning"]["effort"] == "low" and yaml.safe_load(default)["reasoning"]["effort"] == "xhigh"
    assert cfg["available_models"] == yaml.safe_load(default)["available_models"]
    assert "sed " not in run_script(tmp_path)  # no option: the config's effort


def test_arm_names_are_the_labels(tmp_path):
    """The viewer shows the job file name, the job summary the label: they must be the same."""
    for job in Path("experiments").glob("*.yaml"):
        for arm in yaml.safe_load(job.read_text())["agents"]:
            assert arm["name"] == label(tmp_path, **arm.get("kwargs", {})), job


def test_no_skills_is_default_without_skills():
    def load(name):
        return yaml.safe_load(Path(f"config/{name}/agent_config.yaml").read_text())

    default = load("default")
    del default["plugins"]["skills"]
    assert load("no-skills") == default
