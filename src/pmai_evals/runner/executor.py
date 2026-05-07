"""Drive the (case × model × seed) matrix end-to-end.

Per-case exceptions are caught at the isolation barrier and recorded as
``status: failed``, so a single failure does not poison the run.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from pmai_evals._io import read_json_or, write_json
from pmai_evals.browser.project_files import clear_project, upload_to_project
from pmai_evals.browser.viewer_loader import (
    export_viewer_state,
    list_system_names,
    load_local_file,
    load_pdb_id,
)
from pmai_evals.config import Settings
from pmai_evals.errors import (
    BrowserError,
    BudgetExceededError,
    ChatTimeoutError,
    HarnessError,
    PMAIEvalsError,
    TraceNotFoundError,
)
from pmai_evals.runner.artifacts import RunArtifactWriter, CellPaths, iter_cell_paths
from pmai_evals.runner.budget import Budget
from pmai_evals.runner.manifest import MatrixEntry, build_manifest, write_manifest
from pmai_evals.schemas import (
    CaseStatus,
    CaseSummary,
    EvalSet,
    PreloadSpec,
    RunConfig,
    RunRecord,
    RunSummary,
)
from pmai_evals.trace import parse_trace

logger = logging.getLogger(__name__)

T = TypeVar("T")


def make_run_id(eval_set_id: str, label: str, *, now: datetime | None = None) -> str:
    moment = (now or datetime.now(UTC)).strftime("%Y%m%d-%H%M%S")
    safe_label = label.replace(" ", "-").replace("/", "-")
    return f"{moment}_{eval_set_id}_{safe_label}"


def _read_git_sha() -> str | None:
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


def _record_failure(
    run_dir: Path, entry: MatrixEntry, status: CaseStatus, error: str | None = None,
) -> None:
    """Persist a failure disposition to disk so it survives cancellation."""
    writer = RunArtifactWriter(
        run_dir=run_dir, case_id=entry.case.id, model=entry.model, seed=entry.seed,
    )
    writer.ensure_dir()
    writer.write_status(status)
    if error:
        writer.write_error(error)


def _read_status(cell: CellPaths) -> CaseStatus | None:
    """Best-effort read of one cell's ``status`` file."""
    try:
        text = cell.status_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return CaseStatus(text)
    except ValueError:
        return None


def _completed_keys(run_dir: Path) -> set[tuple[str, str, int]]:
    """Keys for cells whose ``status`` file reads ``completed``.

    Per-cell status is the source of truth: it lands as soon as a case
    settles, so a cancelled run that never wrote ``summary.json`` does not
    lose finished cells from the skip set.
    """
    return {
        (cell.case_id, cell.model, cell.seed)
        for cell in iter_cell_paths(run_dir)
        if _read_status(cell) is CaseStatus.completed
    }


def _load_case_summaries(run_dir: Path) -> list[CaseSummary]:
    """Reconstruct ``CaseSummary`` entries from per-cell artifacts on disk."""
    summaries: list[CaseSummary] = []
    for cell in iter_cell_paths(run_dir):
        status = _read_status(cell)
        if status is None:
            continue
        metrics = read_json_or(cell.metrics_path, {})
        error = (
            cell.error_path.read_text(encoding="utf-8").strip() or None
            if cell.error_path.exists() else None
        )
        summaries.append(CaseSummary(
            case_id=cell.case_id, model=cell.model, seed=cell.seed, status=status,
            cost_usd=float(metrics.get("cost_usd") or 0.0),
            artifact_dir=str(cell.cell_dir.relative_to(cell.run_dir)),
            error=error,
        ))
    return summaries


def _write_record(run_dir: Path, record: RunRecord) -> None:
    write_json(run_dir / "run.json", record.model_dump(mode="json"))


async def _soft(label: str, fn: Callable[[], Awaitable[T]], default: T) -> T:
    """Run ``fn``; on BrowserError log a warning and return ``default``."""
    try:
        return await fn()
    except BrowserError as exc:
        logger.warning("%s failed: %s", label, exc)
        return default


