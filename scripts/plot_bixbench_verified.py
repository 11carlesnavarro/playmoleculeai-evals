"""Bar plot of BixBench-Verified-50 accuracies vs the public-baselines figure.

Usage::

    uv run python scripts/plot_bixbench_verified.py \
        --run 20260504-174841_bixbench-verified_final \
        --model gpt-5.4-mini \
        --label "playmoleculeAI\n(GPT5.4-mini)" \
        --out scripts/bixbench_verified_compare.png
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

# Public BixBench-Verified-50 baselines (futurehouse/BixBench leaderboard).
BASELINES: list[tuple[str, float]] = [
    ("Claude Code\n(Opus 4.6)", 65.3),
    ("OpenAI Agents SDK\n(GPT5.2)", 61.3),
    ("Edison Analysis", 78.0),
    ("Biomni Lab\n(20260203)", 88.7),
]

# Two anchor stops define the muted slate-blue ramp; every bar color is derived
# from this colormap so adding a baseline never requires picking a new hex.
PALETTE = LinearSegmentedColormap.from_list(
    "slate_blue", ["#aab8c9", "#3a4a66"],
)


def accuracy_stats(run_dir: Path, model: str) -> tuple[float, float | None]:
    """Return (mean_pct, std_pct) across seeds for ``model``.

    Falls back to the pooled assertion pass rate when a single seed was run.
    """
    bench = json.loads((run_dir / "benchmark.json").read_text())
    for entry in bench.get("models", []):
        if entry.get("model") != model:
            continue
        mean = entry.get("assertion_pass_rate_mean")
        std = entry.get("assertion_pass_rate_std")
        if mean is None:
            mean = entry.get("assertion_pass_rate")
        if mean is None:
            break
        return 100 * mean, (100 * std if std is not None else None)
    raise SystemExit(f"no graded cases for model {model!r} in {run_dir}")


def plot(
    rows: list[tuple[str, float, float | None]], out: Path, title: str
) -> None:
    labels = [r[0] for r in rows]
    values = [r[1] for r in rows]
    stds = [r[2] for r in rows]
    # One palette stop per bar, evenly spaced across the ramp by rank. Each
    # bar therefore gets a unique slate shade regardless of how close two
    # scores happen to land.
    n = len(rows)
    colors = [PALETTE(i / (n - 1)) for i in range(n)]
    edge = PALETTE(0.95)
    yerr = [s if s is not None else 0.0 for s in stds]

    fig, ax = plt.subplots(figsize=(7.2, 7.0))
    bars = ax.bar(
        labels, values,
        color=colors, edgecolor=edge, linewidth=1.0,
        yerr=yerr, capsize=6,
        error_kw={"ecolor": "#1f2533", "elinewidth": 1.2},
    )
    for bar, v, i in zip(bars, values, range(n)):
        text_color = "#ffffff" if i / (n - 1) > 0.55 else "#1f2533"
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            v - 6,
            f"{v:.1f}",
            ha="center", va="top", fontsize=12, color=text_color,
        )
    ax.set_ylim(0, 100)
    ax.set_ylabel("Accuracy (%)", fontsize=12)
    ax.set_title(title, fontsize=18, pad=16)
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="x", labelsize=10)
    plt.setp(ax.get_xticklabels(), rotation=30, ha="right")
    fig.tight_layout()
    fig.savefig(out, dpi=160)
    print(f"wrote {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="Run id under runs/")
    parser.add_argument("--model", required=True, help="Model id present in benchmark.json")
    parser.add_argument("--label", default="playmoleculeAI", help="x-axis label for our bar")
    parser.add_argument(
        "--out", type=Path,
        default=Path("scripts/bixbench_verified_compare.png"),
    )
    parser.add_argument(
        "--results-dir", type=Path, default=Path("runs"),
    )
    args = parser.parse_args()

    run_dir = args.results_dir / args.run
    ours_mean, ours_std = accuracy_stats(run_dir, args.model)
    label = args.label.replace("\\n", "\n")
    rows: list[tuple[str, float, float | None]] = [
        (lbl, val, None) for lbl, val in BASELINES
    ]
    rows.append((label, ours_mean, ours_std))
    rows.sort(key=lambda r: r[1])
    plot(rows, args.out, "BixBench-Verified-50")


if __name__ == "__main__":
    main()
