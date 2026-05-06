"""Render benchmark data as markdown / HTML / JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).parent / "templates"


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
        "| Model | Cases (✓/total) | Assertions | Rubric pass | Rubric mean | Cost (USD) |",
        "|---|---|---|---|---|---|",
    ]
    models = sorted(
        benchmark.get("models", []),
        key=lambda m: (-m.get("assertion_pass_rate", 0), m.get("model", "")),
    )
    for m in models:
        cases = f"{m['cases_completed']}/{m['cases_total']}"
        ar = f"{m['assertions_passed']}/{m['assertions_total']} ({m['assertion_pass_rate']:.0%})"
        rp = f"{m['rubric_pass']}/{m['rubric_total']}" if m["rubric_total"] else "—"
        rm = f"{m['rubric_mean']:.2f}" if m.get("rubric_mean") is not None else "—"
        lines.append(
            f"| `{m['model']}` | {cases} | {ar} | {rp} | {rm} | ${m['cost_usd']:.4f} |"
        )

    lines += ["", "## Per-case breakdown", ""]
    for case_id, info in sorted((benchmark.get("cases") or {}).items()):
        lines += [f"### `{case_id}`", "", "| Model | Assertions | Rubric |", "|---|---|---|"]
        for model, stats in sorted(info.get("models", {}).items()):
            ar = f"{stats['assertions_passed']}/{stats['assertions_total']}"
            passed = stats.get("rubric_passed")
            rp = "✓" if passed is True else ("✗" if passed is False else "—")
            lines.append(f"| `{model}` | {ar} | {rp} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_html(benchmark: dict[str, Any]) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    return env.get_template("benchmark.html.j2").render(b=benchmark)


def render_json(benchmark: dict[str, Any]) -> str:
    return json.dumps(benchmark, indent=2, sort_keys=True) + "\n"
