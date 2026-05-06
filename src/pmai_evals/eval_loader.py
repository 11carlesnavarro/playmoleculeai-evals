"""Read an eval set off disk into validated pydantic models."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from ruamel.yaml import YAML

from pmai_evals.errors import AssertionConfigError, EvalSetLoadError
from pmai_evals.schemas import CaseSpec, EvalSet, EvalSetSpec

EVAL_SETS_DIR = Path("eval_sets")


def _load_checks_module(eval_set_id: str, checks_path: Path) -> ModuleType:
    """Import ``eval_sets/<id>/checks.py`` under a namespaced module name.

    Namespacing avoids collision when multiple eval sets ship a ``checks.py``.
    """
    mod_name = f"pmai_evals_checks__{eval_set_id.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(mod_name, checks_path)
    if spec is None or spec.loader is None:
        raise EvalSetLoadError(f"could not build import spec for {checks_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(mod_name, None)
        raise EvalSetLoadError(
            f"failed to import checks module {checks_path}: {exc}"
        ) from exc
    return module


def _load_yaml(path: Path) -> object:
    return YAML(typ="safe").load(path.read_text(encoding="utf-8"))


def _validate_assertions(case: CaseSpec, base: Path, checks_module: ModuleType | None) -> None:
    # Late import: assertions imports schemas which imports eval_loader.
    from pmai_evals.grading.assertions import PYTHON_CHECK_TYPE, VALID_ASSERTION_TYPES

    for assertion in case.assertions:
        if assertion.type not in VALID_ASSERTION_TYPES:
            raise AssertionConfigError(
                f"case '{case.id}': unknown assertion type '{assertion.type}'"
            )
        if assertion.type != PYTHON_CHECK_TYPE:
            continue
        func_name = getattr(assertion, "function", None)
        if not func_name:
            raise AssertionConfigError(
                f"case '{case.id}': python_check missing 'function'"
            )
        if checks_module is None:
            raise AssertionConfigError(
                f"case '{case.id}': python_check {func_name!r} but no checks.py in {base}"
            )
        if not callable(getattr(checks_module, func_name, None)):
            raise AssertionConfigError(
                f"case '{case.id}': python_check {func_name!r} not found in {base / 'checks.py'}"
            )


def _validate_fixtures(case: CaseSpec, base: Path) -> None:
    for fixture in (*case.preload.project.files, *case.preload.viewer.files):
        fpath = base / "fixtures" / fixture
        if not fpath.exists():
            raise EvalSetLoadError(
                f"case '{case.id}': missing preload fixture {fpath}"
            )


def load_eval_set(eval_set_id: str, *, root: Path | None = None) -> EvalSet:
    """Load ``eval_sets/<id>/{eval_set,cases}.yaml``.

    Validates assertion types and fixture existence eagerly so unknown
    types or missing files fail at load time rather than at run time.
    """
    base = (root or EVAL_SETS_DIR) / eval_set_id
    if not base.is_dir():
        raise EvalSetLoadError(f"eval set not found: {base}")

    spec_path = base / "eval_set.yaml"
    cases_path = base / "cases.yaml"
    for required in (spec_path, cases_path):
        if not required.exists():
            raise EvalSetLoadError(f"missing {required}")

    spec_data = _load_yaml(spec_path)
    cases_data = _load_yaml(cases_path)

    if not isinstance(spec_data, dict):
        raise EvalSetLoadError(f"{spec_path} must be a YAML mapping")
    if not isinstance(cases_data, dict) or "cases" not in cases_data:
        raise EvalSetLoadError(f"{cases_path} must contain a top-level 'cases' list")
    raw_cases = cases_data["cases"] or []
    if not isinstance(raw_cases, list):
        raise EvalSetLoadError("'cases' must be a list")

    spec = EvalSetSpec.model_validate(spec_data)
    cases = [CaseSpec.model_validate(item) for item in raw_cases]

    checks_path = base / "checks.py"
    checks_module = _load_checks_module(spec.id, checks_path) if checks_path.exists() else None

    for case in cases:
        _validate_assertions(case, base, checks_module)
        _validate_fixtures(case, base)

    return EvalSet(spec=spec, cases=cases, root=base, checks_module=checks_module)
