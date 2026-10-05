import asyncio
import json
import shlex

from pmai_evals.agent import PmaiAgent
from test_trial import make_db


def run_script(tmp_path, **kwargs) -> str:
    agent = PmaiAgent(logs_dir=tmp_path, **kwargs)
    sent = []

    async def fake_exec(environment, command, **_):
        sent.append(command)

    agent.exec_as_agent = fake_exec
    asyncio.run(agent.run("it's a 'quoted' prompt", environment=None, context=None))
    return sent[0]


def test_script(tmp_path):
    s = run_script(tmp_path, model_name="openai/gpt-6-luna", flags="--backend local")
    assert "cp -r /opt/pmai-config/default/. /logs/agent/home/" in s
    assert 'FLAGS="--backend local"' in s
    assert "--config /logs/agent/home --model gpt-6-luna --output json" in s
    assert shlex.quote("it's a 'quoted' prompt") in s
    assert s.rstrip().endswith("> /logs/agent/events.jsonl")
    assert "trap 'chmod -R a+rwX /logs/agent' EXIT" in s


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