# --- main entrypoint ------------------------------------------------------

async def run_matrix(
    eval_set: EvalSet,
    config: RunConfig,
    settings: Settings,
    *,
    run_id: str | None = None,
    overwrite: bool = False,
) -> RunSummary:
    """Execute the planned matrix and return a :class:`RunSummary`."""
    started_at = datetime.now(UTC)
    rid = run_id or make_run_id(config.eval_set_id, config.run_label, now=started_at)
    run_dir = settings.results_dir / rid
    reuse_existing = run_id is not None and run_dir.is_dir()
    run_dir.mkdir(parents=True, exist_ok=True)
    if reuse_existing:
        logger.info("reusing existing run dir %s", run_dir)

    record = RunRecord(
        run_id=rid,
        eval_set=eval_set.spec.id,
        started_at=started_at,
        git_sha=_read_git_sha(),
        config=config,
        environment={
            "pm_frontend_url": settings.pm_frontend_url,
            "pm_agent_url": settings.pm_agent_url,
        },
    )
    _write_record(run_dir, record)

    matrix = build_manifest(eval_set, config)
    if reuse_existing and not overwrite:
        already_done = _completed_keys(run_dir)
        if already_done:
            kept = [e for e in matrix if (e.case.id, e.model, e.seed) not in already_done]
            if len(kept) < len(matrix):
                logger.info(
                    "skipping %d already-completed entries; pass --overwrite to re-run",
                    len(matrix) - len(kept),
                )
            matrix = kept
    write_manifest(matrix, run_dir / "manifest.json")
    logger.info("planned %d matrix entries for run %s", len(matrix), rid)

    budget = Budget(max_cost_usd=config.max_cost_usd, journal_path=run_dir / "cost.json")
    by_model: dict[str, list[MatrixEntry]] = {}
    for entry in matrix:
        by_model.setdefault(entry.model, []).append(entry)

    # Late import keeps playwright off the import path for unit tests that
    # exercise the runner manifest without a browser.
    from pmai_evals.browser.session import PMBrowser

    aborted = False

    def write_summary() -> RunSummary:
        cases = _load_case_summaries(run_dir)
        snapshot = RunSummary(
            run_id=rid,
            eval_set=eval_set.spec.id,
            started_at=started_at,
            finished_at=datetime.now(UTC),
            cases=cases,
            total_cost_usd=sum(c.cost_usd for c in cases),
            aborted_over_budget=aborted,
        )
        write_json(run_dir / "summary.json", snapshot.model_dump(mode="json"))
        return snapshot

    for model, entries in by_model.items():
        attempted: set[tuple[str, int]] = set()
        try:
            async with PMBrowser(settings) as browser:
                await browser.ensure_authenticated()
                for entry in entries:
                    try:
                        budget.check()
                    except BudgetExceededError:
                        logger.warning("budget exceeded; skipping remaining cases")
                        aborted = True
                        _record_failure(run_dir, entry, CaseStatus.skipped_over_budget)
                        write_summary()
                        continue
                    await _run_one(
                        browser=browser, entry=entry, eval_set=eval_set,
                        run_dir=run_dir, budget=budget, settings=settings,
                    )
                    attempted.add((entry.case.id, entry.seed))
                    write_summary()
                if aborted:
                    break
        except BrowserError as exc:
            logger.error("browser error for model %s: %s", model, exc)
            for entry in entries:
                if (entry.case.id, entry.seed) in attempted:
                    continue
                _record_failure(
                    run_dir, entry, CaseStatus.failed, f"BrowserError: {exc}",
                )
            write_summary()
        except (BudgetExceededError, PMAIEvalsError):
            raise
        except OSError as exc:
            raise HarnessError(str(exc)) from exc
        if aborted:
            break

    finished_at = datetime.now(UTC)
    record = record.model_copy(update={"finished_at": finished_at})
    _write_record(run_dir, record)
    return write_summary()


# --- per-case -------------------------------------------------------------

