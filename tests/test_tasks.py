"""The cases: evals/<eval>/cases/ (Harbor tasks)."""

from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent


def test_viewer_tasks_have_the_current_compose():
    """Each viewer task has a copy of docker/viewer/compose.yaml: Harbor refuses a link out of the task."""
    compose = (ROOT / "docker/viewer/compose.yaml").read_text()
    copies = sorted(ROOT.glob("evals/*/cases/**/environment/docker-compose.yaml"))
    assert copies
    old = [str(c.relative_to(ROOT)) for c in copies if c.read_text() != compose]
    assert not old, f"copy docker/viewer/compose.yaml to: {old}"


def test_tasks_have_an_image():
    """A task builds environment/Dockerfile, else it names docker_image: else Harbor fails at the build."""
    tomls = sorted(ROOT.glob("evals/*/cases/**/task.toml"))
    assert tomls
    bad = [str(t.parent.relative_to(ROOT)) for t in tomls
           if not (t.parent / "environment/Dockerfile").exists() and "docker_image" not in t.read_text()]
    assert not bad, f"no environment/Dockerfile and no docker_image: {bad}"


def test_job_files_find_their_cases():
    """Each dataset path and task name in evals/*/*.yaml exists: a wrong one fails only when Harbor starts."""
    jobs = sorted(ROOT.glob("evals/*/*.yaml"))
    assert jobs
    missing = [f"{job.relative_to(ROOT)}: {d['path']}/{name}"
               for job in jobs for d in yaml.safe_load(job.read_text())["datasets"]
               for name in d.get("task_names") or [""] if not (ROOT / d["path"] / name).is_dir()]
    assert not missing, f"not found: {missing}"
