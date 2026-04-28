"""Plot per-model resource-usage comparisons from graded runs.

Walks ``runs/`` and, for every cell that has a ``grade.json``, aggregates
metrics from the adjacent ``metrics.json`` and ``trace.json``. Partial
and in-flight runs are safe — ungraded cells are silently skipped.

Produces a 1×3 multi-panel figure comparing models on:

1. Tool error rate (errored / total tool calls)
2. Mean wall time per case (seconds)
3. Mean tokens per case (stacked input + output)

Usage:
    uv run --with matplotlib python scripts/plot_model_metrics.py
    uv run --with matplotlib python scripts/plot_model_metrics.py --out metrics.png
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ModelStats:
    cells: int = 0
    total_ms: list[int] = field(default_factory=list)
    input_tokens: list[int] = field(default_factory=list)
    output_tokens: list[int] = field(default_factory=list)
    tool_calls: int = 0
    tool_errors: int = 0


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def collect(runs_dir: Path) -> dict[str, ModelStats]:
    stats: dict[str, ModelStats] = defaultdict(ModelStats)
    for grade_path in runs_dir.glob("*/*/*/seed-*/grade.json"):
        cell = grade_path.parent
        model = cell.parent.name

        metrics = _read_json(cell / "metrics.json") or {}
        trace = _read_json(cell / "trace.json") or {}
        tool_calls = trace.get("tool_calls") or []

        bucket = stats[model]
        bucket.cells += 1
        bucket.total_ms.append(int(metrics.get("total_ms") or 0))
        bucket.input_tokens.append(int(metrics.get("input_tokens") or 0))
        bucket.output_tokens.append(int(metrics.get("output_tokens") or 0))
        bucket.tool_calls += len(tool_calls)
        bucket.tool_errors += sum(
            1 for c in tool_calls if isinstance(c, dict) and c.get("is_error")
        )
    return stats


def _configure_style() -> None:
    import matplotlib as mpl

    mpl.rcParams.update({
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": "#333333",
        "axes.labelcolor": "#222222",
        "axes.titlesize": 12,
        "axes.titleweight": "semibold",
        "axes.labelsize": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "axes.axisbelow": True,
        "grid.color": "#DDDDDD",
        "grid.linestyle": "-",
        "grid.linewidth": 0.8,
        "xtick.color": "#333333",
        "ytick.color": "#333333",
        "xtick.labelsize": 10,
        "ytick.labelsize": 9,
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "legend.frameon": False,
        "legend.fontsize": 9,
    })


_PALETTE = [
    "#2E86AB", "#E63946", "#06A77D", "#F4A261",
    "#6A4C93", "#264653", "#E76F51", "#457B9D",
]


def _mean(xs: list[int]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def plot(stats: dict[str, ModelStats], out: Path) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    _configure_style()
    models = sorted(stats, key=lambda m: m)
    colors = [_PALETTE[i % len(_PALETTE)] for i in range(len(models))]
    x = list(range(len(models)))

    fig, (ax_err, ax_time, ax_tok) = plt.subplots(
        1, 3, figsize=(13, 5), constrained_layout=True
    )

    # --- Tool error rate ------------------------------------------------
    err_rate = [
        stats[m].tool_errors / stats[m].tool_calls if stats[m].tool_calls else 0.0
        for m in models
    ]
    ax_err.bar(x, err_rate, color=colors, width=0.6, edgecolor="white", linewidth=1.2)
    ax_err.set_title("Tool error rate")
    ax_err.set_ylabel("Errored / total calls")
    ax_err.set_ylim(0, max(err_rate + [0.05]) * 1.25 or 0.05)
    ax_err.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y*100:.0f}%"))

    # --- Wall time ------------------------------------------------------
    mean_sec = [_mean(stats[m].total_ms) / 1000 for m in models]
    ax_time.bar(x, mean_sec, color=colors, width=0.6, edgecolor="white", linewidth=1.2)
    ax_time.set_title("Mean wall time per case")
    ax_time.set_ylabel("Seconds")

    # --- Tokens (stacked input + output) --------------------------------
    mean_in = [_mean(stats[m].input_tokens) for m in models]
    mean_out = [_mean(stats[m].output_tokens) for m in models]
    ax_tok.bar(
        x, mean_in, color=colors, width=0.6,
        edgecolor="white", linewidth=1.2, label="input",
    )
    ax_tok.bar(
        x, mean_out, bottom=mean_in, color=colors, width=0.6,
        edgecolor="white", linewidth=1.2, alpha=0.45, label="output",
    )
    ax_tok.set_title("Mean tokens per case")
    ax_tok.set_ylabel("Tokens")
    ax_tok.yaxis.set_major_formatter(
        FuncFormatter(lambda y, _: f"{y/1000:.0f}k" if y >= 1000 else f"{y:.0f}")
    )
    # Proxy legend entries (solid for input, faded for output; gray)
    from matplotlib.patches import Patch
    ax_tok.legend(
        handles=[
            Patch(facecolor="#999999", label="input"),
            Patch(facecolor="#999999", alpha=0.45, label="output"),
        ],
        loc="upper left",
    )

    for ax in (ax_err, ax_time, ax_tok):
        ax.set_xticks(x)
        ax.set_xticklabels(models, rotation=15, ha="right")
        ax.margins(x=0.1)

    fig.savefig(out, dpi=160, bbox_inches="tight")
    print(f"wrote {out}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument("--out", type=Path, default=Path("model_metrics.png"))
    args = parser.parse_args()

    stats = collect(args.runs_dir)
    if not stats:
        raise SystemExit(f"no graded cells found under {args.runs_dir}")

    plot(stats, args.out)

    print("\nper-model:")
    for m in sorted(stats):
        s = stats[m]
        err = s.tool_errors / s.tool_calls if s.tool_calls else 0.0
        print(
            f"  {m:<22} n={s.cells}  "
            f"tool_err={err:.1%} ({s.tool_errors}/{s.tool_calls})  "
            f"time={_mean(s.total_ms)/1000:.1f}s  "
            f"tok={_mean(s.input_tokens):.0f} in / {_mean(s.output_tokens):.0f} out"
        )


if __name__ == "__main__":
    main()
