"""One time port: eval_sets/<set>/ -> tasks/<set>/<case>/, with the old checks unchanged.

uv run python scripts/cases_to_tasks.py eval_sets/acellera-bench/structure-analysis tasks/structure-analysis
"""

import json
import re
import shutil
import sys
from pathlib import Path

import yaml

IMAGE = "pmai-eval:latest"
HERE = Path(__file__).parent
VIEWER_COMPOSE = HERE.parent / "viewer/compose.yaml"
VIEWER_DATA = re.compile(r"artifact\.(viewer_state|viewer_selection|load_system|system_files)")
TEST_SH = "#!/bin/bash\nPYTHONPATH=/opt exec /opt/grader/bin/pytest /tests -q -p pmai_evals.reward\n"
TOML = """schema_version = "1.4"

[task]
name = "acellera/{id}"
keywords = {tags}

[agent]
timeout_sec = {timeout}

[verifier]
timeout_sec = 600

[environment]
{image}network_mode = "public"
cpus = 2
memory_mb = 8192
{env}"""


def port(src: Path, out: Path) -> None:
    spec = yaml.safe_load((src / "eval_set.yaml").read_text())
    checks = re.sub(
        r"^from pmai_evals\.[\w.]+ import ",
        "from pmai_evals.legacy import ",
        (src / "checks.py").read_text(),
        flags=re.M,
    )
    viewer = bool(VIEWER_DATA.search(checks))  # the set's tasks get the viewer sidecar
    truth = sorted(set(re.findall(r'FIXTURES / "([^"]+)"', checks)))  # files the checks read
    for case in yaml.safe_load((src / "cases.yaml").read_text())["cases"]:
        task = out / case["id"]
        shutil.rmtree(task, ignore_errors=True)
        (task / "tests").mkdir(parents=True)
        pre = case.get("preload") or {}
        view = pre.get("viewer") or {}
        if view.get("pdb_ids") and not viewer:  # the prompts name the entries: the agent can get them
            print(f"{case['id']}: no viewer, {view['pdb_ids']} not preloaded")
        # the old harness uploaded each file to the project root by its basename
        files = [Path(f) for f in (pre.get("project") or {}).get("files", []) + view.get("files", [])]
        env = task / "environment"  # Harbor needs it, also when it is empty
        env.mkdir()
        for f in files:
            shutil.copy(src / "fixtures" / f, env / f.name)
        if files:
            env.joinpath("Dockerfile").write_text(
                f"FROM {IMAGE}\nCOPY {' '.join(f.name for f in files)} /app/\n"
            )
        else:
            env.joinpath(".gitkeep").touch()
        preload = ""
        if viewer:  # a copy: Harbor refuses a link out of the task (git datasets)
            shutil.copy(VIEWER_COMPOSE, env / "docker-compose.yaml")
            start = {"pdb_ids": view.get("pdb_ids"), "files": [Path(f).name for f in view.get("files", [])]}
            start = {k: v for k, v in start.items() if v}  # the files are in /app too (above)
            preload = f"env = {{ VIEWER_PRELOAD = {json.dumps(json.dumps(start) if start else '')} }}\n"
        timeout = case.get("timeout_s") or spec.get("default_timeout_s") or 1800
        (task / "task.toml").write_text(
            TOML.format(
                id=case["id"],
                tags=json.dumps(case.get("tags", [])),
                timeout=timeout,
                image="" if files else f'docker_image = "{IMAGE}"\n',
                env=preload,
            )
        )
        (task / "instruction.md").write_text(case["prompt"])
        (task / "tests/test.sh").write_text(TEST_SH)
        (task / "tests/test.sh").chmod(0o755)
        (task / "tests/checks.py").write_text(checks)
        shutil.copy(HERE / "legacy_test_case.py", task / "tests/test_case.py")
        specs = [
            {"function": a["function"], "kwargs": a.get("kwargs") or {}}
            for a in case.get("assertions", [])
            if a["type"] == "python_check"
        ]
        (task / "tests/assertions.json").write_text(json.dumps(specs, indent=2) + "\n")
        for name in truth:
            (task / "tests/fixtures").mkdir(exist_ok=True)
            shutil.copy(src / "fixtures" / name, task / "tests/fixtures" / name)
    print(f"{out}: {len(list(out.iterdir()))} tasks")


if __name__ == "__main__":
    port(Path(sys.argv[1]), Path(sys.argv[2]))
