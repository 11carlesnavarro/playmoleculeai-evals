"""Exact answer grading for the 3d-reasoning eval set."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from pmai_evals.grading.assertions import PYTHON_CHECK_TYPE
from pmai_evals.runner.artifacts import RunArtifact
from pmai_evals.schemas import AssertionResult

FIXTURES = Path(__file__).resolve().parent / "fixtures"
_ANSWER_RE = re.compile(r"<answer>\s*([ABCD])\s*</answer>", re.IGNORECASE)


@lru_cache(maxsize=1)
def _truth() -> dict[str, Any]:
    payload = json.loads((FIXTURES / "ground_truth.json").read_text(encoding="utf-8"))
    return payload["cases"]


def _result(score: float | bool, evidence: str) -> AssertionResult:
    return AssertionResult(
        assertion_type=PYTHON_CHECK_TYPE,
        score=float(score),
        evidence=evidence,
        config={},
    )


def answer_choice(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass only when one answer tag contains the gold candidate letter."""
    case_id = str(config.get("case_id", ""))
    case_truth = _truth().get(case_id)
    if case_truth is None:
        return _result(0.0, f"unknown case id {case_id!r}")
    matches = _ANSWER_RE.findall(artifact.final_answer())
    if len(matches) != 1:
        return _result(
            0.0,
            f"expected one answer tag with A, B, C, or D; found {len(matches)}",
        )
    received = matches[0].upper()
    expected = str(case_truth["answer"]).upper()
    return _result(
        received == expected,
        f"answer={received} expected={expected}",
    )
