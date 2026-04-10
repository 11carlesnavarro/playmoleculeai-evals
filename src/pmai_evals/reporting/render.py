"""Render benchmark data as markdown / HTML / JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATE_DIR = Path(__file__).parent / "templates"


# --- markdown -------------------------------------------------------------

def render_markdown(benchmark: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# Benchmark — {benchmark.get('eval_set', '?')}")
    lines.append("")
    lines.append(f"- **Run id**: `{benchmark.get('run_id', '?')}`")
    lines.append(f"- **Total cost**: ${benchmark.get('total_cost_usd', 0):.4f}")
    if benchmark.get("aborted_over_budget"):
        lines.append("- **Aborted over budget**: yes")
    lines.append("")
    lines.append("## Models")
    lines.append("")
    lines.append(
        "| Model | Cases (✓/total) | Assertions | Rubric pass | Rubric mean | Cost (USD) |"
    )
    lines.append(
        "|---|---|---|---|---|---|"
    )
    models = sorted(
        benchmark.get("models", []),
        key=lambda m: (-m.get("assertion_pass_rate", 0), m.get("model", "")),
    )
    for m in models:
        cases = f"{m['cases_completed']}/{m['cases_total']}"
        ar = f"{m['assertions_passed']}/{m['assertions_total']} ({m['assertion_pass_rate']:.0%})"
        rp = f"{m['rubric_pass']}/{m['rubric_total']}" if m["rubric_total"] else "—"
        rm = (
            f"{m['rubric_mean']:.2f}" if m.get("rubric_mean") is not None else "—"
        )
        lines.append(
            f"| `{m['model']}` | {cases} | {ar} | {rp} | {rm} | ${m['cost_usd']:.4f} |"
        )

    lines.append("")
    lines.append("## Per-case breakdown")
    lines.append("")
    cases = benchmark.get("cases") or {}
    for case_id, info in sorted(cases.items()):
        lines.append(f"### `{case_id}`")
        lines.append("")
        lines.append("| Model | Assertions | Rubric |")
        lines.append("|---|---|---|")
        for model, stats in sorted(info.get("models", {}).items()):
            ar = f"{stats['assertions_passed']}/{stats['assertions_total']}"
            rp = stats.get("rubric_passed")
            rp_str = "✓" if rp is True else ("✗" if rp is False else "—")
            lines.append(f"| `{model}` | {ar} | {rp_str} |")
        lines.append("")
    return "\n".join(lines) + "\n"


# --- html -----------------------------------------------------------------

def render_html(benchmark: dict[str, Any]) -> str:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("benchmark.html.j2")
    return template.render(b=benchmark)


# --- json -----------------------------------------------------------------

def render_json(benchmark: dict[str, Any]) -> str:
    return json.dumps(benchmark, indent=2, sort_keys=True) + "\n"
