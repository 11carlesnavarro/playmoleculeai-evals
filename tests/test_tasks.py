"""The ported tasks (scripts/cases_to_tasks.py)."""

from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_viewer_tasks_have_the_current_compose():
    """Each viewer task has a copy of viewer/compose.yaml: Harbor refuses a link out of the task."""
    compose = (ROOT / "viewer/compose.yaml").read_text()
    copies = sorted(ROOT.glob("tasks/*/*/environment/docker-compose.yaml"))
    assert copies
    old = [str(c.relative_to(ROOT)) for c in copies if c.read_text() != compose]
    assert not old, f"copy viewer/compose.yaml to: {old}"


def test_tasks_have_an_image():
    """A task builds environment/Dockerfile, else it names docker_image: else Harbor fails at the build."""
    tomls = sorted(ROOT.glob("tasks/*/*/task.toml"))
    assert tomls
    bad = [str(t.parent.relative_to(ROOT)) for t in tomls
           if not (t.parent / "environment/Dockerfile").exists() and "docker_image" not in t.read_text()]
    assert not bad, f"no environment/Dockerfile and no docker_image: {bad}"
