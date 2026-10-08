"""Run old eval_sets checks.py functions, unchanged, against a Harbor trial.

scripts/cases_to_tasks.py rewrites their `from pmai_evals.<old module> import` lines to this module.
"""

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from pmai_evals import trial
from pmai_evals.reward import InfraError

PYTHON_CHECK_TYPE = "python_check"


class AssertionConfigError(Exception):
    """An old check found a bad value."""


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

    # The viewer, through the agent's own API (trial.py). Old field names: docs/implementation-plan.md 5.7.

    @cached_property
    def _systems(self) -> dict:
        """The structures (no volumes), the newest first: the agent's own copy before a preloaded one.
        A system with no name gets ""."""
        systems = reversed(trial.viewer_state()["systems"].items())
        return {u: {**s, "name": s.get("name") or ""} for u, s in systems if s.get("type") == "structure"}

    def viewer_state(self) -> list[dict]:
        return [
            {"moleculeID": uuid, "name": s["name"], "representations": [
                {"type": r.get("style"), "selection": r.get("sel"), "color_value": _hex(r.get("color")),
                 "visibility": r.get("visibility", True) and s.get("visible", True)}
                for r in s.get("representations") or []
            ]}
            for uuid, s in self._systems.items()
        ]

    def viewer_selection(self) -> dict:  # {moleculeID: atom selection}
        return trial.viewer_selection()

    def system_files(self) -> list[tuple[str, None]]:
        """The names that load_system takes: the old export file names without the extension."""
        return [(Path(s["name"]).stem, None) for s in self._systems.values()]

    def load_system(self, name: str):
        """The structure in the viewer after the turn, as a moleculekit Molecule. KeyError if not there."""
        for uuid, s in self._systems.items():
            if Path(s["name"]).stem.lower() == name.lower():
                from moleculekit.molecule import Molecule  # in the grader venv

                return Molecule(str(trial.viewer_system(uuid)))
        raise KeyError(f"system {name!r} not in the viewer; there: {[n for n, _ in self.system_files()]}")


def _hex(color) -> str | None:
    """The checks read "#rrggbb" themselves (PMView stores "blue" as "#0000ff"). A scheme
    ("element-symbol") was None in the old state."""
    return color if isinstance(color, str) and color.startswith("#") else None


def check(module, function: str, **kwargs) -> float:
    """The score of one old check. As in the old grader, a crash scores 0."""
    try:
        result = getattr(module, function)(RunArtifact(), {**kwargs, "function": function})
    except InfraError:
        raise  # the viewer failed, not the agent: no reward (reward.py)
    except Exception as exc:
        print(f"{function} raised {type(exc).__name__}: {exc}")
        return 0.0
    print(f"{function}: {result.score} {result.evidence}")  # lands in verifier/test-stdout.txt
    return result.score
