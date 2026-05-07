"""Frozen dataclasses for parsed agent traces.

Frozen because traces are read-only after construction and flow through
pure assertion functions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class TraceStatus(StrEnum):
    completed = "completed"
    failed = "failed"
    timed_out = "timed_out"
    unknown = "unknown"


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass(frozen=True, slots=True)
class TimingMetrics:
    ttft_ms: int | None = None
    total_ms: int = 0
    tool_latency_ms: int = 0


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]
    output: str | None
    error: str | None
    latency_ms: int | None
    turn_index: int
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class Message:
    message_id: int
    response_id: str
    item_index: int
    role: str
    type: str
    text: str | None
    payload: dict[str, Any]
    model: str | None
    created_at: str | None
    status: str | None


@dataclass(frozen=True, slots=True)
class Trace:
    chat_id: str
    model: str | None
    messages: tuple[Message, ...]
    tool_calls: tuple[ToolCall, ...]
    usage: TokenUsage
    metrics: TimingMetrics
    final_answer: str
    status: TraceStatus
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def tool_calls_named(self, name: str) -> tuple[ToolCall, ...]:
        return tuple(call for call in self.tool_calls if call.name == name)

    def has_tool_call(self, name: str) -> bool:
        return any(call.name == name for call in self.tool_calls)
