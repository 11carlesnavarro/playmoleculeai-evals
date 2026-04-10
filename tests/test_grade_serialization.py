"""Round-trip tests for the pydantic schemas in ``schemas.py``."""

from __future__ import annotations

from datetime import UTC, datetime

from pmai_evals.schemas import (
    AssertionResult,
    CaseGrade,
    CaseGradeSummary,
    CaseSummary,
    DimensionScore,
    PairwiseGrade,
    RubricGrade,
    RunConfig,
    RunRecord,
    RunSummary,
)


def test_assertion_result_roundtrip() -> None:
    a = AssertionResult(
        assertion_type="output_contains",
        passed=True,
        evidence="evidence",
        config={"value": "x"},
    )
    assert AssertionResult.model_validate_json(a.model_dump_json()) == a


def test_case_grade_roundtrip() -> None:
    grade = CaseGrade(
        case_id="case",
        model="m",
        seed=0,
        assertions=[
            AssertionResult(
                assertion_type="tool_called",
                passed=True,
                evidence="ok",
                config={"name": "pmview_load"},
            )
        ],
        rubric=RubricGrade(
            overall_score=4.0,
            passed=True,
            dimensions=[
                DimensionScore(
                    name="correctness",
                    score=4.0,
                    justification="ok",
                    evidence="cited",
                )
            ],
            evidence=["c"],
        ),
        summary=CaseGradeSummary(
            assertions_passed=1,
            assertions_total=1,
            rubric_passed=True,
        ),
    )
    j = grade.model_dump_json()
    reloaded = CaseGrade.model_validate_json(j)
    assert reloaded == grade


def test_run_record_roundtrip() -> None:
    cfg = RunConfig(
        eval_set_id="t",
        models=["m1"],
        seeds=1,
        max_cost_usd=1.0,
        headless=True,
        run_label="test",
        judge_model="claude-sonnet-4-6",
    )
    rec = RunRecord(
        run_id="r",
        eval_set="t",
        started_at=datetime.now(UTC),
        config=cfg,
    )
    assert RunRecord.model_validate_json(rec.model_dump_json()) == rec


def test_run_summary_roundtrip() -> None:
    now = datetime.now(UTC)
    summary = RunSummary(
        run_id="r",
        eval_set="t",
        started_at=now,
        finished_at=now,
        cases=[
            CaseSummary(
                case_id="c",
                model="m",
                seed=0,
                status="completed",
                cost_usd=0.01,
                artifact_dir="c/m/seed-0",
            )
        ],
        total_cost_usd=0.01,
        aborted_over_budget=False,
    )
    assert RunSummary.model_validate_json(summary.model_dump_json()) == summary


def test_pairwise_grade_roundtrip() -> None:
    pg = PairwiseGrade(winner="A", justification="A is better", evidence=["A: ..."])
    assert PairwiseGrade.model_validate_json(pg.model_dump_json()) == pg
