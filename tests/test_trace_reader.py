"""Unit tests for the SQLite trace reader."""

from __future__ import annotations

from pathlib import Path

import pytest

from pmai_evals.errors import TraceNotFoundError
from pmai_evals.trace import load_trace


def test_load_trace_basic(trace_db: Path) -> None:
    trace = load_trace("test-chat-uid", trace_db)
    assert trace.chat_id == "test-chat-uid"
    assert trace.chat_pk == 1
    assert trace.model == "test-model"
    assert trace.status == "completed"
    # 4 messages: user, function_call, function_call_output, assistant
    assert len(trace.messages) == 4


def test_load_trace_extracts_tool_call(trace_db: Path) -> None:
    trace = load_trace("test-chat-uid", trace_db)
    assert len(trace.tool_calls) == 1
    call = trace.tool_calls[0]
    assert call.name == "pmview_load"
    assert call.arguments == {"identifier": "1CRN"}
    assert call.output == "loaded 1CRN"
    assert call.is_error is False


def test_load_trace_sums_tokens(trace_db: Path) -> None:
    trace = load_trace("test-chat-uid", trace_db)
    assert trace.usage.input_tokens == 110  # 50 + 60
    assert trace.usage.output_tokens == 50   # 20 + 30


def test_load_trace_extracts_final_answer(trace_db: Path) -> None:
    trace = load_trace("test-chat-uid", trace_db)
    assert "1CRN" in trace.final_answer


def test_load_trace_not_found(trace_db: Path) -> None:
    with pytest.raises(TraceNotFoundError):
        load_trace("missing-uid", trace_db)


def test_trace_helpers(trace_db: Path) -> None:
    trace = load_trace("test-chat-uid", trace_db)
    assert trace.has_tool_call("pmview_load")
    assert not trace.has_tool_call("nonexistent")
    assert len(trace.tool_calls_named("pmview_load")) == 1
