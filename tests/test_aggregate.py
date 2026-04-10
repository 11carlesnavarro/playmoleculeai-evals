"""Tests for benchmark aggregation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pmai_evals.reporting.aggregate import aggregate_run
from pmai_evals.reporting.render import render_html, render_json, render_markdown


def _seed_run(run_dir: Path) -> None:
    summary = {
        "run_id": "test-run",
        "eval_set": "test-set",
        "started_at": datetime.now(UTC).isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "cases": [
            {
                "case_id": "c1",
                "model": "model-a",
                "seed": 0,
                "status": "completed",
                "cost_usd": 0.01,
                "artifact_dir": "c1/model-a/seed-0",
            },
            {
                "case_id": "c1",
                "model": "model-b",
                "seed": 0,
                "status": "completed",
                "cost_usd": 0.02,
                "artifact_dir": "c1/model-b/seed-0",
            },
        ],
        "total_cost_usd": 0.03,
        "aborted_over_budget": False,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    for model, passed in (("model-a", True), ("model-b", False)):
        cell = run_dir / "c1" / model / "seed-0"
        cell.mkdir(parents=True)
        grade = {
            "case_id": "c1",
            "model": model,
            "seed": 0,
            "assertions": [
                {
                    "assertion_type": "tool_called",
                    "passed": passed,
                    "evidence": "...",
                    "config": {"name": "pmview_load"},
                }
            ],
            "rubric": {
                "overall_score": 4.5 if passed else 2.5,
                "passed": passed,
                "dimensions": [
                    {
                        "name": "correctness",
                        "score": 5 if passed else 2,
                        "justification": "...",
                        "evidence": "...",
                    }
                ],
                "evidence": [],
            },
            "summary": {
                "assertions_passed": 1 if passed else 0,
                "assertions_total": 1,
                "rubric_passed": passed,
            },
            "judge_model": "claude-sonnet-4-6",
            "judge_error": None,
        }
        (cell / "grade.json").write_text(json.dumps(grade), encoding="utf-8")


def test_aggregate_and_render(tmp_path: Path) -> None:
    run_dir = tmp_path / "test-run"
    run_dir.mkdir()
    _seed_run(run_dir)

    benchmark = aggregate_run(run_dir)
    models = {m["model"]: m for m in benchmark["models"]}
    assert models["model-a"]["assertion_pass_rate"] == 1.0
    assert models["model-b"]["assertion_pass_rate"] == 0.0
    assert models["model-a"]["rubric_pass"] == 1
    assert models["model-b"]["rubric_pass"] == 0

    md = render_markdown(benchmark)
    assert "model-a" in md
    assert "model-b" in md

    html = render_html(benchmark)
    assert "<table" in html
    assert "model-a" in html

    js = render_json(benchmark)
    assert json.loads(js) == benchmark
