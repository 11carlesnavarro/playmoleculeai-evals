"""Harbor agent: one PlayMoleculeAI turn with `pmai run`, inside the trial container."""

import shlex
from pathlib import PurePosixPath
from typing import Literal

from harbor.agents.installed.base import BaseInstalledAgent, with_prompt_template
from harbor.agents.options import InstalledAgentOptions
from pydantic import Field

from pmai_evals import trial

HOME = "/logs/agent/home"  # pmai config home: agent_config.yaml + agent.db, synced to the host
# Viewer tasks only: the sidecar opens PMView on this project. No sidecar: fails at once.
OPEN_VIEWER = (
    'python3 -c "import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=600)" '
    '"http://viewer:9000/open?project=$(basename "$PWD")" 2>/dev/null'
)


class PmaiOptions(InstalledAgentOptions):
    pmai_config: str = Field("/opt/pmai-config/default", description="Config folder in the image.")
    work: str = Field("/app", description="Project folder: the agent's cwd.")
    flags: str = Field("", description="Extra `pmai run` flags.")
    skills: str = Field(
        "", description="Folder in the container whose skills replace the image skills. Mount it in the job."
    )
    # Harbor's viewer shows this kwarg in its reasoning effort column
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high", "xhigh"] | None = Field(
        None, description="Replaces the config's reasoning effort."
    )


class PmaiAgent(BaseInstalledAgent):
    options_model = PmaiOptions

    @staticmethod
    def name() -> str:
        return "pmai"

    def to_agent_info(self):
        """Harbor's job summary groups trials by this name: pmai, pmai-no-skills, pmai-effort-low, ...
        The arm `name` in the job file must be the same (tests/test_agent.py checks it)."""
        o, parts = self.options, [self.name()]
        if (config := PurePosixPath(o.pmai_config).name) != "default":
            parts.append(config)
        if o.skills:
            parts.append(PurePosixPath(o.skills).name)
        if o.reasoning_effort:
            parts.append(f"effort-{o.reasoning_effort}")
        return super().to_agent_info().model_copy(update={"name": "-".join(parts)})

    async def install(self, environment) -> None:
        await self.exec_as_agent(environment, command="pmai --help > /dev/null")  # baked in the image

    @with_prompt_template
    async def run(self, instruction, environment, context) -> None:
        o = self.options
        model = (self.model_name or "").split("/")[-1]
        model_flag = f"--model {shlex.quote(model)}" if model else ""  # none: the config's default
        skills = (
            f'rm -rf "${{PMAI_HOME:?}}/skills" && cp -r {shlex.quote(o.skills)} "$PMAI_HOME/skills"'
            if o.skills
            else ""
        )
        cfg, e = f"{HOME}/agent_config.yaml", o.reasoning_effort
        effort = (  # reasoning.effort: the only effort with 2 spaces of indent
            f"sed -i 's/^  effort: .*/  effort: {e}/' {cfg} && grep -q '^  effort: {e}$' {cfg}" if e else ""
        )
        await self.exec_as_agent(
            environment,
            command=f"""
set -e
# also when pmai fails: the host user can then read agent.db and delete the trial folder
# keep the exit code: parts of /logs/agent belong to the host user, and chmod fails there
trap 'rc=$?; chmod -R a+rwX /logs/agent 2>/dev/null || true; exit $rc' EXIT
mkdir -p {HOME} {o.work}
cp -r {o.pmai_config}/. {HOME}/
{effort}
{skills}
echo {o.work} > /logs/agent/work_dir
cd {o.work}
FLAGS="{o.flags}"
if {OPEN_VIEWER}; then FLAGS="$FLAGS --serve --viewer-id eval"; fi
pmai run $FLAGS --config {HOME} {model_flag} --output json \\
  --prompt {shlex.quote(instruction)} > /logs/agent/events.jsonl
""",
        )

    def populate_context_post_run(self, context) -> None:
        db = self.logs_dir / "home" / "agent.db"
        try:
            u = trial.usage(db) if db.exists() else None
        except Exception as exc:  # Harbor calls this before the verifier: an error here stops the trial
            self.logger.warning(f"no usage from {db}: {exc!r}")
            u = None
        if u:
            context.n_input_tokens = u["input_tokens"]
            context.n_cache_tokens = u["cached_tokens"]
            context.n_output_tokens = u["output_tokens"]
            context.cost_usd = u["cost_usd"]
