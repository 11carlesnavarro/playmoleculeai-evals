"""Aggregate per-cell ``grade.json`` files into a benchmark summary."""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pmai_evals._io import read_json_or, write_json
from pmai_evals.runner.artifacts import iter_grade_files

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ModelStats:
    model: str
    cases_total: int = 0
    cases_completed: int = 0
    cases_failed: int = 0
    cases_timed_out: int = 0
    cases_skipped: int = 0
    assertions_passed: int = 0
    assertions_total: int = 0
    rubric_pass: int = 0
    rubric_total: int = 0
    rubric_scores: list[float] = field(default_factory=list)
    cost_usd: float = 0.0

    @property
    def assertion_pass_rate(self) -> float:
        return self.assertions_passed / self.assertions_total if self.assertions_total else 0.0

    @property
    def rubric_pass_rate(self) -> float:
        return self.rubric_pass / self.rubric_total if self.rubric_total else 0.0

    @property
    def rubric_mean(self) -> float | None:
        return sum(self.rubric_scores) / len(self.rubric_scores) if self.rubric_scores else None

    @property
    def rubric_stderr(self) -> float | None:
        if len(self.rubric_scores) < 2:
            return None
        mean = self.rubric_mean or 0.0
        variance = sum((s - mean) ** 2 for s in self.rubric_scores) / (len(self.rubric_scores) - 1)
        return math.sqrt(variance / len(self.rubric_scores))

    def to_dict(self) -> dict[str, Any]:
        def _round(value: float | None, ndigits: int) -> float | None:
            return None if value is None else round(value, ndigits)

        return {
            "model": self.model,
            "cases_total": self.cases_total,
            "cases_completed": self.cases_completed,
            "cases_failed": self.cases_failed,
            "cases_timed_out": self.cases_timed_out,
            "cases_skipped": self.cases_skipped,
            "assertions_passed": self.assertions_passed,
            "assertions_total": self.assertions_total,
            "assertion_pass_rate": round(self.assertion_pass_rate, 4),
            "rubric_pass": self.rubric_pass,
            "rubric_total": self.rubric_total,
            "rubric_pass_rate": round(self.rubric_pass_rate, 4),
            "rubric_mean": _round(self.rubric_mean, 4),
            "rubric_stderr": _round(self.rubric_stderr, 4),
            "cost_usd": round(self.cost_usd, 6),
        }


_STATUS_FIELD = {
    "completed": "cases_completed",
    "failed": "cases_failed",
    "timed_out": "cases_timed_out",
    "skipped_over_budget": "cases_skipped",
}


def aggregate_run(run_dir: Path) -> dict[str, Any]:
    """Build the benchmark summary dict and write ``benchmark.json``."""
    if not run_dir.is_dir():
        raise FileNotFoundError(f"run dir not found: {run_dir}")

    summary = read_json_or(run_dir / "summary.json", {})
    by_model: dict[str, ModelStats] = {}
    per_case: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"models": {}, "rubric": {}}
    )

    def _stats(model: str) -> ModelStats:
        return by_model.setdefault(model, ModelStats(model=model))

    for case_summary in summary.get("cases", []):
        stats = _stats(case_summary["model"])
        stats.cases_total += 1
        stats.cost_usd += float(case_summary.get("cost_usd") or 0)
        field_name = _STATUS_FIELD.get(case_summary.get("status"))
        if field_name:
            setattr(stats, field_name, getattr(stats, field_name) + 1)

    for _cell, grade in iter_grade_files(run_dir):
        model = grade.get("model", "?")
        case_id = grade.get("case_id", "?")
        stats = _stats(model)
        s = grade.get("summary") or {}
        stats.assertions_passed += int(s.get("assertions_passed") or 0)
        stats.assertions_total += int(s.get("assertions_total") or 0)
        rubric = grade.get("rubric") or None
        if rubric:
            stats.rubric_total += 1
            if rubric.get("passed"):
                stats.rubric_pass += 1
            score = rubric.get("overall_score")
            if isinstance(score, int | float):
                stats.rubric_scores.append(float(score))
                per_case[case_id]["rubric"][model] = float(score)
        per_case[case_id]["models"][model] = {
            "assertions_passed": int(s.get("assertions_passed") or 0),
            "assertions_total": int(s.get("assertions_total") or 0),
            "rubric_passed": s.get("rubric_passed"),
        }

    benchmark = {
        "run_id": summary.get("run_id"),
        "eval_set": summary.get("eval_set"),
        "total_cost_usd": summary.get("total_cost_usd"),
        "aborted_over_budget": summary.get("aborted_over_budget"),
        "models": [stats.to_dict() for stats in by_model.values()],
        "cases": dict(per_case),
    }
    out = run_dir / "benchmark.json"
    write_json(out, benchmark)
    logger.info("wrote %s", out)
    return benchmark
