"""Drive the (case × model × seed) matrix end-to-end.

Spec §4.7. Per-case flow lives in :func:`_run_one`. Per-case exceptions are
caught at the isolation barrier and recorded as ``status: failed`` — they
do not poison the run.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from pmai_evals._io import write_json
from pmai_evals.config import Settings
from pmai_evals.errors import (
    BrowserError,
    BudgetExceededError,
    ChatTimeoutError,
    HarnessError,
    PMAIEvalsError,
    TraceNotFoundError,
)
from pmai_evals.pricing import cost_for_usage
from pmai_evals.runner.artifacts import RunArtifactWriter
from pmai_evals.runner.budget import Budget
from pmai_evals.runner.manifest import MatrixEntry, build_manifest, write_manifest
from pmai_evals.schemas import (
    CaseStatus,
    CaseSummary,
    EvalSet,
    RunConfig,
    RunRecord,
    RunSummary,
)
from pmai_evals.trace import load_trace

logger = logging.getLogger(__name__)


# --- run id helpers --------------------------------------------------------

def make_run_id(eval_set_id: str, label: str, *, now: datetime | None = None) -> str:
    moment = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    safe_label = label.replace(" ", "-").replace("/", "-")
    return f"{moment}_{eval_set_id}_{safe_label}"


def _read_git_sha() -> str | None:
    """Return the project HEAD SHA, or None if git or the repo is unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _write_run_json(run_dir: Path, record: RunRecord) -> None:
    write_json(run_dir / "run.json", record.model_dump(mode="json"))


def _write_summary(run_dir: Path, summary: RunSummary) -> None:
    write_json(run_dir / "summary.json", summary.model_dump(mode="json"))


def _artifact_rel(entry: MatrixEntry) -> str:
    return str(Path(entry.case.id) / entry.model / f"seed-{entry.seed}")


def _failure_summary(
    entry: MatrixEntry,
    status: CaseStatus,
    *,
    error: str | None = None,
    cost_usd: float = 0.0,
) -> CaseSummary:
    return CaseSummary(
        case_id=entry.case.id,
        model=entry.model,
        seed=entry.seed,
        status=status,
        cost_usd=cost_usd,
        artifact_dir=_artifact_rel(entry),
        error=error,
    )


# --- main entrypoint -------------------------------------------------------

async def run_matrix(
    eval_set: EvalSet,
    config: RunConfig,
    settings: Settings,
    *,
    run_id: str | None = None,
) -> RunSummary:
    """Execute the planned matrix and return a :class:`RunSummary`."""

    started_at = datetime.now(UTC)
    rid = run_id or make_run_id(config.eval_set_id, config.run_label, now=started_at)
    run_dir = settings.results_dir / rid
    run_dir.mkdir(parents=True, exist_ok=True)

    record = RunRecord(
        run_id=rid,
        eval_set=eval_set.spec.id,
        started_at=started_at,
        git_sha=_read_git_sha(),
        config=config,
        environment={
            "pm_frontend_url": settings.pm_frontend_url,
            "pm_agent_url": settings.pm_agent_url,
            "pm_db_path": str(settings.pm_db_path),
        },
    )
    _write_run_json(run_dir, record)

    matrix = build_manifest(eval_set, config)
    write_manifest(matrix, run_dir / "manifest.json")
    logger.info("planned %d matrix entries for run %s", len(matrix), rid)

    budget = Budget(max_cost_usd=config.max_cost_usd, journal_path=run_dir / "cost.json")

    case_summaries: list[CaseSummary] = []
    aborted = False

    # Group by model so we can amortize one PMBrowser per model.
    by_model: dict[str, list[MatrixEntry]] = {}
    for entry in matrix:
        by_model.setdefault(entry.model, []).append(entry)

    # Late import: keeps playwright off the import path for unit tests
    # that exercise the runner manifest without a browser.
    from pmai_evals.browser.session import PMBrowser

    for model, entries in by_model.items():
        try:
            async with PMBrowser(settings) as browser:
                await browser.ensure_authenticated()
                for entry in entries:
                    try:
                        budget.check()
                    except BudgetExceededError:
                        logger.warning("budget exceeded; skipping remaining cases")
                        aborted = True
                        case_summaries.append(
                            _failure_summary(entry, CaseStatus.skipped_over_budget)
                        )
                        continue

                    summary = await _run_one(
                        browser=browser,
                        entry=entry,
                        eval_set=eval_set,
                        run_dir=run_dir,
                        settings=settings,
                        budget=budget,
                    )
                    case_summaries.append(summary)
                if aborted:
                    break
        except BrowserError as exc:
            logger.error("browser error for model %s: %s", model, exc)
            attempted = {(s.case_id, s.seed) for s in case_summaries if s.model == model}
            for entry in entries:
                if (entry.case.id, entry.seed) not in attempted:
                    case_summaries.append(
                        _failure_summary(entry, CaseStatus.failed, error=f"BrowserError: {exc}")
                    )
        except (BudgetExceededError, PMAIEvalsError):
            raise
        except OSError as exc:
            raise HarnessError(str(exc)) from exc
        if aborted:
            break

    finished_at = datetime.now(UTC)
    record = record.model_copy(update={"finished_at": finished_at})
    _write_run_json(run_dir, record)

    summary = RunSummary(
        run_id=rid,
        eval_set=eval_set.spec.id,
        started_at=started_at,
        finished_at=finished_at,
        cases=case_summaries,
        total_cost_usd=budget.total_cost_usd,
        aborted_over_budget=aborted,
    )
    _write_summary(run_dir, summary)
    return summary


