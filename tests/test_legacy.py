from types import SimpleNamespace

import pytest

from pmai_evals import legacy, trial
from pmai_evals.legacy import AssertionResult, RunArtifact, check
from pmai_evals.reward import InfraError


def test_check(tmp_path, monkeypatch):
    monkeypatch.setattr(trial, "WORK", tmp_path)
    monkeypatch.setattr(trial, "answer", lambda: "<answer>B</answer>")
    seen = []

    def ok(artifact: RunArtifact, config: dict) -> AssertionResult:
        seen.append((artifact.project_files_dir, artifact.final_answer(), config))
        return AssertionResult(legacy.PYTHON_CHECK_TYPE, 0.5, "half")

    def crash(artifact, config):
        raise KeyError("x")

    checks = SimpleNamespace(ok=ok, crash=crash)
    assert check(checks, "ok", case_id="dr-1") == 0.5
    assert seen == [(tmp_path, "<answer>B</answer>", {"case_id": "dr-1", "function": "ok"})]
    assert check(checks, "crash") == 0.0  # as in the old grader


def test_viewer_adapter(monkeypatch):
    rep = {"sel": "chain A", "style": "cartoon", "visibility": True, "color": "#0000ff", "opacity": 1}
    state = {"systems": {
        "u1": {"name": "2ITY", "type": "structure", "visible": True,
               "representations": [rep, {**rep, "color": "element-symbol"}]},
        "v1": {"name": "map", "type": "volume"},
        "u2": {"name": None, "type": "structure", "visible": False, "representations": [rep]},
    }}
    monkeypatch.setattr(trial, "viewer_state", lambda: state)
    artifact = RunArtifact()
    old = {"type": "cartoon", "selection": "chain A", "visibility": True, "color_value": "#0000ff"}
    assert artifact.viewer_state() == [  # the newest first, no volumes
        {"moleculeID": "u2", "name": "", "representations": [{**old, "visibility": False}]},  # hidden system
        {"moleculeID": "u1", "name": "2ITY", "representations": [old, {**old, "color_value": None}]},
    ]
    assert artifact.system_files() == [("", None), ("2ITY", None)]
    with pytest.raises(KeyError, match="1JPZ"):
        artifact.load_system("1JPZ")

    def down(artifact, config):
        trial.viewer_state()

    def no_viewer():
        raise InfraError("viewer /python: 503")

    monkeypatch.setattr(trial, "viewer_state", no_viewer)
    with pytest.raises(InfraError):  # no reward, not a 0
        check(SimpleNamespace(down=down), "down")
