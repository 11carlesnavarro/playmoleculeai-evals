"""Typer CLI: ``pmai-evals {setup-auth,run,grade,report,critique}``.

Thin wrappers around library functions. No business logic in this file.

Exit codes:
    0 — success
    1 — user error (bad args, missing eval set, ...)
    2 — budget abort
    3 — unrecoverable harness error
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.logging import RichHandler

from pmai_evals.config import Settings
from pmai_evals.errors import (
    AssertionConfigError,
    BudgetExceededError,
    EvalSetLoadError,
    HarnessError,
    PMAIEvalsError,
)
from pmai_evals.eval_loader import load_eval_set
from pmai_evals.pricing import load_registry
from pmai_evals.reporting import aggregate_run, render_html, render_json, render_markdown
from pmai_evals.runner.executor import run_matrix
from pmai_evals.runner.manifest import build_manifest
from pmai_evals.schemas import RunConfig

app = typer.Typer(
    add_completion=False,
    help="playmoleculeAI evaluation harness.",
    no_args_is_help=True,
)
console = Console()


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )


def _settings() -> Settings:
    s = Settings()
    _configure_logging(s.pmai_evals_log_level)
    return s


# --- setup-auth -----------------------------------------------------------

@app.command(name="setup-auth")
def setup_auth() -> None:
    """One-time interactive login. Saves storage_state.json."""
    settings = _settings()

    async def _go() -> None:
        from pmai_evals.browser.session import PMBrowser

        async with PMBrowser(settings) as browser:
            await browser.login_and_save()

    try:
        asyncio.run(_go())
    except PMAIEvalsError as exc:
        console.print(f"[red]auth failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]storage state saved to[/green] {settings.auth_state_path}")


# --- run ------------------------------------------------------------------

def _resolve_models(
    explicit: list[str] | None,
    tier: str | None,
) -> list[str]:
    registry = load_registry()
    if explicit:
        return explicit
    if tier:
        return [m.id for m in registry.by_tier(tier)]  # type: ignore[arg-type]
    return [m.id for m in registry.by_tier("flagship")]


@app.command()
def run(
    eval_set: Annotated[str, typer.Option("--eval-set", "-e", help="Eval set id")],
    models: Annotated[
        str | None,
        typer.Option("--models", help="Comma-separated model ids"),
    ] = None,
    tier: Annotated[
        str | None,
        typer.Option("--tier", help="flagship | cheap | all"),
    ] = None,
    seeds: Annotated[int, typer.Option("--seeds", help="Seeds per case", min=1)] = 1,
    max_cost: Annotated[
        float | None,
        typer.Option("--max-cost", help="Override $PMAI_EVALS_MAX_COST_USD"),
    ] = None,
    headless: Annotated[bool, typer.Option("--headless/--no-headless")] = True,
    case: Annotated[
        list[str] | None,
        typer.Option("--case", help="Run only this case (repeatable)"),
    ] = None,
    label: Annotated[str, typer.Option("--label", help="Run id suffix")] = "iter",
    judge_model: Annotated[
        str | None, typer.Option("--judge-model", help="Override judge model")
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print manifest, do not execute"),
    ] = False,
) -> None:
    """Run the (case × model × seed) matrix."""

    settings = _settings()

    try:
        es = load_eval_set(eval_set)
    except (EvalSetLoadError, AssertionConfigError) as exc:
        console.print(f"[red]eval set error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    chosen_models = _resolve_models(
        [m.strip() for m in models.split(",")] if models else None,
        tier,
    )

    config = RunConfig(
        eval_set_id=eval_set,
        models=chosen_models,
        seeds=seeds,
        max_cost_usd=max_cost if max_cost is not None else settings.pmai_evals_max_cost_usd,
        headless=headless,
        tier=tier if tier in {"flagship", "cheap", "all"} else None,  # type: ignore[arg-type]
        case_filter=list(case) if case else None,
        run_label=label,
        judge_model=judge_model or settings.pmai_evals_judge_model,
    )

    # Headless override.
    if headless != settings.pmai_evals_headless:
        settings = settings.model_copy(update={"pmai_evals_headless": headless})

    if dry_run:
        manifest = build_manifest(es, config)
        console.print(f"[bold]Planned matrix[/bold] ({len(manifest)} entries):")
        for entry in manifest:
            console.print(f"  {entry.label}")
        return

    try:
        summary = asyncio.run(run_matrix(es, config, settings))
    except BudgetExceededError as exc:
        console.print(f"[yellow]budget abort:[/yellow] {exc}")
        raise typer.Exit(code=2) from exc
    except HarnessError as exc:
        console.print(f"[red]harness error:[/red] {exc}")
        raise typer.Exit(code=3) from exc
    except PMAIEvalsError as exc:
        console.print(f"[red]error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]run complete:[/green] {summary.run_id}")
    console.print(
        f"  total cost: ${summary.total_cost_usd:.4f} | "
        f"cases: {len(summary.cases)}"
    )
    if summary.aborted_over_budget:
        console.print("[yellow]  aborted over budget[/yellow]")
        raise typer.Exit(code=2)


# --- grade ----------------------------------------------------------------

@app.command()
def grade(
    run_id: Annotated[str, typer.Argument(help="Run id under $PMAI_EVALS_RESULTS_DIR")],
    judge_model: Annotated[
        str | None, typer.Option("--judge-model", help="Override judge model")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Re-grade even if grade.json exists")
    ] = False,
    rubric: Annotated[
        Path | None, typer.Option("--rubric", help="Override the eval set's rubric path")
    ] = None,
) -> None:
    """Grade an existing run. Re-runnable."""
    from pmai_evals.grading.grade_run import grade_run_sync

    settings = _settings()
    try:
        written = grade_run_sync(
            run_id,
            settings,
            judge_model=judge_model,
            rubric_override=rubric,
            force=force,
        )
    except PMAIEvalsError as exc:
        console.print(f"[red]grade error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]graded {written} cells[/green] for run {run_id}")


# --- report ---------------------------------------------------------------

@app.command()
def report(
    run_id: Annotated[str, typer.Argument()],
    fmt: Annotated[
        str,
        typer.Option("--format", "-f", help="markdown | html | json"),
    ] = "markdown",
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Write to file instead of stdout"),
    ] = None,
) -> None:
    """Render a benchmark report from a graded run."""
    settings = _settings()
    run_dir = settings.results_dir / run_id
    if not run_dir.is_dir():
        console.print(f"[red]run not found:[/red] {run_dir}")
        raise typer.Exit(code=1)

    benchmark = aggregate_run(run_dir)
    if fmt == "markdown":
        body = render_markdown(benchmark)
    elif fmt == "html":
        body = render_html(benchmark)
    elif fmt == "json":
        body = render_json(benchmark)
    else:
        console.print(f"[red]unknown format:[/red] {fmt}")
        raise typer.Exit(code=1)

    if out is not None:
        out.write_text(body, encoding="utf-8")
        console.print(f"[green]wrote {out}[/green]")
    else:
        sys.stdout.write(body)


# --- critique -------------------------------------------------------------

@app.command()
def critique(run_id: Annotated[str, typer.Argument()]) -> None:
    """Run the grade-the-grader pass; emit critique.json."""
    from pmai_evals.grading.critique import critique_run

    settings = _settings()
    run_dir = settings.results_dir / run_id
    try:
        result = critique_run(run_dir)
    except PMAIEvalsError as exc:
        console.print(f"[red]critique error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    findings = result.get("non_discriminating") or []
    console.print(f"[bold]{len(findings)} non-discriminating finding(s)[/bold]")
    for f in findings:
        console.print(f"  - {f['assertion_or_dimension']}: {f['reason']}")
    console.print(f"\nsummary: {result.get('summary')}")


# --- list-models ----------------------------------------------------------

@app.command(name="list-models")
def list_models() -> None:
    """Print the model registry."""
    registry = load_registry()
    payload = [m.model_dump() for m in registry.models]
    console.print(json.dumps(payload, indent=2))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
