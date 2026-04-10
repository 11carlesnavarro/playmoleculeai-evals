"""Test the grade-the-grader critique pass."""

from __future__ import annotations

import json
from pathlib import Path

from pmai_evals.grading.critique import critique_run


def _write_grade(run_dir: Path, model: str, passed: bool) -> None:
    cell = run_dir / "c1" / model / "seed-0"
    cell.mkdir(parents=True)
    (cell / "status").write_text("completed\n")
    grade = {
        "case_id": "c1",
        "model": model,
        "seed": 0,
        "assertions": [
            {
                "assertion_type": "tool_called",
                "passed": passed,
                "evidence": "...",
                "config": {"name": "pmview_load"},
            }
        ],
        "rubric": None,
        "summary": {
            "assertions_passed": 1 if passed else 0,
            "assertions_total": 1,
            "rubric_passed": None,
        },
    }
    (cell / "grade.json").write_text(json.dumps(grade), encoding="utf-8")


def test_critique_flags_universal_pass(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_grade(run_dir, "model-a", True)
    _write_grade(run_dir, "model-b", True)
    result = critique_run(run_dir)
    findings = result["non_discriminating"]
    assert any("passes for all" in f["reason"] for f in findings)


def test_critique_flags_universal_fail(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_grade(run_dir, "model-a", False)
    _write_grade(run_dir, "model-b", False)
    result = critique_run(run_dir)
    findings = result["non_discriminating"]
    assert any("fails for all" in f["reason"] for f in findings)


def test_critique_no_finding_when_discriminating(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_grade(run_dir, "model-a", True)
    _write_grade(run_dir, "model-b", False)
    result = critique_run(run_dir)
    assert result["non_discriminating"] == []
