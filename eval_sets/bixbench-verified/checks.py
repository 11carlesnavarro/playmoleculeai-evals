"""BixBench-Verified verifiers, pure Python.

Three verifiers mirror the upstream ``Future-House/BixBench`` eval modes
(``str_verifier``, ``range_verifier``, ``llm_verifier``) but run without
the LLM judge: cleaned-string equality plus bidirectional substring for
the open-ended modes, numeric in-range for the range mode.
"""

from __future__ import annotations

import re
from typing import Any

from pmai_evals.errors import AssertionConfigError
from pmai_evals.grading.assertions import PYTHON_CHECK_TYPE
from pmai_evals.runner.artifacts import RunArtifact
from pmai_evals.schemas import AssertionResult


_ANSWER_RE = re.compile(r"<answer>\s*(.*?)\s*</answer>", re.IGNORECASE | re.DOTALL)
_NON_ALNUM_RE = re.compile(r"[^a-zA-Z0-9]")
_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_RANGE_RE = re.compile(
    r"\(\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*,\s*"
    r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*\)"
)


def _result(score: float | bool, evidence: str) -> AssertionResult:
    return AssertionResult(
        assertion_type=PYTHON_CHECK_TYPE,
        score=float(score),
        evidence=evidence,
        config={},
    )


def _need(config: dict[str, Any], key: str) -> Any:
    if key not in config:
        raise AssertionConfigError(f"BixBench verifier missing required kwarg {key!r}")
    return config[key]


def _extract_answer(artifact: RunArtifact) -> str | None:
    matches = _ANSWER_RE.findall(artifact.final_answer())
    return matches[-1].strip() if matches else None


def _clean(text: str) -> str:
    return _NON_ALNUM_RE.sub("", text).lower()


def _first_number(text: str) -> float | None:
    match = _NUMBER_RE.search(text)
    return float(match.group(0)) if match else None


def bix_str_verifier(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    target = str(_need(config, "ideal"))
    predicted = _extract_answer(artifact)
    if predicted is None:
        return _result(0.0, f"no <answer> tag found; expected {target!r}")
    cleaned_target = _clean(target)
    cleaned_predicted = _clean(predicted)
    if not cleaned_predicted:
        return _result(0.0, f"empty predicted; expected {target!r}")
    if (
        cleaned_predicted == cleaned_target
        or cleaned_predicted in cleaned_target
        or cleaned_target in cleaned_predicted
    ):
        return _result(1.0, f"match: predicted={predicted!r}, target={target!r}")
    return _result(0.0, f"no match: predicted={predicted!r}, target={target!r}")


def bix_range_verifier(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    target = str(_need(config, "ideal"))
    predicted = _extract_answer(artifact)
    if predicted is None:
        return _result(0.0, f"no <answer> tag found; expected within {target}")
    bounds = _RANGE_RE.search(target)
    if bounds is None:
        raise AssertionConfigError(
            f"BixBench range target must be (low, high); got {target!r}"
        )
    low, high = sorted((float(bounds.group(1)), float(bounds.group(2))))
    value = _first_number(predicted)
    if value is None:
        return _result(
            0.0, f"no number in predicted={predicted!r}; expected within {target}"
        )
    if low <= value <= high:
        return _result(1.0, f"{value} ∈ [{low}, {high}]")
    return _result(0.0, f"{value} ∉ [{low}, {high}]")


bix_llm_verifier = bix_str_verifier
