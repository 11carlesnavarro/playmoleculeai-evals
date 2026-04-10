"""Frozen dataclasses for parsed agent traces.

Frozen dataclasses (not pydantic) because:

- Traces are read-only after construction.
- They flow through pure assertion functions where mutability is a footgun.
- Serialization is centralized in :func:`Trace.to_dict` so we don't need
  pydantic's runtime validation overhead.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class TraceStatus(StrEnum):
    """Status of a parsed trace as observed in the SQLite DB."""

    completed = "completed"
    failed = "failed"
    timed_out = "timed_out"
    unknown = "unknown"


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Sum of token counts across all messages in a chat."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass(frozen=True, slots=True)
class TimingMetrics:
    """Latency snapshot derived from per-message metrics."""

    ttft_ms: int | None = None  # first assistant turn only
    total_ms: int = 0
    tool_latency_ms: int = 0


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One tool invocation within a chat."""

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
    """One row from the ``messages`` table, parsed."""

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
    """A complete chat rollout, ready for assertion grading."""

    chat_id: str
    chat_pk: int
    model: str | None
    messages: tuple[Message, ...]
    tool_calls: tuple[ToolCall, ...]
    usage: TokenUsage
    metrics: TimingMetrics
    final_answer: str
    status: TraceStatus
    project: str | None = None
    user_id: str | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable form for ``trace.json``."""
        return asdict(self)

    # ---- ergonomic accessors --------------------------------------------

    def tool_calls_named(self, name: str) -> tuple[ToolCall, ...]:
        return tuple(call for call in self.tool_calls if call.name == name)

    def has_tool_call(self, name: str) -> bool:
        return any(call.name == name for call in self.tool_calls)
