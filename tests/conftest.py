"""Shared pytest fixtures for unit tests."""

from __future__ import annotations

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
def sample_history() -> list[dict[str, Any]]:
    """A representative ``GET /v3/agent/chat/{id}`` response payload."""
    return [
        {"type": "message", "role": "user", "text": "Load 1CRN", "id": "resp-1"},
        {
            "type": "function_call",
            "name": "pmview_load",
            "call_id": "call-1",
            "arguments": {"identifier": "1CRN"},
            "id": "resp-2",
        },
        {
            "type": "function_call_output",
            "call_id": "call-1",
            "output": "loaded 1CRN",
            "is_error": False,
            "id": "resp-2",
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Loaded 1CRN successfully."}],
            "id": "resp-3",
        },
    ]
