"""Shared pytest fixtures for unit tests."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from pmai_evals.runner.artifacts import RunArtifact, RunArtifactWriter


@pytest.fixture
def tmp_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "test-run"
    run_dir.mkdir()
    return run_dir


@pytest.fixture
def writer(tmp_run_dir: Path) -> RunArtifactWriter:
    w = RunArtifactWriter(
        run_dir=tmp_run_dir, case_id="example", model="test-model", seed=0
    )
    w.ensure_dir()
    return w


def _make_trace_dict(
    *,
    final_answer: str = "",
    tool_calls: list[dict[str, Any]] | None = None,
    status: str = "completed",
) -> dict[str, Any]:
    return {
        "chat_id": "abc",
        "chat_pk": 1,
        "model": "test-model",
        "messages": [],
        "tool_calls": tool_calls or [],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cached_tokens": 0,
            "reasoning_tokens": 0,
        },
        "metrics": {"ttft_ms": 200, "total_ms": 1000, "tool_latency_ms": 50},
        "final_answer": final_answer,
        "status": status,
        "project": "test",
        "user_id": None,
        "raw_metadata": {},
    }


@pytest.fixture
def make_trace_dict():
    return _make_trace_dict


@pytest.fixture
def artifact_with_trace(writer: RunArtifactWriter):
    """Return a (writer, artifact, populate) triple for assertion tests."""

    def _populate(
        *,
        final_answer: str = "",
        tool_calls: list[dict[str, Any]] | None = None,
        viewer_state: dict[str, Any] | None = None,
        status: str = "completed",
    ) -> RunArtifact:
        trace = _make_trace_dict(
            final_answer=final_answer,
            tool_calls=tool_calls,
            status=status,
        )
        writer.cell_dir.mkdir(parents=True, exist_ok=True)
        writer.trace_path.write_text(
            json.dumps(trace, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        writer.write_final_answer(final_answer)
        writer.write_viewer_state(viewer_state or {})
        writer.write_status("completed")
        return RunArtifact(
            run_dir=writer.run_dir,
            case_id=writer.case_id,
            model=writer.model,
            seed=writer.seed,
        )

    return _populate


@pytest.fixture
def trace_db(tmp_path: Path) -> Path:
    """Create a tiny SQLite DB matching the agent schema."""
    db_path = tmp_path / "agent.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_uid TEXT NOT NULL,
                user_id TEXT,
                project TEXT,
                parent_id INTEGER,
                summary TEXT,
                instructions TEXT,
                created_at TEXT,
                deleted_at TEXT
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_uid TEXT,
                chat_id INTEGER NOT NULL,
                parent_id INTEGER,
                response_id TEXT,
                item_index INTEGER,
                item_data TEXT,
                created_at TEXT,
                rating INTEGER,
                model TEXT,
                usage TEXT,
                start_time TEXT,
                first_token_time TEXT,
                end_time TEXT,
                latency_ms INTEGER,
                ttft_ms INTEGER,
                tool_latency REAL,
                status TEXT
            );
            """
        )
        now = datetime.now(UTC).isoformat()
        conn.execute(
            "INSERT INTO chats (chat_uid, user_id, project, summary, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("test-chat-uid", "user-1", "pmai-evals", "test chat", now),
        )
        chat_pk = conn.execute("SELECT id FROM chats").fetchone()[0]

        # User prompt
        conn.execute(
            "INSERT INTO messages (chat_id, response_id, item_index, item_data, model, usage, "
            "latency_ms, ttft_ms, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                chat_pk,
                "resp-1",
                0,
                json.dumps(
                    {"type": "message", "role": "user", "text": "Load 1CRN"}
                ),
                None,
                None,
                None,
                None,
                None,
                now,
            ),
        )
        # Function call
        conn.execute(
            "INSERT INTO messages (chat_id, response_id, item_index, item_data, model, usage, "
            "latency_ms, ttft_ms, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                chat_pk,
                "resp-2",
                1,
                json.dumps(
                    {
                        "type": "function_call",
                        "name": "pmview_load",
                        "call_id": "call-1",
                        "arguments": json.dumps({"identifier": "1CRN"}),
                    }
                ),
                "test-model",
                json.dumps({"input_tokens": 50, "output_tokens": 20}),
                500,
                100,
                None,
                now,
            ),
        )
        # Function call output
        conn.execute(
            "INSERT INTO messages (chat_id, response_id, item_index, item_data, model, usage, "
            "latency_ms, ttft_ms, tool_latency, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                chat_pk,
                "resp-2",
                2,
                json.dumps(
                    {
                        "type": "function_call_output",
                        "call_id": "call-1",
                        "output": "loaded 1CRN",
                    }
                ),
                None,
                None,
                None,
                None,
                0.25,
                None,
                now,
            ),
        )
        # Assistant final
        conn.execute(
            "INSERT INTO messages (chat_id, response_id, item_index, item_data, model, usage, "
            "latency_ms, ttft_ms, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                chat_pk,
                "resp-3",
                3,
                json.dumps(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": "Loaded 1CRN successfully."}
                        ],
                    }
                ),
                "test-model",
                json.dumps({"input_tokens": 60, "output_tokens": 30}),
                400,
                None,
                None,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return db_path
