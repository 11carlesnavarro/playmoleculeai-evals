"""Run old eval_sets checks.py functions, unchanged, against a Harbor trial.

scripts/cases_to_tasks.py rewrites their `from pmai_evals.<old module> import` lines to this module.
"""

from dataclasses import dataclass, field
from pathlib import Path

from pmai_evals import trial

PYTHON_CHECK_TYPE = "python_check"


@dataclass
class AssertionResult:
    assertion_type: str
    score: float
    evidence: str = ""
    config: dict = field(default_factory=dict)


class RunArtifact:
    """What the old checks read, taken from the trial."""

    @property
    def project_files_dir(self) -> Path:
        return trial.WORK

    def final_answer(self) -> str:
        return trial.answer()


def check(module, function: str, **kwargs) -> float:
    """The score of one old check. As in the old grader, a crash scores 0."""
    try:
        result = getattr(module, function)(RunArtifact(), {**kwargs, "function": function})
    except Exception as exc:
        print(f"{function} raised {type(exc).__name__}: {exc}")
        return 0.0
    print(f"{function}: {result.score} {result.evidence}")  # lands in verifier/test-stdout.txt
    return result.score
