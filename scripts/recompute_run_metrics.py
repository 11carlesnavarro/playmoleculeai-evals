"""Rewrite a run's per-case metrics + run-level summary using the corrected
trace parser. Re-reads chat history from the source agent.db so we get the
deduped per-response usage and the per-call tiered cost.

Usage:
    uv run python scripts/recompute_run_metrics.py <run_dir> <agent_db>
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from pmai_evals.trace.http_reader import parse_trace


def _load_chat_rows(con: sqlite3.Connection, chat_uid: str) -> list[dict] | None:
    chat = con.execute("SELECT id FROM chats WHERE chat_uid=?", (chat_uid,)).fetchone()
    if chat is None:
        return None
    rows = con.execute(
        """
        SELECT id AS message_id, response_id, item_index, item_data, usage,
               latency_ms, ttft_ms, tool_latency, model, status, rating, created_at
        FROM messages WHERE chat_id=? ORDER BY id
        """,
        (chat["id"],),
    ).fetchall()
    return [dict(r) for r in rows]


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def main(run_dir: Path, agent_db: Path) -> None:
    con = sqlite3.connect(str(agent_db))
    con.row_factory = sqlite3.Row

    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text())
    old_total = float(summary.get("total_cost_usd") or 0.0)

    charges: list[dict] = []
    total_cost = 0.0

    for case in summary["cases"]:
        cell = run_dir / case["artifact_dir"]
        trace_path = cell / "trace.json"
        metrics_path = cell / "metrics.json"
        if not trace_path.exists() or not metrics_path.exists():
            print(f"  skip (no artifacts): {case['artifact_dir']}")
            continue

        old_trace = json.loads(trace_path.read_text())
        chat_uid = old_trace.get("chat_id") or ""
        rows = _load_chat_rows(con, chat_uid)
        if rows is None:
            print(f"  skip (chat {chat_uid} not in db): {case['artifact_dir']}")
            continue

        trace = parse_trace(rows, chat_uid, model=case["model"])
        new_trace = trace.to_dict()
        # ``to_dict`` emits enum members as objects; coerce status to string for json.
        new_trace["status"] = str(trace.status)
        _write_json(trace_path, new_trace)

        old_metrics = json.loads(metrics_path.read_text())
        old_metrics.update({
            "input_tokens": trace.usage.input_tokens,
            "output_tokens": trace.usage.output_tokens,
            "cached_tokens": trace.usage.cached_tokens,
            "reasoning_tokens": trace.usage.reasoning_tokens,
            "ttft_ms": trace.metrics.ttft_ms,
            "total_ms": trace.metrics.total_ms,
            "tool_latency_ms": trace.metrics.tool_latency_ms,
            "cost_usd": trace.cost_usd,
            "trace_status": str(trace.status),
        })
        _write_json(metrics_path, old_metrics)

        case["cost_usd"] = trace.cost_usd
        total_cost += trace.cost_usd

        charges.append({
            "case_id": case["case_id"],
            "model": case["model"],
            "seed": case["seed"],
            "input_tokens": trace.usage.input_tokens,
            "output_tokens": trace.usage.output_tokens,
            "cached_tokens": trace.usage.cached_tokens,
            "cost_usd": trace.cost_usd,
        })

        print(f"  {case['case_id']:12s}  in={trace.usage.input_tokens:>10,}  out={trace.usage.output_tokens:>7,}  cost=${trace.cost_usd:.4f}")

    summary["total_cost_usd"] = round(total_cost, 6)
    _write_json(summary_path, summary)

    cost_path = run_dir / "cost.json"
    cost: dict[str, object] = (
        json.loads(cost_path.read_text()) if cost_path.exists() else {"max_cost_usd": 0.0}
    )
    cost["total_cost_usd"] = round(total_cost, 6)
    cost["charges"] = charges
    _write_json(cost_path, cost)

    print()
    print(f"total cost: ${total_cost:.4f}  (was ${old_total:.4f})")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
