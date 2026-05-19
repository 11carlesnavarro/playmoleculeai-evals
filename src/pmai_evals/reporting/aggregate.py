"""Aggregate per-cell ``grade.json`` files into a benchmark summary."""

from __future__ import annotations

import logging
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pmai_evals._io import read_json_or, write_json
from pmai_evals.runner.artifacts import iter_grade_files

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CellAccumulator:
    """Per-cell stats. Used as both per-seed row and pooled model row."""

    cases_total: int = 0
    cases_completed: int = 0
    cases_failed: int = 0
    cases_timed_out: int = 0
    cases_skipped: int = 0
    assertions_score: float = 0.0
    assertions_total: int = 0
    rubric_pass: int = 0
    rubric_total: int = 0
    rubric_scores: list[float] = field(default_factory=list)
    cost_usd: float = 0.0

    @property
    def assertion_score_mean(self) -> float:
        return self.assertions_score / self.assertions_total if self.assertions_total else 0.0

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
        return {
            "cases_total": self.cases_total,
            "cases_completed": self.cases_completed,
            "cases_failed": self.cases_failed,
            "cases_timed_out": self.cases_timed_out,
            "cases_skipped": self.cases_skipped,
            "assertions_score": round(self.assertions_score, 4),
            "assertions_total": self.assertions_total,
            "assertion_score_mean": round(self.assertion_score_mean, 4),
            "rubric_pass": self.rubric_pass,
            "rubric_total": self.rubric_total,
            "rubric_pass_rate": round(self.rubric_pass_rate, 4),
            "rubric_mean": _round(self.rubric_mean, 4),
            "rubric_stderr": _round(self.rubric_stderr, 4),
            "cost_usd": round(self.cost_usd, 6),
        }


def _round(value: float | None, ndigits: int) -> float | None:
    return None if value is None else round(value, ndigits)


_STATUS_FIELD = {
    "completed": "cases_completed",
    "failed": "cases_failed",
    "timed_out": "cases_timed_out",
    "skipped_over_budget": "cases_skipped",
}


def _seed_summary(seeds: list[dict[str, Any]], key: str) -> dict[str, float | None]:
    values = [s[key] for s in seeds if s.get(key) is not None]
    if not values:
        return {"mean": None, "std": None}
    mean = sum(values) / len(values)
    std = statistics.stdev(values) if len(values) >= 2 else None
    return {"mean": round(mean, 4), "std": round(std, 4) if std is not None else None}


def aggregate_run(run_dir: Path) -> dict[str, Any]:
    """Build the benchmark summary dict and write ``benchmark.json``."""
    if not run_dir.is_dir():
        raise FileNotFoundError(f"run dir not found: {run_dir}")

    summary = read_json_or(run_dir / "summary.json", {})
    pooled: dict[str, CellAccumulator] = defaultdict(CellAccumulator)
    by_seed: dict[tuple[str, int], CellAccumulator] = defaultdict(CellAccumulator)
    per_case: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"models": {}, "rubric": {}}
    )

    for case_summary in summary.get("cases", []):
        model = case_summary["model"]
        seed = int(case_summary.get("seed", 0))
        cost = float(case_summary.get("cost_usd") or 0)
        field_name = _STATUS_FIELD.get(case_summary.get("status"))
        for acc in (pooled[model], by_seed[(model, seed)]):
            acc.cases_total += 1
            acc.cost_usd += cost
            if field_name:
                setattr(acc, field_name, getattr(acc, field_name) + 1)

    for _, grade in iter_grade_files(run_dir):
        model = grade.get("model", "?")
        seed = int(grade.get("seed", 0))
        case_id = grade.get("case_id", "?")
        s = grade.get("summary") or {}
        ascore = float(s.get("assertions_score") or 0)
        at = int(s.get("assertions_total") or 0)
        rubric = grade.get("rubric") or None
        for acc in (pooled[model], by_seed[(model, seed)]):
            acc.assertions_score += ascore
            acc.assertions_total += at
            if rubric:
                acc.rubric_total += 1
                if rubric.get("passed"):
                    acc.rubric_pass += 1
                score = rubric.get("overall_score")
                if isinstance(score, int | float):
                    acc.rubric_scores.append(float(score))
        if rubric and isinstance(rubric.get("overall_score"), int | float):
            per_case[case_id]["rubric"][model] = float(rubric["overall_score"])
        per_case[case_id]["models"][model] = {
            "assertions_score": round(ascore, 4),
            "assertions_total": at,
            "rubric_passed": s.get("rubric_passed"),
        }

    seeds_by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (model, seed), acc in sorted(by_seed.items()):
        seeds_by_model[model].append({"seed": seed, **acc.to_dict()})

    models_out: list[dict[str, Any]] = []
    for model, acc in pooled.items():
        seeds = seeds_by_model.get(model, [])
        as_summary = _seed_summary(seeds, "assertion_score_mean")
        rp_summary = _seed_summary(seeds, "rubric_pass_rate")
        rm_summary = _seed_summary(seeds, "rubric_mean")
        models_out.append({
            "model": model,
            **acc.to_dict(),
            "n_seeds": len(seeds),
            "seeds": seeds,
            "assertion_score_mean_seed_mean": as_summary["mean"],
            "assertion_score_mean_seed_std": as_summary["std"],
            "rubric_pass_rate_mean": rp_summary["mean"],
            "rubric_pass_rate_std": rp_summary["std"],
            "rubric_mean_seed_mean": rm_summary["mean"],
            "rubric_mean_seed_std": rm_summary["std"],
        })

    benchmark = {
        "run_id": summary.get("run_id"),
        "eval_set": summary.get("eval_set"),
        "total_cost_usd": summary.get("total_cost_usd"),
        "aborted_over_budget": summary.get("aborted_over_budget"),
        "models": models_out,
        "cases": dict(per_case),
    }
    out = run_dir / "benchmark.json"
    write_json(out, benchmark)
    logger.info("wrote %s", out)
    return benchmark
