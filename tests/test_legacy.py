from types import SimpleNamespace

from pmai_evals import legacy, trial
from pmai_evals.legacy import AssertionResult, RunArtifact, check


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
