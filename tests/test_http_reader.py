"""Unit tests for ``pmai_evals.trace.http_reader.parse_trace``."""

from __future__ import annotations

from typing import Any

from pmai_evals.trace import parse_trace
from pmai_evals.trace.schemas import TraceStatus


def test_parse_trace_basic(sample_history: list[dict[str, Any]]) -> None:
    trace = parse_trace(sample_history, "test-chat-uid", model="test-model")
    assert trace.chat_id == "test-chat-uid"
    assert trace.model == "test-model"
    assert trace.status == TraceStatus.completed
    assert len(trace.messages) == 4
    assert trace.raw_metadata == {"source": "http"}


def test_parse_trace_extracts_tool_call(sample_history: list[dict[str, Any]]) -> None:
    trace = parse_trace(sample_history, "test-chat-uid")
    assert len(trace.tool_calls) == 1
    call = trace.tool_calls[0]
    assert call.name == "pmview_load"
    assert call.arguments == {"identifier": "1CRN"}
    assert call.output == "loaded 1CRN"
    assert call.is_error is False


def test_parse_trace_extracts_final_answer(sample_history: list[dict[str, Any]]) -> None:
    trace = parse_trace(sample_history, "test-chat-uid")
    assert trace.final_answer == "Loaded 1CRN successfully."


def test_parse_trace_usage_is_zero(sample_history: list[dict[str, Any]]) -> None:
    # HTTP endpoint doesn't expose per-message usage — documented limitation.
    trace = parse_trace(sample_history, "test-chat-uid")
    assert trace.usage.input_tokens == 0
    assert trace.usage.output_tokens == 0
    assert trace.metrics.ttft_ms is None
    assert trace.metrics.total_ms == 0


def test_parse_trace_flags_errored_tool() -> None:
    history = [
        {
            "type": "function_call",
            "name": "pmview_load",
            "call_id": "c1",
            "arguments": {},
            "id": "r1",
        },
        {
            "type": "function_call_output",
            "call_id": "c1",
            "output": "boom",
            "is_error": True,
            "id": "r1",
        },
    ]
    trace = parse_trace(history, "cid")
    assert trace.status == TraceStatus.failed
    assert trace.tool_calls[0].is_error is True
    assert trace.tool_calls[0].error == "boom"


def test_parse_trace_empty_history() -> None:
    trace = parse_trace([], "cid")
    assert trace.status == TraceStatus.completed
    assert trace.messages == ()
    assert trace.tool_calls == ()
    assert trace.final_answer == ""


def test_parse_trace_has_tool_call_helper(sample_history: list[dict[str, Any]]) -> None:
    trace = parse_trace(sample_history, "test-chat-uid")
    assert trace.has_tool_call("pmview_load")
    assert not trace.has_tool_call("nonexistent")