# --- per-case ---------------------------------------------------------------

async def _run_one(
    *,
    browser: object,  # PMBrowser, untyped to avoid the cyclic import at module load
    entry: MatrixEntry,
    eval_set: EvalSet,
    run_dir: Path,
    settings: Settings,
    budget: Budget,
) -> CaseSummary:
    case = entry.case
    writer = RunArtifactWriter(
        run_dir=run_dir, case_id=case.id, model=entry.model, seed=entry.seed
    )
    writer.ensure_dir()
    timeout_s = case.timeout_s or eval_set.spec.default_timeout_s
    logger.info("starting %s", entry.label)

    try:
        chat = await browser.new_chat(  # type: ignore[attr-defined]
            model=entry.model, project=settings.pm_project
        )
        try:
            if case.fixtures:
                await chat.upload_fixtures(
                    [eval_set.fixture_path(name) for name in case.fixtures]
                )
            await chat.send_prompt(case.prompt)
            status_str = await chat.wait_for_completion(timeout_s=timeout_s)
            chat_id = chat.chat_id

            try:
                viewer_state = await chat.get_viewer_state()
            except BrowserError as exc:
                logger.warning("viewer state fetch failed: %s", exc)
                viewer_state = {"_error": str(exc)}

            try:
                await chat.save_screenshot(writer.screenshot_path)
            except BrowserError as exc:
                logger.warning("screenshot failed: %s", exc)

            try:
                final_answer = await chat.get_final_answer()
            except BrowserError as exc:
                logger.warning("final answer fetch failed: %s", exc)
                final_answer = ""
        finally:
            try:
                await chat.delete_chat()
            except BrowserError as exc:
                logger.warning("delete_chat failed (ignored): %s", exc)
            await chat.close()

        if not chat_id:
            raise BrowserError("chat_id was never populated; can't load trace")

        trace = load_trace(chat_id, settings.pm_db_path)
        writer.write_trace(trace)
        writer.write_viewer_state(viewer_state)
        writer.write_final_answer(final_answer or trace.final_answer)

        cost = cost_for_usage(
            model_id=entry.model,
            input_tokens=trace.usage.input_tokens,
            output_tokens=trace.usage.output_tokens,
            cached_tokens=trace.usage.cached_tokens,
        )
        writer.write_metrics(
            {
                "input_tokens": trace.usage.input_tokens,
                "output_tokens": trace.usage.output_tokens,
                "cached_tokens": trace.usage.cached_tokens,
                "reasoning_tokens": trace.usage.reasoning_tokens,
                "ttft_ms": trace.metrics.ttft_ms,
                "total_ms": trace.metrics.total_ms,
                "tool_latency_ms": trace.metrics.tool_latency_ms,
                "cost_usd": cost,
                "trace_status": str(trace.status),
            }
        )
        budget.charge(
            case_id=case.id,
            model=entry.model,
            seed=entry.seed,
            input_tokens=trace.usage.input_tokens,
            output_tokens=trace.usage.output_tokens,
            cached_tokens=trace.usage.cached_tokens,
        )

        status = CaseStatus.timed_out if status_str == "timed_out" else CaseStatus.completed
        writer.write_status(status)
        return CaseSummary(
            case_id=case.id,
            model=entry.model,
            seed=entry.seed,
            status=status,
            cost_usd=cost,
            artifact_dir=_artifact_rel(entry),
        )

    except ChatTimeoutError as exc:
        writer.write_status(CaseStatus.timed_out)
        writer.write_error(str(exc))
        return _failure_summary(entry, CaseStatus.timed_out, error=str(exc))
    except TraceNotFoundError as exc:
        writer.write_status(CaseStatus.failed)
        writer.write_error(f"TraceNotFound: {exc}")
        return _failure_summary(entry, CaseStatus.failed, error=str(exc))
    except Exception as exc:
        logger.exception("case failed: %s", entry.label)
        writer.write_status(CaseStatus.failed)
        writer.write_error(f"{type(exc).__name__}: {exc}")
        return _failure_summary(
            entry, CaseStatus.failed, error=f"{type(exc).__name__}: {exc}"
        )
