"""Grade-the-grader pass.

After a run is graded, this pass surveys the assertion and rubric outputs
and flags entries that are *not discriminating*: ones that pass for every
model (false confidence) or fail for every model (likely buggy or
mis-specified).

Spec §7.2 — borrowed directly from the ``skill-creator`` philosophy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pmai_evals._io import write_json
from pmai_evals.errors import HarnessError
from pmai_evals.runner.artifacts import iter_grade_files

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CritiqueFinding:
    target: str
    reason: str
    suggestion: str

    def to_dict(self) -> dict[str, str]:
        return {
            "assertion_or_dimension": self.target,
            "reason": self.reason,
            "suggestion": self.suggestion,
        }


def critique_run(run_dir: Path) -> dict[str, Any]:
    """Read all ``grade.json`` files under ``run_dir`` and emit a critique."""

    if not run_dir.is_dir():
        raise HarnessError(f"run dir not found: {run_dir}")

    # Index assertion outcomes by (case_id, assertion_signature) → list[(model, passed)]
    assertion_index: dict[tuple[str, str], list[tuple[str, bool]]] = {}
    rubric_index: dict[tuple[str, str], list[tuple[str, float]]] = {}

    for _cell, grade in iter_grade_files(run_dir):
        case_id = grade.get("case_id", "?")
        model = grade.get("model", "?")

        for assertion in grade.get("assertions") or []:
            sig = assertion.get("assertion_type", "?")
            cfg = assertion.get("config") or {}
            extra = cfg.get("name") or cfg.get("value") or cfg.get("identifier") or ""
            label = f"{sig}({extra})" if extra else sig
            assertion_index.setdefault((case_id, label), []).append(
                (model, bool(assertion.get("passed")))
            )

        rubric = grade.get("rubric") or {}
        for dim in rubric.get("dimensions") or []:
            label = dim.get("name", "?")
            rubric_index.setdefault((case_id, label), []).append(
                (model, float(dim.get("score") or 0))
            )

    findings: list[CritiqueFinding] = []

    for (case_id, label), outcomes in assertion_index.items():
        models = {m for m, _ in outcomes}
        if len(models) < 2:
            continue
        passes = [p for _, p in outcomes]
        if all(passes):
            findings.append(
                CritiqueFinding(
                    target=f"{case_id}::{label}",
                    reason=f"passes for all {len(models)} models",
                    suggestion="tighten the threshold or replace with a more specific check",
                )
            )
        elif not any(passes):
            findings.append(
                CritiqueFinding(
                    target=f"{case_id}::{label}",
                    reason=f"fails for all {len(models)} models",
                    suggestion="re-check the assertion logic and the prompt — likely a mismatch",
                )
            )

    for (case_id, label), scores in rubric_index.items():
        if len({m for m, _ in scores}) < 2:
            continue
        values = [s for _, s in scores]
        if all(v >= 4.5 for v in values):
            findings.append(
                CritiqueFinding(
                    target=f"{case_id}::rubric::{label}",
                    reason="all models scored ≥4.5",
                    suggestion="raise the rubric ceiling or add a stricter dimension",
                )
            )
        elif all(v <= 1.5 for v in values):
            findings.append(
                CritiqueFinding(
                    target=f"{case_id}::rubric::{label}",
                    reason="all models scored ≤1.5",
                    suggestion="reword the dimension — it may be unanswerable from the artifacts",
                )
            )

    summary = (
        f"{len(findings)} non-discriminating finding(s) over "
        f"{len(assertion_index)} assertion configurations and "
        f"{len(rubric_index)} rubric dimensions."
    )
    payload = {
        "non_discriminating": [f.to_dict() for f in findings],
        "summary": summary,
    }
    out_path = run_dir / "critique.json"
    write_json(out_path, payload)
    logger.info("wrote %s", out_path)
    return payload
