"""Grade-the-grader pass.

Surveys the assertion and rubric outputs of a graded run and flags
entries that are *not discriminating*: ones that pass for every model
(false confidence) or fail for every model (likely buggy).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pmai_evals._io import write_json
from pmai_evals.errors import HarnessError
from pmai_evals.runner.artifacts import iter_grade_files

logger = logging.getLogger(__name__)


def _assertion_label(assertion: dict[str, Any]) -> str:
    sig = assertion.get("assertion_type", "?")
    cfg = assertion.get("config") or {}
    extra = cfg.get("name") or cfg.get("value") or cfg.get("identifier") or ""
    return f"{sig}({extra})" if extra else sig


def critique_run(run_dir: Path) -> dict[str, Any]:
    """Read all ``grade.json`` files under ``run_dir`` and emit a critique."""
    if not run_dir.is_dir():
        raise HarnessError(f"run dir not found: {run_dir}")

    assertion_index: dict[tuple[str, str], list[tuple[str, bool]]] = {}
    rubric_index: dict[tuple[str, str], list[tuple[str, float]]] = {}

    for _cell, grade in iter_grade_files(run_dir):
        case_id = grade.get("case_id", "?")
        model = grade.get("model", "?")

        for assertion in grade.get("assertions") or []:
            key = (case_id, _assertion_label(assertion))
            assertion_index.setdefault(key, []).append(
                (model, bool(assertion.get("passed")))
            )

        rubric = grade.get("rubric") or {}
        for dim in rubric.get("dimensions") or []:
            key = (case_id, dim.get("name", "?"))
            rubric_index.setdefault(key, []).append(
                (model, float(dim.get("score") or 0))
            )

    findings: list[dict[str, str]] = []

    for (case_id, label), outcomes in assertion_index.items():
        models = {m for m, _ in outcomes}
        if len(models) < 2:
            continue
        passes = [p for _, p in outcomes]
        target = f"{case_id}::{label}"
        if all(passes):
            findings.append({
                "assertion_or_dimension": target,
                "reason": f"passes for all {len(models)} models",
                "suggestion": "tighten the threshold or replace with a more specific check",
            })
        elif not any(passes):
            findings.append({
                "assertion_or_dimension": target,
                "reason": f"fails for all {len(models)} models",
                "suggestion": "re-check the assertion logic and the prompt — likely a mismatch",
            })

    for (case_id, label), scores in rubric_index.items():
        if len({m for m, _ in scores}) < 2:
            continue
        values = [s for _, s in scores]
        target = f"{case_id}::rubric::{label}"
        if all(v >= 4.5 for v in values):
            findings.append({
                "assertion_or_dimension": target,
                "reason": "all models scored ≥4.5",
                "suggestion": "raise the rubric ceiling or add a stricter dimension",
            })
        elif all(v <= 1.5 for v in values):
            findings.append({
                "assertion_or_dimension": target,
                "reason": "all models scored ≤1.5",
                "suggestion": "reword the dimension — it may be unanswerable from the artifacts",
            })

    payload = {
        "non_discriminating": findings,
        "summary": (
            f"{len(findings)} non-discriminating finding(s) over "
            f"{len(assertion_index)} assertion configurations and "
            f"{len(rubric_index)} rubric dimensions."
        ),
    }
    out_path = run_dir / "critique.json"
    write_json(out_path, payload)
    logger.info("wrote %s", out_path)
    return payload
