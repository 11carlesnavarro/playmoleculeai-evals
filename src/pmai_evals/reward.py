"""pytest plugin: one score per test, reward = mean. Use: pytest -p pmai_evals.reward"""

import json
import os
from pathlib import Path

OUT = Path(os.environ.get("REWARD_JSON", "/logs/verifier/reward.json"))
_scores: dict[str, float] = {}
_partial: dict[str, float] = {}
_infra: list[str] = []


class InfraError(Exception):
    """The eval setup failed, not the agent (e.g. the viewer sidecar). The trial gets no reward.json,
    so Harbor shows an error, not a 0."""


def partial(value: float) -> float:
    """Give the running test a score from 0 to 1 instead of pass or fail."""
    name = os.environ["PYTEST_CURRENT_TEST"].split("::")[-1].split(" ")[0]
    _partial[name] = float(value)
    return float(value)


def pytest_runtest_logreport(report):
    name = report.nodeid.split("::")[-1]
    if report.when == "call" or report.failed:  # a setup error counts as 0
        _scores[name] = _partial.get(name, 1.0) if report.passed else 0.0


def pytest_runtest_makereport(item, call):  # returns None: pytest still makes the report
    if call.excinfo and call.excinfo.errisinstance(InfraError):
        _infra.append(f"{item.name}: {call.excinfo.value}")


def pytest_sessionfinish(session):
    if _infra:
        OUT.unlink(missing_ok=True)
        print("\ninfra error, no reward:", *_infra, sep="\n  ")
        return
    reward = sum(_scores.values()) / len(_scores) if _scores else 0.0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"reward": reward, **_scores}))
