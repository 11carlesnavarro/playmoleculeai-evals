"""BixBench verifiers, mirroring ``Future-House/BixBench:bixbench/graders.py``.

Score parity with the upstream open-ended path: ``str_verifier`` does
alphanumeric-only equality, then substring containment, then an LLM
fallback; ``range_verifier`` and ``llm_verifier`` go straight to the
judge with the upstream prompts.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from pmai_evals.config import Settings
from pmai_evals.errors import AssertionConfigError
from pmai_evals.grading.assertions import PYTHON_CHECK_TYPE
from pmai_evals.runner.artifacts import RunArtifact
from pmai_evals.schemas import AssertionResult


# Verbatim from bixbench/prompts.py so the judge sees the same input.
OPEN_ENDED_GRADING_PROMPT = """You are given a question, target answer and a predicted answer. Your task is to compare the target answer with the predicted and assess if the predicted answer is correct, incorrect or it refused to answer.
Question: {question}
Target Answer: {target}
Predicted Answer: {predicted}

Important: You must only output one from `correct`, `incorrect` or `refused` between <grade> tags.
Example Output: <grade> correct </grade>
"""

OPEN_ENDED_RANGE_GRADING_PROMPT = """You are given a question, target range using the format (lower,upper) and a predicted answer. Your task is to compare the target range with the predicted and assess if the predicted answer falls within the specified range. If it falls within the range, it is correct, otherwise it is incorrect. If the predicted answer cannot be compared to the target range, it is refused to answer.
Question: {question}
Target Range: {target}
Predicted Answer: {predicted}

Important: You must only output one from `correct`, `incorrect` or `refused` between <grade> tags.
Example Output: <grade> correct </grade>
"""

DEFAULT_JUDGE_MODEL = "claude-sonnet-4-6"

_ANSWER_RE = re.compile(r"<answer>\s*(.*?)\s*</answer>", re.IGNORECASE | re.DOTALL)
_GRADE_RE = re.compile(r"<grade>\s*(.*?)\s*</grade>", re.DOTALL)
_NON_ALNUM_RE = re.compile(r"[^a-zA-Z0-9]")


def _result(passed: bool, evidence: str) -> AssertionResult:
    return AssertionResult(
        assertion_type=PYTHON_CHECK_TYPE,
        passed=passed,
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


def _parse_grade(response: str) -> str:
    # Only `correct` passes; `incorrect`/`refused`/anything else fails — matches
    # the upstream ``GradingFunction._parse_grade_response``.
    match = _GRADE_RE.search(response)
    return match.group(1).strip().lower() if match else ""


@lru_cache(maxsize=1)
def _cached_client(api_key: str) -> Any:
    from anthropic import Anthropic

    return Anthropic(api_key=api_key)


def _client() -> Any | None:
    api_key = Settings().anthropic_api_key
    return _cached_client(api_key) if api_key else None


def _llm_grade(
    *,
    question: str,
    target: str,
    predicted: str,
    template: str,
    judge_model: str,
) -> tuple[bool, str]:
    client = _client()
    if client is None:
        return False, "ANTHROPIC_API_KEY missing; cannot run BixBench LLM grader"
    prompt = template.format(question=question, target=target, predicted=predicted)
    try:
        response = client.messages.create(
            model=judge_model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        return False, f"judge call failed: {type(exc).__name__}: {exc}"

    text = "".join(
        getattr(block, "text", "")
        for block in response.content
        if getattr(block, "type", "") == "text"
    ).strip()
    verdict = _parse_grade(text)
    snippet = (text[:160] + "...") if len(text) > 160 else text
    return verdict == "correct", f"verdict={verdict or '?'}; raw={snippet!r}"


def _verify_via_llm(
    artifact: RunArtifact, config: dict[str, Any], template: str
) -> AssertionResult:
    target = str(_need(config, "ideal"))
    predicted = _extract_answer(artifact)
    if predicted is None:
        return _result(False, f"no <answer> tag found; expected {target!r}")
    correct, evidence = _llm_grade(
        question=str(config.get("question") or ""),
        target=target,
        predicted=predicted,
        template=template,
        judge_model=str(config.get("judge_model") or DEFAULT_JUDGE_MODEL),
    )
    return _result(correct, evidence)


def bix_str_verifier(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    target = str(_need(config, "ideal"))
    predicted = _extract_answer(artifact)
    if predicted is None:
        return _result(False, f"no <answer> tag found; expected {target!r}")

    cleaned_target = _clean(target)
    cleaned_predicted = _clean(predicted)
    if cleaned_predicted == cleaned_target:
        return _result(True, f"exact match: predicted={predicted!r}")
    if cleaned_predicted and cleaned_predicted in cleaned_target:
        return _result(
            True, f"partial match: predicted={predicted!r} ⊂ target={target!r}"
        )

    correct, evidence = _llm_grade(
        question=str(config.get("question") or ""),
        target=target,
        predicted=predicted,
        template=OPEN_ENDED_GRADING_PROMPT,
        judge_model=str(config.get("judge_model") or DEFAULT_JUDGE_MODEL),
    )
    return _result(correct, f"str→llm fallback: {evidence}")


def bix_range_verifier(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    return _verify_via_llm(artifact, config, OPEN_ENDED_RANGE_GRADING_PROMPT)


def bix_llm_verifier(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    return _verify_via_llm(artifact, config, OPEN_ENDED_GRADING_PROMPT)
