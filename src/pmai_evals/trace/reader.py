"""Read a chat's full trace from the agent SQLite database.

The schema lives in ``playmoleculeAI/playmoleculeai/apps/agent/models/tables.py``.
We talk to it directly via stdlib :mod:`sqlite3` in read-only URI mode —
two parameterized queries do not need an ORM, and avoiding SQLAlchemy
keeps the engine setup off the per-call hot path.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

from pmai_evals._io import parse_json_lenient
from pmai_evals.errors import TraceNotFoundError, TraceParseError
from pmai_evals.trace.schemas import (
    Message,
    TimingMetrics,
    TokenUsage,
    ToolCall,
    Trace,
    TraceStatus,
)

logger = logging.getLogger(__name__)

_CHAT_QUERY = """
    SELECT id, chat_uid, project, user_id, summary, created_at
    FROM chats
    WHERE chat_uid = ?
    LIMIT 1
"""

_MESSAGES_QUERY = """
    SELECT id, response_id, item_index, item_data, model, usage,
           latency_ms, ttft_ms, tool_latency, status, created_at
    FROM messages
    WHERE chat_id = ?
    ORDER BY id ASC
"""


@lru_cache(maxsize=8)
def _connect(db_path: str) -> sqlite3.Connection:
    """Open one read-only connection per DB and reuse it within the process.

    SQLite connections are cheap but the read-only URI form is not free
    on every call. ``check_same_thread=False`` is safe here because the
    harness only reads — there is no shared cursor state to corrupt.
    """
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _usage_from_payload(raw: Any) -> tuple[int, int, int, int]:
    """Return (input, output, cached, reasoning) tokens from a usage blob."""
    parsed = parse_json_lenient(raw)
    if not isinstance(parsed, dict):
        return 0, 0, 0, 0
    input_tokens = int(parsed.get("input_tokens") or 0)
    output_tokens = int(parsed.get("output_tokens") or 0)
    in_details = parsed.get("input_tokens_details") or {}
    out_details = parsed.get("output_tokens_details") or {}
    cached = int(in_details.get("cached_tokens") or 0) if isinstance(in_details, dict) else 0
    reasoning = (
        int(out_details.get("reasoning_tokens") or 0) if isinstance(out_details, dict) else 0
    )
    return input_tokens, output_tokens, cached, reasoning


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


def _coerce_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def load_trace(chat_id: str, db_path: Path) -> Trace:
    """Load a chat by ``chat_uid`` from the read-only SQLite trace DB.

    ``chat_id`` here is the user-visible chat UID (the hex string the
    frontend exposes), not the auto-increment primary key.
    """

    conn = _connect(str(db_path))
    chat_row = conn.execute(_CHAT_QUERY, (chat_id,)).fetchone()
    if chat_row is None:
        raise TraceNotFoundError(f"no chat with chat_uid={chat_id} in {db_path}")

    chat_pk = int(chat_row["id"])
    message_rows = conn.execute(_MESSAGES_QUERY, (chat_pk,)).fetchall()

    messages: list[Message] = []
    tool_calls: list[ToolCall] = []
    pending_calls: dict[str, ToolCall] = {}

    in_total = out_total = cached_total = reasoning_total = 0
    ttft_ms: int | None = None
    total_ms = 0
    tool_latency_ms = 0
    last_assistant_text: str | None = None
    last_model: str | None = None
    failed_seen = False

    for turn_index, row in enumerate(message_rows):
        payload = parse_json_lenient(row["item_data"])
        if not isinstance(payload, dict):
            raise TraceParseError(f"message id={row['id']} has unparseable item_data")

        payload_type = str(payload.get("type") or "message")
        role = _payload_role(payload)
        text_value = _payload_text(payload)
        message_model = row["model"]
        if message_model:
            last_model = message_model

        messages.append(
            Message(
                message_id=int(row["id"]),
                response_id=str(row["response_id"] or ""),
                item_index=int(row["item_index"] or 0),
                role=role,
                type=payload_type,
                text=text_value,
                payload=payload,
                model=message_model,
                created_at=str(row["created_at"]) if row["created_at"] else None,
                status=row["status"],
            )
        )

        i_tok, o_tok, c_tok, r_tok = _usage_from_payload(row["usage"])
        in_total += i_tok
        out_total += o_tok
        cached_total += c_tok
        reasoning_total += r_tok

        latency = _coerce_int(row["latency_ms"])
        if latency is not None:
            total_ms += latency
        if ttft_ms is None:
            ttft_ms = _coerce_int(row["ttft_ms"])
        tool_latency = row["tool_latency"]
        if tool_latency is not None:
            with contextlib.suppress(TypeError, ValueError):
                tool_latency_ms += int(float(tool_latency) * 1000.0)

        if row["status"] and str(row["status"]).lower() == "error":
            failed_seen = True

        if payload_type == "function_call":
            call_id = str(payload.get("call_id") or payload.get("id") or "")
            arguments_raw = payload.get("arguments")
            if isinstance(arguments_raw, dict):
                arguments = arguments_raw
            else:
                parsed_args = parse_json_lenient(arguments_raw)
                arguments = parsed_args if isinstance(parsed_args, dict) else {}
            call = ToolCall(
                call_id=call_id,
                name=str(payload.get("name") or ""),
                arguments=arguments,
                output=None,
                error=None,
                latency_ms=None,
                turn_index=turn_index,
            )
            pending_calls[call_id] = call
            tool_calls.append(call)
        elif payload_type == "function_call_output":
            call_id = str(payload.get("call_id") or payload.get("id") or "")
            output = payload.get("output")
            if isinstance(output, (dict, list)):
                output_str = json.dumps(output, default=str)
            elif output is None:
                output_str = None
            else:
                output_str = str(output)
            is_error = bool(payload.get("is_error"))
            existing = pending_calls.pop(call_id, None)
            if existing is not None:
                idx = tool_calls.index(existing)
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

    status = TraceStatus.failed if failed_seen else TraceStatus.completed

    return Trace(
        chat_id=chat_id,
        chat_pk=chat_pk,
        model=last_model,
        messages=tuple(messages),
        tool_calls=tuple(tool_calls),
        usage=TokenUsage(
            input_tokens=in_total,
            output_tokens=out_total,
            cached_tokens=cached_total,
            reasoning_tokens=reasoning_total,
        ),
        metrics=TimingMetrics(
            ttft_ms=ttft_ms,
            total_ms=total_ms,
            tool_latency_ms=tool_latency_ms,
        ),
        final_answer=last_assistant_text or "",
        status=status,
        project=str(chat_row["project"]) if chat_row["project"] else None,
        user_id=str(chat_row["user_id"]) if chat_row["user_id"] else None,
        raw_metadata={
            "summary": chat_row["summary"],
            "created_at": str(chat_row["created_at"]) if chat_row["created_at"] else None,
        },
    )
