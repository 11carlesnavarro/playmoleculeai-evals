"""The cases (evals/<eval>/cases/, Harbor tasks), the job files (evals/<eval>/*.yaml) and the images: mistakes
that Harbor finds only when a run starts, or never."""

import re
import tomllib
from pathlib import Path

import yaml

from pmai_evals.agent import PmaiAgent
from pmai_evals.review import _rubric

ROOT = Path(__file__).parent.parent
CASES = sorted(p.parent for p in ROOT.glob("evals/*/cases/*/task.toml"))
JOBS = sorted(ROOT.glob("evals/*/*.yaml"))


def name(path: Path) -> str:
    return str(path.relative_to(ROOT))


def task(case: Path) -> dict:
    return tomllib.loads((case / "task.toml").read_text())


def job_cases(job: Path) -> list[Path]:
    """The case folders that a job file runs."""
    return [ROOT / d["path"] / n for d in yaml.safe_load(job.read_text())["datasets"]
            for n in d.get("task_names") or sorted(p.name for p in (ROOT / d["path"]).iterdir())]


def test_tasks_parse():
    assert CASES and JOBS
    for case in CASES:
        task(case)  # a TOML error names the line


def test_tasks_have_one_image():
    """environment/Dockerfile or docker_image, not both: with both, Harbor takes the image and ignores the
    Dockerfile, so the input files that it copies are not there."""
    bad = [name(c) for c in CASES
           if (c / "environment/Dockerfile").exists() == ("docker_image" in task(c).get("environment", {}))]
    assert not bad, f"give environment/Dockerfile or docker_image, not none or both: {bad}"


def test_viewer_tasks_have_the_current_compose():
    """A viewer case (it sets VIEWER_PRELOAD) has a copy of docker/viewer/compose.yaml: Harbor refuses a link
    out of the task."""
    compose = (ROOT / "docker/viewer/compose.yaml").read_text()
    for case in CASES:
        copy = case / "environment/docker-compose.yaml"
        viewer = "VIEWER_PRELOAD" in task(case).get("environment", {}).get("env", {})
        assert viewer == copy.exists(), f"{name(case)}: VIEWER_PRELOAD and the compose copy go together"
        if copy.exists():
            assert copy.read_text() == compose, f"copy docker/viewer/compose.yaml to {name(copy)}"


def test_job_files_find_their_cases():
    """Each dataset path and task name exists, in the job file's own eval."""
    for job in JOBS:
        for d in yaml.safe_load(job.read_text())["datasets"]:
            assert d["path"] == f"evals/{job.parent.name}/cases", f"{name(job)}: {d['path']}"
        missing = [name(c) for c in job_cases(job) if not c.is_dir()]
        assert not missing, f"{name(job)}: not found: {missing}"


def test_agent_names_are_the_labels(tmp_path):
    """Harbor's viewer shows the agent name of the job file, its job summary the label: the same."""
    for job in JOBS:
        for arm in yaml.safe_load(job.read_text())["agents"]:
            agent = PmaiAgent(logs_dir=tmp_path, model_name=arm.get("model_name"), **arm.get("kwargs", {}))
            assert arm["name"] == agent.to_agent_info().name, name(job)


def test_scored_cases_have_tests():
    """A job file with the verifier on runs tests/test.sh of each case."""
    for job in JOBS:
        if (yaml.safe_load(job.read_text()).get("verifier") or {}).get("disable"):
            continue
        missing = [name(c) for c in job_cases(job) if not (c / "tests/test.sh").exists()]
        assert not missing, f"{name(job)}: no tests/test.sh in {missing}"


def test_rubrics_add_up_to_10():
    """Each tests/rubric.txt parses ("<points> <criterion>" a line) and its points add up to 10."""
    rubrics = sorted(ROOT.glob("evals/*/cases/*/tests/rubric.txt"))
    assert rubrics
    bad = [name(r) for r in rubrics if sum(line["points"] for line in _rubric(r)) != 10]
    assert not bad, f"the points do not add up to 10: {bad}"


def test_images_pin_the_versions_of_uv_lock():
    """The containers run what make test checks. playwright is not in uv.lock: its base image's version."""
    lock = {p["name"]: p["version"] for p in tomllib.loads((ROOT / "uv.lock").read_text())["package"]}
    for dockerfile in ROOT.glob("docker/*/Dockerfile"):
        text = dockerfile.read_text()
        base = re.search(r"^FROM \S+:v?([\d.]+)", text, re.M)
        for package, version in re.findall(r"([\w-]+)==([\w.]+)", text):
            expected = lock[package] if package in lock else base and base[1]
            assert version == expected, f"{name(dockerfile)}: {package}=={version}, not {expected}"
