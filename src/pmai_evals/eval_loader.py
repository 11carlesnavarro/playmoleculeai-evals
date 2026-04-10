"""Read an eval set off disk into validated pydantic models."""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

from pmai_evals.errors import AssertionConfigError, EvalSetLoadError
from pmai_evals.schemas import CaseSpec, EvalSet, EvalSetSpec

EVAL_SETS_DIR = Path("eval_sets")


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

    # Validate assertion types and fixture existence eagerly.
    from pmai_evals.grading.assertions import ASSERTION_REGISTRY  # late: avoid cycles

    for case in cases:
        for assertion in case.assertions:
            if assertion.type not in ASSERTION_REGISTRY:
                raise AssertionConfigError(
                    f"case '{case.id}': unknown assertion type '{assertion.type}'"
                )
        for fixture in case.fixtures:
            fpath = base / "fixtures" / fixture
            if not fpath.exists():
                raise EvalSetLoadError(
                    f"case '{case.id}': missing fixture {fpath}"
                )

    return EvalSet(spec=spec, cases=cases, root=base)
