"""Tests for the bixbench verifiers (deterministic paths only, no network)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

from pmai_evals.errors import AssertionConfigError
from pmai_evals.eval_loader import load_eval_set


checks = cast(Any, load_eval_set("bixbench", root=Path("eval_sets")).checks_module)


@dataclass
class _StubArtifact:
    answer: str

    def final_answer(self) -> str:
        return self.answer


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure the LLM client is unconfigured for the LLM-fallback tests."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    checks._cached_client.cache_clear()


def test_extract_answer_picks_last_tag() -> None:
    art = _StubArtifact("scratch <answer>0.1</answer> rethink <answer>0.0002</answer>")
    assert checks._extract_answer(art) == "0.0002"


def test_extract_answer_missing() -> None:
    assert checks._extract_answer(_StubArtifact("no tag here")) is None


def test_clean_strips_non_alnum_and_lowercases() -> None:
    assert checks._clean(" Canonical Glycolysis! ") == "canonicalglycolysis"
    assert checks._clean("0.0002") == "00002"
    assert checks._clean("(1.50, 1.54)") == "150154"


def test_parse_grade_correct_passes() -> None:
    assert checks._parse_grade("<grade>correct</grade>") == "correct"


def test_parse_grade_incorrect_returns_word() -> None:
    assert checks._parse_grade("blah <grade> incorrect </grade>") == "incorrect"


def test_parse_grade_missing_returns_empty() -> None:
    assert checks._parse_grade("no tag here") == ""


def test_str_verifier_exact_alnum_match_passes() -> None:
    art = _StubArtifact("<answer>Canonical glycolysis</answer>")
    res = checks.bix_str_verifier(art, {"ideal": "canonical-glycolysis"})
    assert res.passed
    assert "exact match" in res.evidence


def test_str_verifier_partial_match_passes() -> None:
    art = _StubArtifact("<answer>Glycolysis</answer>")
    res = checks.bix_str_verifier(
        art, {"ideal": "Canonical glycolysis pathway", "question": "?"}
    )
    assert res.passed
    assert "partial match" in res.evidence


def test_str_verifier_missing_answer_fails() -> None:
    res = checks.bix_str_verifier(_StubArtifact("no tag"), {"ideal": "x"})
    assert not res.passed
    assert "no <answer>" in res.evidence


def test_str_verifier_requires_ideal() -> None:
    with pytest.raises(AssertionConfigError):
        checks.bix_str_verifier(_StubArtifact(""), {})


def test_range_verifier_missing_answer() -> None:
    res = checks.bix_range_verifier(
        _StubArtifact("no tag"), {"ideal": "(0.07,0.08)", "question": "?"}
    )
    assert not res.passed
    assert "no <answer>" in res.evidence


def test_llm_verifier_missing_answer() -> None:
    res = checks.bix_llm_verifier(
        _StubArtifact("no tag"), {"ideal": "x", "question": "?"}
    )
    assert not res.passed


@pytest.mark.parametrize(
    ("verifier", "config"),
    [
        ("bix_str_verifier", {"ideal": "0.0002", "question": "?"}),
        ("bix_range_verifier", {"ideal": "(0.07,0.08)", "question": "?"}),
        ("bix_llm_verifier", {"ideal": "x", "question": "?"}),
    ],
)
def test_short_circuits_without_api_key(verifier: str, config: dict[str, Any]) -> None:
    art = _StubArtifact("<answer>nowhere-near-the-target</answer>")
    res = getattr(checks, verifier)(art, config)
    assert not res.passed
    assert "ANTHROPIC_API_KEY" in res.evidence
