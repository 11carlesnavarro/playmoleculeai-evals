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

    Namespacing avoids collision when multiple eval sets each ship a
    ``checks.py`` — they'd otherwise all import as ``checks``.
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


def load_eval_set(eval_set_id: str, *, root: Path | None = None) -> EvalSet:
    """Load ``eval_sets/<id>/{eval_set,cases}.yaml``.

    Validates assertion types against the registry so unknown types fail
    at load time, not at run time.
    """

    base = (root or EVAL_SETS_DIR) / eval_set_id
    if not base.is_dir():
        raise EvalSetLoadError(f"eval set not found: {base}")

    spec_path = base / "eval_set.yaml"
    cases_path = base / "cases.yaml"
    if not spec_path.exists():
        raise EvalSetLoadError(f"missing {spec_path}")
    if not cases_path.exists():
        raise EvalSetLoadError(f"missing {cases_path}")

    yaml = YAML(typ="safe")
    spec_data = yaml.load(spec_path.read_text(encoding="utf-8"))
    cases_data = yaml.load(cases_path.read_text(encoding="utf-8"))

    if not isinstance(spec_data, dict):
        raise EvalSetLoadError(f"{spec_path} must be a YAML mapping")
    if not isinstance(cases_data, dict) or "cases" not in cases_data:
        raise EvalSetLoadError(f"{cases_path} must contain a top-level 'cases' list")

    spec = EvalSetSpec.model_validate(spec_data)
    raw_cases = cases_data["cases"] or []
    if not isinstance(raw_cases, list):
        raise EvalSetLoadError("'cases' must be a list")

    cases = [CaseSpec.model_validate(item) for item in raw_cases]

    checks_path = base / "checks.py"
    checks_module = _load_checks_module(spec.id, checks_path) if checks_path.exists() else None

    # Validate assertion types and fixture existence eagerly. Late import
    # breaks the assertions→schemas→eval_loader cycle.
    from pmai_evals.grading.assertions import (  # noqa: PLC0415
        PYTHON_CHECK_TYPE,
        VALID_ASSERTION_TYPES,
    )

    for case in cases:
        for assertion in case.assertions:
            if assertion.type not in VALID_ASSERTION_TYPES:
                raise AssertionConfigError(
                    f"case '{case.id}': unknown assertion type '{assertion.type}'"
                )
            if assertion.type == PYTHON_CHECK_TYPE:
                func_name = getattr(assertion, "function", None)
                if not func_name:
                    raise AssertionConfigError(
                        f"case '{case.id}': python_check missing 'function'"
                    )
                if checks_module is None:
                    raise AssertionConfigError(
                        f"case '{case.id}': python_check {func_name!r} but "
                        f"no checks.py in {base}"
                    )
                if not callable(getattr(checks_module, func_name, None)):
                    raise AssertionConfigError(
                        f"case '{case.id}': python_check {func_name!r} not "
                        f"found in {checks_path}"
                    )
        for fixture in (*case.preload.project.files, *case.preload.viewer.files):
            fpath = base / "fixtures" / fixture
            if not fpath.exists():
                raise EvalSetLoadError(
                    f"case '{case.id}': missing preload fixture {fpath}"
                )

    return EvalSet(spec=spec, cases=cases, root=base, checks_module=checks_module)
