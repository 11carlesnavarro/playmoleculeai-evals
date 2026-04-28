"""Tests for the python_check dispatcher in pmai_evals.grading.assertions."""

from __future__ import annotations

import types
from typing import Any, Callable

import pytest

from pmai_evals.errors import AssertionConfigError
from pmai_evals.grading.assertions import run_assertions
from pmai_evals.runner.artifacts import RunArtifact
from pmai_evals.schemas import AssertionResult


def _module_with(*funcs: Callable[..., Any]) -> types.ModuleType:
    mod = types.ModuleType("test_checks")
    for fn in funcs:
        setattr(mod, fn.__name__, fn)
    return mod


def _passing(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    return AssertionResult(
        assertion_type="python_check",
        passed=True,
        evidence=f"called with {config['function']}",
        config=config,
    )


def _raising(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    raise RuntimeError("boom")


def _wrong_return(artifact: RunArtifact, config: dict[str, Any]) -> str:
    return "not an AssertionResult"


def test_dispatcher_runs_python_check(artifact_with_trace: Any) -> None:
    art = artifact_with_trace()
    mod = _module_with(_passing)
    [result] = run_assertions(
        art,
        [{"type": "python_check", "function": "_passing"}],
        checks_module=mod,
    )
    assert result.passed
    assert "_passing" in result.evidence


def test_unknown_assertion_type_raises(artifact_with_trace: Any) -> None:
    art = artifact_with_trace()
    with pytest.raises(AssertionConfigError, match="unknown assertion type"):
        run_assertions(art, [{"type": "tool_called"}])


def test_missing_type_raises(artifact_with_trace: Any) -> None:
    art = artifact_with_trace()
    with pytest.raises(AssertionConfigError, match="unknown assertion type"):
        run_assertions(art, [{"value": "x"}])  # type: ignore[list-item]


def test_python_check_missing_function_name(artifact_with_trace: Any) -> None:
    art = artifact_with_trace()
    mod = _module_with(_passing)
    with pytest.raises(AssertionConfigError, match="missing 'function'"):
        run_assertions(
            art, [{"type": "python_check"}], checks_module=mod
        )


def test_python_check_no_module(artifact_with_trace: Any) -> None:
    art = artifact_with_trace()
    with pytest.raises(AssertionConfigError, match="no checks.py"):
        run_assertions(
            art,
            [{"type": "python_check", "function": "_passing"}],
            checks_module=None,
        )


def test_python_check_unknown_function(artifact_with_trace: Any) -> None:
    art = artifact_with_trace()
    mod = _module_with(_passing)
    with pytest.raises(AssertionConfigError, match="not in checks.py"):
        run_assertions(
            art,
            [{"type": "python_check", "function": "ghost"}],
            checks_module=mod,
        )


def test_python_check_raising_is_a_failure(artifact_with_trace: Any) -> None:
    art = artifact_with_trace()
    mod = _module_with(_raising)
    [result] = run_assertions(
        art,
        [{"type": "python_check", "function": "_raising"}],
        checks_module=mod,
    )
    assert not result.passed
    assert "RuntimeError" in result.evidence
    assert "boom" in result.evidence


def test_python_check_wrong_return_type_raises(artifact_with_trace: Any) -> None:
    art = artifact_with_trace()
    mod = _module_with(_wrong_return)
    with pytest.raises(AssertionConfigError, match="must return AssertionResult"):
        run_assertions(
            art,
            [{"type": "python_check", "function": "_wrong_return"}],
            checks_module=mod,
        )