async def _preload_scenario(
    page: object,
    preload: PreloadSpec,
    eval_set: EvalSet,
    *,
    project: str,
    frontend_url: str,
) -> None:
    if preload.project.files:
        await upload_to_project(
            page,  # type: ignore[arg-type]
            [eval_set.fixture_path(name) for name in preload.project.files],
            project=project,
            frontend_url=frontend_url,
        )
    for pdb_id in preload.viewer.pdb_ids:
        await load_pdb_id(page, pdb_id)  # type: ignore[arg-type]
    for name in preload.viewer.files:
        await load_local_file(page, eval_set.fixture_path(name))  # type: ignore[arg-type]


async def _run_one(
    *,
    browser: object,  # PMBrowser; untyped to keep the cyclic import out of module load
    entry: MatrixEntry,
    eval_set: EvalSet,
    run_dir: Path,
    budget: Budget,
    settings: Settings,
) -> CaseSummary:
    case = entry.case
    writer = RunArtifactWriter(
        run_dir=run_dir, case_id=case.id, model=entry.model, seed=entry.seed
    )
    writer.ensure_dir()
    timeout_s = case.timeout_s or eval_set.spec.default_timeout_s
    logger.info("starting %s", entry.label)

    try:
        chat = await browser.new_chat(model=entry.model)  # type: ignore[attr-defined]
        try:
            await clear_project(
                chat.page,
                project=settings.pm_project,
                frontend_url=settings.pm_frontend_url,
            )
            if not case.preload.is_empty():
                await _preload_scenario(
                    chat.page, case.preload, eval_set,
                    project=settings.pm_project,
                    frontend_url=settings.pm_frontend_url,
                )
            await chat.send_prompt(case.prompt)
            status_str = await chat.wait_for_completion(timeout_s=timeout_s)
            chat_id = chat.chat_id

            history = await _soft("chat history fetch", chat.fetch_history, [])
            viewer_state = await _soft(
                "viewer state fetch", chat.get_viewer_state, {"_error": "fetch failed"}
            )
            viewer_selection = await _soft(
                "viewer selection fetch", chat.get_viewer_selection, {"_error": "fetch failed"}
            )
            await _soft(
                "screenshot", lambda: chat.save_screenshot(writer.screenshot_path), None
            )
            final_answer = await _soft("final answer fetch", chat.get_final_answer, "")

            try:
                if await list_system_names(chat.page):
                    await export_viewer_state(chat.page, writer.systems_dir)
            except BrowserError as exc:
                logger.warning("systems export failed: %s", exc)
        finally:
            await chat.close()

        if not chat_id:
            raise BrowserError("chat_id was never populated; can't parse trace")

        trace = parse_trace(history, chat_id, model=entry.model)
        writer.write_trace(trace)
        if not trace.messages and not trace.tool_calls:
            raise BrowserError(
                f"agent rollout produced no events (chat_id={chat_id}); "
                "treat as failed so re-run via --run-id retries the case"
            )
        writer.write_viewer_state(viewer_state)
        writer.write_viewer_selection(viewer_selection)
        writer.write_final_answer(final_answer or trace.final_answer)

        cost = trace.cost_usd
        writer.write_metrics({
            "input_tokens": trace.usage.input_tokens,
            "output_tokens": trace.usage.output_tokens,
            "cached_tokens": trace.usage.cached_tokens,
            "reasoning_tokens": trace.usage.reasoning_tokens,
            "ttft_ms": trace.metrics.ttft_ms,
            "total_ms": trace.metrics.total_ms,
            "tool_latency_ms": trace.metrics.tool_latency_ms,
            "cost_usd": cost,
            "trace_status": str(trace.status),
        })
        budget.charge(
            case_id=case.id,
            model=entry.model,
            seed=entry.seed,
            input_tokens=trace.usage.input_tokens,
            output_tokens=trace.usage.output_tokens,
            cached_tokens=trace.usage.cached_tokens,
            cost_usd=cost,
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
