"""Unit tests for ``pmai_evals.trace.http_reader.parse_trace``."""

from __future__ import annotations

import json
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


def _row(item: dict[str, Any], **meta: Any) -> dict[str, Any]:
    return {
        "item_data": json.dumps(item),
        "response_id": item.get("id", "resp"),
        **meta,
    }


def test_parse_trace_full_rows_extract_usage_and_timing() -> None:
    history = [
        _row(
            {"type": "message", "role": "user", "text": "hi", "id": "r-1"},
            model="gpt-x",
            ttft_ms=420,
            latency_ms=900,
        ),
        _row(
            {
                "type": "function_call",
                "name": "pmview_load",
                "call_id": "c-1",
                "arguments": {"identifier": "1CRN"},
                "id": "r-2",
            },
        ),
        _row(
            {
                "type": "function_call_output",
                "call_id": "c-1",
                "output": "ok",
                "is_error": False,
                "id": "r-3",
            },
            tool_latency=0.250,
        ),
        _row(
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "done"}],
                "id": "r-4",
            },
            model="gpt-x",
            latency_ms=1500,
            usage=json.dumps(
                {
                    "input_tokens": 1200,
                    "output_tokens": 300,
                    "input_tokens_details": {"cached_tokens": 800},
                    "output_tokens_details": {"reasoning_tokens": 50},
                }
            ),
            status="completed",
        ),
    ]
    trace = parse_trace(history, "cid", model="gpt-x")
    assert trace.usage.input_tokens == 1200
    assert trace.usage.output_tokens == 300
    assert trace.usage.cached_tokens == 800
    assert trace.usage.reasoning_tokens == 50
    assert trace.metrics.ttft_ms == 420
    assert trace.metrics.total_ms == 2400  # 900 + 1500
    assert trace.metrics.tool_latency_ms == 250
    assert trace.tool_calls[0].latency_ms == 250
    assert trace.final_answer == "done"
