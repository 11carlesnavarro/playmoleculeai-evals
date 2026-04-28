"""Assertion dispatch for the eval grader.

The framework defines exactly one assertion type, ``python_check``: each
eval set ships its own ``checks.py`` with case-specific functions whose
names are referenced from ``cases.yaml``. Built-in assertions live in
the eval set, not here.
"""

from __future__ import annotations

import logging
from types import ModuleType
from typing import Any

from pmai_evals.errors import AssertionConfigError
from pmai_evals.runner.artifacts import RunArtifact
from pmai_evals.schemas import AssertionResult

logger = logging.getLogger(__name__)


PYTHON_CHECK_TYPE = "python_check"
VALID_ASSERTION_TYPES: frozenset[str] = frozenset({PYTHON_CHECK_TYPE})


def _run_python_check(
    artifact: RunArtifact,
    config: dict[str, Any],
    checks_module: ModuleType | None,
) -> AssertionResult:
    func_name = config.get("function")
    if not func_name:
        raise AssertionConfigError("python_check missing 'function'")
    if checks_module is None:
        raise AssertionConfigError(
            f"python_check {func_name!r}: eval set has no checks.py"
        )
    func = getattr(checks_module, func_name, None)
    if not callable(func):
        available = sorted(
            n for n in dir(checks_module)
            if callable(getattr(checks_module, n)) and not n.startswith("_")
        )
        raise AssertionConfigError(
            f"python_check: {func_name!r} not in checks.py; available: {available}"
        )
    merged = {**config.get("kwargs", {}), "function": func_name}
    try:
        result = func(artifact, merged)
    except Exception as exc:
        logger.exception("python_check %s crashed", func_name)
        return AssertionResult(
            assertion_type=PYTHON_CHECK_TYPE,
            passed=False,
            evidence=f"{func_name} raised {type(exc).__name__}: {exc}",
            config=config,
        )
    if not isinstance(result, AssertionResult):
        raise AssertionConfigError(
            f"python_check {func_name!r} must return AssertionResult, "
            f"got {type(result).__name__}"
        )
    return result


def run_assertions(
    artifact: RunArtifact,
    specs: list[dict[str, Any]],
    *,
    checks_module: ModuleType | None = None,
) -> list[AssertionResult]:
    """Apply each spec to ``artifact`` and collect results."""
    results: list[AssertionResult] = []
    for spec in specs:
        assertion_type = spec.get("type")
        if assertion_type != PYTHON_CHECK_TYPE:
            raise AssertionConfigError(
                f"unknown assertion type: {assertion_type!r}; "
                f"only {PYTHON_CHECK_TYPE!r} is supported"
            )
        results.append(_run_python_check(artifact, spec, checks_module))
    return results
