"""Plot per-model accuracy vs cost from graded runs.

Walks ``runs/`` and aggregates every cell that has a ``grade.json`` —
partially-graded or still-running directories are safe, ungraded cells
are skipped. Per-cell ``cost_usd`` comes from ``metrics.json``;
accuracy is ``assertions_passed / assertions_total`` summed across all
graded cells for each model.

Usage:
    uv run --with matplotlib python scripts/plot_accuracy_vs_cost.py
    uv run --with matplotlib python scripts/plot_accuracy_vs_cost.py --out foo.png
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ModelStats:
    passed: int = 0
    total: int = 0
    cost: float = 0.0
    cells: int = 0

    @property
    def accuracy(self) -> float:
        return self.passed / self.total if self.total else 0.0


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def collect(runs_dir: Path) -> dict[str, ModelStats]:
    stats: dict[str, ModelStats] = defaultdict(ModelStats)
    for grade_path in runs_dir.glob("*/*/*/seed-*/grade.json"):
        grade = _read_json(grade_path)
        if grade is None:
            continue
        summary = grade.get("summary") or {}
        total = int(summary.get("assertions_total") or 0)
        if total == 0:
            continue
        passed = int(summary.get("assertions_passed") or 0)
        model = grade_path.parent.parent.name  # .../<case>/<model>/seed-N/grade.json
        cost = float(
            (_read_json(grade_path.parent / "metrics.json") or {}).get("cost_usd") or 0.0
        )
        bucket = stats[model]
        bucket.passed += passed
        bucket.total += total
        bucket.cost += cost
        bucket.cells += 1
    return stats


def _configure_style() -> None:
    import matplotlib as mpl

    mpl.rcParams.update({
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": "#333333",
        "axes.labelcolor": "#222222",
        "axes.titlesize": 14,
        "axes.titleweight": "semibold",
        "axes.labelsize": 11,
        "axes.labelweight": "medium",
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": "#DDDDDD",
        "grid.linestyle": "-",
        "grid.linewidth": 0.8,
        "xtick.color": "#333333",
        "ytick.color": "#333333",
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "legend.frameon": False,
    })


def plot(stats: dict[str, ModelStats], out: Path) -> None:
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, LogLocator

    _configure_style()

    models = sorted(stats, key=lambda m: (stats[m].cost, m))
    costs = [stats[m].cost for m in models]
    accuracies = [stats[m].accuracy for m in models]

    palette = [
        "#2E86AB", "#E63946", "#06A77D", "#F4A261",
        "#6A4C93", "#264653", "#E76F51", "#457B9D",
    ]
    colors = [palette[i % len(palette)] for i in range(len(models))]

    fig, ax = plt.subplots(figsize=(9, 6))

    ax.scatter(
        costs,
        accuracies,
        s=220,
        c=colors,
        edgecolors="white",
        linewidths=1.8,
        zorder=3,
    )

    cost_span = max(costs) / max(min(costs), 1e-6) if costs else 1
    use_log = cost_span > 5 and min(costs) > 0
    if use_log:
        ax.set_xscale("log")
        ax.xaxis.set_major_locator(LogLocator(base=10, subs=(1.0, 2.0, 5.0)))

    ax.xaxis.set_major_formatter(
        FuncFormatter(lambda x, _: f"${x:,.2f}" if x >= 0.01 else f"${x:.3f}")
    )
    ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y*100:.0f}%"))
    ax.set_ylim(-0.02, 1.05)

    if costs:
        lo = min(costs) / (1.8 if use_log else 1.1)
        hi = max(costs) * (1.8 if use_log else 1.15)
        ax.set_xlim(max(lo, 1e-4), hi)

    for model, cost, acc in zip(models, costs, accuracies):
        ax.annotate(
            model,
            (cost, acc),
            xytext=(10, 0),
            textcoords="offset points",
            fontsize=10,
            color="#222222",
            va="center",
            ha="left",
        )

    ax.set_xlabel("Total cost (USD)")
    ax.set_ylabel("Assertion pass rate")
    ax.set_title("Accuracy vs cost")

    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(out, dpi=160, bbox_inches="tight")
    print(f"wrote {out}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument("--out", type=Path, default=Path("accuracy_vs_cost.png"))
    args = parser.parse_args()

    stats = collect(args.runs_dir)
    if not stats:
        raise SystemExit(f"no graded cells found under {args.runs_dir}")

    plot(stats, args.out)

    print("\nper-model:")
    for model in sorted(stats, key=lambda m: -stats[m].accuracy):
        s = stats[model]
        print(
            f"  {model:<22} {s.passed}/{s.total} ({s.accuracy:.0%})  "
            f"${s.cost:>7.4f}  ({s.cells} cells)"
        )


if __name__ == "__main__":
    main()
