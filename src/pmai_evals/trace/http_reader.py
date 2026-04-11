"""Parse an agent trace returned by the HTTP endpoint.

The backend exposes ``GET /v3/agent/chat/{chat_uid}`` which returns the
chat history as a list of Responses-API items (the parsed ``item_data``
blob for each row, with ``id``, ``created_at`` and ``rating`` merged in).
See ``playmoleculeAI/apps/agent/models/messages.py::get_chat_history``.

The HTTP endpoint intentionally does **not** expose the per-message
``usage`` / ``latency`` / ``model`` / ``status`` columns that the SQLite
schema stores separately. Token usage, timing metrics and cost will
therefore be zero in traces produced by this reader — that's a
known limitation, flagged in ``docs/plan.md`` §5.
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
    """Best-effort extraction of human-readable text from a Responses item."""
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


def parse_trace(
    history: list[dict[str, Any]],
    chat_id: str,
    *,
    model: str | None = None,
) -> Trace:
    """Transform the HTTP chat-history response into a :class:`Trace`.

    ``history`` is the JSON list returned by ``GET /v3/agent/chat/{id}``.
    ``model`` is the requested model id from the case (applied uniformly
    to every message, since the HTTP endpoint doesn't expose per-message
    model). Usage and timing fields are zeroed — see module docstring.
    """

    messages: list[Message] = []
    tool_calls: list[ToolCall] = []
    pending_call_idx: dict[str, int] = {}
    last_assistant_text: str | None = None
    saw_error = False

    for turn_index, item in enumerate(history):
        if not isinstance(item, dict):
            continue

        payload_type = str(item.get("type") or "message")
        role = _payload_role(item)
        text_value = _payload_text(item)
        response_id = str(item.get("id") or "")
        created_at = item.get("created_at")

        messages.append(
            Message(
                message_id=turn_index,
                response_id=response_id,
                item_index=turn_index,
                role=role,
                type=payload_type,
                text=text_value,
                payload=item,
                model=model,
                created_at=str(created_at) if created_at else None,
                status=None,
            )
        )

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
                tool_calls[idx] = ToolCall(
                    call_id=existing.call_id,
                    name=existing.name,
                    arguments=existing.arguments,
                    output=output_str,
                    error=output_str if is_error else None,
                    latency_ms=existing.latency_ms,
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
        usage=TokenUsage(),
        metrics=TimingMetrics(),
        final_answer=last_assistant_text or "",
        status=status,
        project=None,
        user_id=None,
        raw_metadata={"source": "http"},
    )
