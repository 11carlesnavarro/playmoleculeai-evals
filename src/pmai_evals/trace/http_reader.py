"""Parse an agent trace returned by the HTTP endpoint.

We call ``GET /v3/agent/chat/{chat_uid}?full=true``, which returns the
raw ``messages`` rows. Each row carries a JSON-encoded Responses-API
item under ``item_data`` plus the per-message ``usage`` / ``latency_ms``
/ ``ttft_ms`` / ``tool_latency`` / ``model`` / ``status`` columns the
dashboard reads, so token counts and timings round-trip cleanly into
the trace.

The parser also tolerates the legacy parsed-item shape (no
``item_data`` key) for unit-test fixtures.
"""

from __future__ import annotations

import json
from typing import Any

from pmai_evals._io import parse_json_lenient
from pmai_evals.trace.schemas import (
    Message,
    TimingMetrics,
    TokenUsage,
    ToolCall,
    Trace,
    TraceStatus,
)


def _payload_text(payload: dict[str, Any]) -> str | None:
    for key in ("text", "output_text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value

    content = payload.get("content")
    if isinstance(content, list):
        chunks: list[str] = []
        for chunk in content:
            if not isinstance(chunk, dict):
                continue
            text_value = chunk.get("text") or chunk.get("output_text") or chunk.get("input_text")
            if isinstance(text_value, str):
                chunks.append(text_value)
        if chunks:
            return "\n".join(chunks)
    return None


def _payload_role(payload: dict[str, Any]) -> str:
    role = payload.get("role")
    if isinstance(role, str) and role:
        return role
    payload_type = payload.get("type")
    if payload_type in {"function_call", "reasoning"}:
        return "assistant"
    if payload_type == "function_call_output":
        return "tool"
    return "unknown"


def _unwrap(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = row.get("item_data")
    if not isinstance(raw, str):
        return row, {}
    try:
        item = json.loads(raw)
    except Exception:
        item = {}
    if not isinstance(item, dict):
        item = {}
    if isinstance(row.get("response_id"), str):
        item["id"] = row["response_id"]
    if row.get("created_at") is not None:
        item["created_at"] = row["created_at"]
    if row.get("rating") is not None:
        item["rating"] = row["rating"]
    return item, row


def _add_usage(meta: dict[str, Any], totals: dict[str, int]) -> None:
    raw = meta.get("usage")
    if not isinstance(raw, str) or not raw:
        return
    try:
        usage = json.loads(raw)
    except Exception:
        return
    if not isinstance(usage, dict):
        return
    totals["input_tokens"] += int(usage.get("input_tokens") or 0)
    totals["output_tokens"] += int(usage.get("output_tokens") or 0)
    cached = usage.get("cached_tokens")
    if cached is None:
        details = usage.get("input_tokens_details")
        if isinstance(details, dict):
            cached = details.get("cached_tokens")
    totals["cached_tokens"] += int(cached or 0)
    reasoning = usage.get("reasoning_tokens")
    if reasoning is None:
        details = usage.get("output_tokens_details")
        if isinstance(details, dict):
            reasoning = details.get("reasoning_tokens")
    totals["reasoning_tokens"] += int(reasoning or 0)


def parse_trace(
    history: list[dict[str, Any]],
    chat_id: str,
    *,
    model: str | None = None,
) -> Trace:
    """Transform the HTTP chat-history response into a :class:`Trace`."""

    messages: list[Message] = []
    tool_calls: list[ToolCall] = []
    pending_call_idx: dict[str, int] = {}
    last_assistant_text: str | None = None
    saw_error = False

    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
        "reasoning_tokens": 0,
    }
    total_ms = 0
    ttft_ms: int | None = None
    tool_latency_ms = 0

    for turn_index, row in enumerate(history):
        item, meta = _unwrap(row)

        payload_type = str(item.get("type") or "message")
        role = _payload_role(item)
        text_value = _payload_text(item)
        response_id = str(item.get("id") or "")
        created_at = item.get("created_at")
        msg_model = meta.get("model") if isinstance(meta.get("model"), str) else None
        msg_status = meta.get("status") if isinstance(meta.get("status"), str) else None

        messages.append(
            Message(
                message_id=turn_index,
                response_id=response_id,
                item_index=turn_index,
                role=role,
                type=payload_type,
                text=text_value,
                payload=item,
                model=msg_model or model,
                created_at=str(created_at) if created_at else None,
                status=msg_status,
            )
        )

        _add_usage(meta, usage_totals)
        latency = meta.get("latency_ms")
        if isinstance(latency, (int, float)):
            total_ms += int(latency)
        if ttft_ms is None:
            t = meta.get("ttft_ms")
            if isinstance(t, (int, float)) and t > 0:
                ttft_ms = int(t)
        tool_lat = meta.get("tool_latency")
        if isinstance(tool_lat, (int, float)):
            tool_latency_ms += int(round(tool_lat * 1000))

        if payload_type == "function_call":
            call_id = str(item.get("call_id") or item.get("id") or "")
            arguments_raw = item.get("arguments")
            if isinstance(arguments_raw, dict):
                arguments = arguments_raw
            else:
                parsed_args = parse_json_lenient(arguments_raw)
                arguments = parsed_args if isinstance(parsed_args, dict) else {}
            call = ToolCall(
                call_id=call_id,
                name=str(item.get("name") or ""),
                arguments=arguments,
                output=None,
                error=None,
                latency_ms=None,
                turn_index=turn_index,
            )
            pending_call_idx[call_id] = len(tool_calls)
            tool_calls.append(call)
        elif payload_type == "function_call_output":
            call_id = str(item.get("call_id") or item.get("id") or "")
            output = item.get("output")
            if isinstance(output, (dict, list)):
                output_str = json.dumps(output, default=str)
            elif output is None:
                output_str = None
            else:
                output_str = str(output)
            is_error = bool(item.get("is_error"))
            if is_error:
                saw_error = True
            idx = pending_call_idx.pop(call_id, None)
            if idx is not None:
                existing = tool_calls[idx]
                call_latency = (
                    int(round(tool_lat * 1000))
                    if isinstance(tool_lat, (int, float))
                    else existing.latency_ms
                )
                tool_calls[idx] = ToolCall(
                    call_id=existing.call_id,
                    name=existing.name,
                    arguments=existing.arguments,
                    output=output_str,
                    error=output_str if is_error else None,
                    latency_ms=call_latency,
                    turn_index=existing.turn_index,
                    is_error=is_error,
                )
        elif role == "assistant" and text_value:
            last_assistant_text = text_value

    status = TraceStatus.failed if saw_error else TraceStatus.completed

    return Trace(
        chat_id=chat_id,
        chat_pk=0,
        model=model,
        messages=tuple(messages),
        tool_calls=tuple(tool_calls),
        usage=TokenUsage(**usage_totals),
        metrics=TimingMetrics(
            ttft_ms=ttft_ms, total_ms=total_ms, tool_latency_ms=tool_latency_ms
        ),
        final_answer=last_assistant_text or "",
        status=status,
        project=None,
        user_id=None,
        raw_metadata={"source": "http"},
    )
