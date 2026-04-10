"""Top-level grade orchestrator: walks a run dir and writes ``grade.json``.

Pure function over disk artifacts. Re-runnable. Spec §4.4: only the
grade stage writes ``grade.json``; the runner never does.

Cells are graded concurrently because each judge call is an independent
network request and the API is the bottleneck. A semaphore caps in-flight
calls so we don't trip provider rate limits.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from pmai_evals._io import read_json
from pmai_evals.config import Settings
from pmai_evals.errors import EvalSetLoadError, JudgeError
from pmai_evals.eval_loader import load_eval_set
from pmai_evals.grading.assertions import run_assertions
from pmai_evals.grading.judge import (
    LLMJudge,
    Rubric,
    RubricDimension,
    default_rubric,
    load_rubric,
)
from pmai_evals.runner.artifacts import RunArtifact, RunArtifactWriter, iter_cell_paths
from pmai_evals.schemas import (
    CaseGrade,
    CaseGradeSummary,
    CaseSpec,
    EvalSet,
    RubricGrade,
)

logger = logging.getLogger(__name__)

# Cap concurrent judge calls. Each provider has its own rate limits; this
# is a conservative default that callers can override via env in future.
DEFAULT_GRADE_CONCURRENCY = 8


def _load_run_eval_set(run_dir: Path) -> EvalSet:
    record_path = run_dir / "run.json"
    if not record_path.exists():
        raise EvalSetLoadError(f"run.json missing under {run_dir}")
    record = read_json(record_path)
    return load_eval_set(record["eval_set"])


def _resolve_rubric(eval_set: EvalSet, override_path: Path | None) -> Rubric:
    if override_path is not None:
        return load_rubric(override_path)
    if eval_set.spec.rubric_path:
        candidate = eval_set.root / eval_set.spec.rubric_path
        if candidate.exists():
            return load_rubric(candidate)
    return default_rubric()


def _case_by_id(eval_set: EvalSet, case_id: str) -> CaseSpec | None:
    for case in eval_set.cases:
        if case.id == case_id:
            return case
    return None


async def _grade_one(
    *,
    cell,
    eval_set: EvalSet,
    rubric: Rubric,
    judge: LLMJudge,
    semaphore: asyncio.Semaphore,
    force: bool,
) -> bool:
    """Grade a single cell. Returns True if a ``grade.json`` was written."""

    artifact = RunArtifact(
        run_dir=cell.run_dir,
        case_id=cell.case_id,
        model=cell.model,
        seed=cell.seed,
    )
    if artifact.grade_path.exists() and not force:
        logger.debug("skipping already-graded cell %s", artifact.cell_dir)
        return False

    case = _case_by_id(eval_set, cell.case_id)
    if case is None:
        logger.warning("case '%s' not in eval set; skipping", cell.case_id)
        return False

    writer = RunArtifactWriter(
        run_dir=cell.run_dir,
        case_id=cell.case_id,
        model=cell.model,
        seed=cell.seed,
    )
    assertion_specs = [a.model_dump() for a in case.assertions]

    try:
        assertion_results = run_assertions(artifact, assertion_specs)
    except (KeyError, TypeError, ValueError) as exc:
        logger.exception("assertions crashed for %s", artifact.cell_dir)
        writer.write_grade(
            CaseGrade(
                case_id=cell.case_id,
                model=cell.model,
                seed=cell.seed,
                assertions=[],
                rubric=None,
                summary=CaseGradeSummary(
                    assertions_passed=0,
                    assertions_total=len(assertion_specs),
                    rubric_passed=None,
                ),
                judge_model=judge.model,
                judge_error=f"assertion_crash: {exc}",
            )
        )
        return True

    passed = sum(1 for r in assertion_results if r.passed)

    rubric_grade: RubricGrade | None = None
    judge_error: str | None = None
    if case.rubric.enabled:
        case_rubric = rubric
        if case.rubric.dimensions:
            case_rubric = Rubric(
                dimensions=[
                    RubricDimension(name=d.name, question=d.question, scale=d.scale)
                    for d in case.rubric.dimensions
                ],
                pass_threshold=rubric.pass_threshold,
            )
        async with semaphore:
            try:
                rubric_grade = await judge.grade_absolute(
                    artifact, case_rubric, case_prompt=case.prompt
                )
            except JudgeError as exc:
                judge_error = str(exc)
                logger.warning("judge failed for %s: %s", artifact.cell_dir, exc)

    writer.write_grade(
        CaseGrade(
            case_id=cell.case_id,
            model=cell.model,
            seed=cell.seed,
            assertions=assertion_results,
            rubric=rubric_grade,
            summary=CaseGradeSummary(
                assertions_passed=passed,
                assertions_total=len(assertion_results),
                rubric_passed=(rubric_grade.passed if rubric_grade else None),
            ),
            judge_model=judge.model,
            judge_error=judge_error,
        )
    )
    logger.info(
        "graded %s/%s/seed-%d: %d/%d assertions passed",
        cell.case_id,
        cell.model,
        cell.seed,
        passed,
        len(assertion_results),
    )
    return True


async def grade_run(
    run_id: str,
    settings: Settings,
    *,
    judge_model: str | None = None,
    rubric_override: Path | None = None,
    force: bool = False,
    concurrency: int = DEFAULT_GRADE_CONCURRENCY,
) -> int:
    """Grade a previously executed run. Returns the count of cells written."""

    run_dir = settings.results_dir / run_id
    if not run_dir.is_dir():
        raise EvalSetLoadError(f"run not found: {run_dir}")

    eval_set = _load_run_eval_set(run_dir)
    rubric = _resolve_rubric(eval_set, rubric_override)
    judge = LLMJudge(judge_model or settings.pmai_evals_judge_model, settings)
    semaphore = asyncio.Semaphore(max(1, concurrency))

    cells = list(iter_cell_paths(run_dir))
    tasks = [
        _grade_one(
            cell=cell,
            eval_set=eval_set,
            rubric=rubric,
            judge=judge,
            semaphore=semaphore,
            force=force,
        )
        for cell in cells
    ]
    results = await asyncio.gather(*tasks)
    return sum(1 for written in results if written)


def grade_run_sync(
    run_id: str,
    settings: Settings,
    *,
    judge_model: str | None = None,
    rubric_override: Path | None = None,
    force: bool = False,
) -> int:
    """CLI-friendly synchronous wrapper around :func:`grade_run`."""
    return asyncio.run(
        grade_run(
            run_id,
            settings,
            judge_model=judge_model,
            rubric_override=rubric_override,
            force=force,
        )
    )
