"""Render benchmark data as markdown / HTML / JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _fmt_pct_pm(mean: float | None, std: float | None) -> str:
    if mean is None:
        return "—"
    if std is None:
        return _fmt_pct(mean)
    return f"{mean * 100:.1f}% ± {std * 100:.1f}%"


def _fmt_score_pm(mean: float | None, std: float | None) -> str:
    if mean is None:
        return "—"
    if std is None:
        return f"{mean:.2f}"
    return f"{mean:.2f} ± {std:.2f}"


def render_markdown(benchmark: dict[str, Any]) -> str:
    lines: list[str] = [
        f"# Benchmark — {benchmark.get('eval_set', '?')}",
        "",
        f"- **Run id**: `{benchmark.get('run_id', '?')}`",
        f"- **Total cost**: ${benchmark.get('total_cost_usd', 0):.4f}",
    ]
    if benchmark.get("aborted_over_budget"):
        lines.append("- **Aborted over budget**: yes")
    lines += [
        "",
        "## Models",
        "",
        "| Model | Seed | Cases (✓/total) | Assertions | Rubric pass | Rubric mean | Cost (USD) |",
        "|---|---|---|---|---|---|---|",
    ]
    models = sorted(
        benchmark.get("models", []),
        key=lambda m: (
            -(m.get("assertion_score_mean_seed_mean") or m.get("assertion_score_mean") or 0),
            m.get("model", ""),
        ),
    )
    for m in models:
        for s in m.get("seeds") or []:
            cases = f"{s['cases_completed']}/{s['cases_total']}"
            ar = (
                f"{s['assertions_score']:.2f}/{s['assertions_total']} "
                f"({_fmt_pct(s['assertion_score_mean'])})"
            )
            rp = f"{s['rubric_pass']}/{s['rubric_total']}" if s["rubric_total"] else "—"
            rm = f"{s['rubric_mean']:.2f}" if s.get("rubric_mean") is not None else "—"
            lines.append(
                f"| `{m['model']}` | {s['seed']} | {cases} | {ar} | {rp} | {rm} | ${s['cost_usd']:.4f} |"
            )
        if (m.get("n_seeds") or 0) >= 2:
            ar_summary = _fmt_pct_pm(
                m.get("assertion_score_mean_seed_mean"),
                m.get("assertion_score_mean_seed_std"),
            )
            rp_summary = _fmt_pct_pm(m.get("rubric_pass_rate_mean"), m.get("rubric_pass_rate_std"))
            rp_cell = f"**{rp_summary}**" if m.get("rubric_total") else "—"
            rm_summary = _fmt_score_pm(m.get("rubric_mean_seed_mean"), m.get("rubric_mean_seed_std"))
            rm_cell = f"**{rm_summary}**" if rm_summary != "—" else "—"
            lines.append(
                f"| `{m['model']}` | **mean ± std** | — | **{ar_summary}** | {rp_cell} | {rm_cell} | ${m['cost_usd']:.4f} |"
            )
    return "\n".join(lines) + "\n"


def render_html(benchmark: dict[str, Any]) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    return env.get_template("benchmark.html.j2").render(b=benchmark)


def render_json(benchmark: dict[str, Any]) -> str:
    return json.dumps(benchmark, indent=2, sort_keys=True) + "\n"
