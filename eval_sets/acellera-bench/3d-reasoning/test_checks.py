"""Tests for the exact answer grader and the frozen case declarations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from pmai_evals.eval_loader import load_eval_set
from pmai_evals.runner.artifacts import RunArtifact

SET_DIR = Path("eval_sets/acellera-bench/3d-reasoning")
EVAL_SET = load_eval_set("acellera-bench/3d-reasoning", root=Path("eval_sets"))
CHECKS = cast(Any, EVAL_SET.checks_module)
TRUTH = json.loads((SET_DIR / "fixtures/ground_truth.json").read_text(encoding="utf-8"))["cases"]


def artifact(tmp_path: Path, answer: str) -> RunArtifact:
    result = RunArtifact(run_dir=tmp_path / "run", case_id="c", model="m", seed=1)
    result.cell_dir.mkdir(parents=True, exist_ok=True)
    result.final_answer_path.write_text(answer, encoding="utf-8")
    return result


def score(tmp_path: Path, case_id: str, answer: str) -> float:
    return CHECKS.answer_choice(artifact(tmp_path, answer), {"case_id": case_id}).score


def test_eval_set_has_ten_project_only_cases() -> None:
    assert len(EVAL_SET.cases) == 10
    assert EVAL_SET.spec.default_timeout_s is None
    assert {case.id for case in EVAL_SET.cases} == set(TRUTH)
    for case in EVAL_SET.cases:
        assert case.preload.project.files
        assert not case.preload.viewer.pdb_ids
        assert not case.preload.viewer.files
        assert len(case.assertions) == 1
        assert case.rubric.enabled is False


@pytest.mark.parametrize("case_id", sorted(TRUTH))
def test_gold_answer_passes(tmp_path: Path, case_id: str) -> None:
    answer = TRUTH[case_id]["answer"]
    assert score(tmp_path, case_id, f"<answer>{answer}</answer>") == 1.0


@pytest.mark.parametrize("case_id", sorted(TRUTH))
def test_lowercase_gold_answer_passes(tmp_path: Path, case_id: str) -> None:
    answer = TRUTH[case_id]["answer"].lower()
    assert score(tmp_path, case_id, f"<answer> {answer} </answer>") == 1.0


@pytest.mark.parametrize("case_id", sorted(TRUTH))
def test_wrong_answer_fails(tmp_path: Path, case_id: str) -> None:
    expected = TRUTH[case_id]["answer"]
    wrong = next(letter for letter in "ABCD" if letter != expected)
    assert score(tmp_path, case_id, f"<answer>{wrong}</answer>") == 0.0


@pytest.mark.parametrize(
    "answer",
    ["A", "<answer>E</answer>", "", "<answer>A</answer><answer>B</answer>"],
)
def test_missing_or_ambiguous_answer_fails(tmp_path: Path, answer: str) -> None:
    assert score(tmp_path, "dr-0001", answer) == 0.0


def test_agent_files_do_not_contain_source_names() -> None:
    banned = {
        "1iep",
        "4wkq",
        "2w26",
        "2p16",
        "3og7",
        "7aad",
        "7tll",
        "1ycr",
        "1bxl",
        "4zqk",
        "imatinib",
        "gefitinib",
        "rivaroxaban",
        "apixaban",
        "vemurafenib",
        "olaparib",
        "nirmatrelvir",
        "mdm2",
        "p53",
        "bcl-xl",
        "bak",
        "pd-1",
        "pd-l1",
    }
    visible = {
        SET_DIR / "fixtures" / name
        for case in EVAL_SET.cases
        for name in case.preload.project.files
    }
    for path in visible:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        found = sorted(token for token in banned if token in text)
        assert not found, f"{path} contains source name(s): {found}"
