"""LLM-as-judge with vision (Claude Sonnet by default).

Two modes:

- :meth:`LLMJudge.grade_absolute` — score one artifact against a rubric.
- :meth:`LLMJudge.grade_pairwise` — blind comparison of two artifacts.

Judge prompts live in ``grading/prompts/*.md``. JSON output is parsed
defensively — judge errors do not abort the run.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from ruamel.yaml import YAML

from pmai_evals.config import Settings
from pmai_evals.errors import JudgeError
from pmai_evals.pricing import supports_vision
from pmai_evals.runner.artifacts import RunArtifact
from pmai_evals.schemas import (
    DimensionScore,
    PairwiseGrade,
    RubricDimensionSpec,
    RubricGrade,
)

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).parent / "prompts"
RUBRICS_DIR = Path(__file__).parent / "rubrics"

# Re-export for callers that want a stable name. The schema-level type is
# the single source of truth for rubric dimensions.
RubricDimension = RubricDimensionSpec


# --- rubric ---------------------------------------------------------------

class Rubric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimensions: list[RubricDimension] = Field(default_factory=list)
    pass_threshold: float = 3.5


@lru_cache(maxsize=16)
def _load_template(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


@lru_cache(maxsize=16)
def load_rubric(path: Path) -> Rubric:
    """Load a YAML rubric from disk. Markdown paths delegate to a YAML sibling."""
    if path.suffix == ".md":
        sibling = path.with_suffix(".yaml")
        if not sibling.exists():
            raise JudgeError(f"no .yaml sibling for markdown rubric: {path}")
        return load_rubric(sibling)
    if path.suffix not in {".yaml", ".yml"}:
        raise JudgeError(f"unsupported rubric format: {path}")
    yaml = YAML(typ="safe")
    data = yaml.load(path.read_text(encoding="utf-8"))
    return Rubric.model_validate(data)


def default_rubric() -> Rubric:
    return load_rubric(RUBRICS_DIR / "visualization.yaml")


# --- prompt rendering -----------------------------------------------------

def _format_dimensions(rubric: Rubric) -> str:
    lines: list[str] = []
    for dim in rubric.dimensions:
        lo, hi = dim.scale
        lines.append(f"### {dim.name} (scale {lo}–{hi})")
        lines.append(dim.question.strip())
        lines.append("")
    return "\n".join(lines)


def _trace_brief(artifact: RunArtifact, *, max_calls: int = 12) -> str:
    trace = artifact.trace()
    calls = trace.get("tool_calls") or []
    summary: list[str] = []
    for call in calls[:max_calls]:
        name = call.get("name", "?")
        summary.append(f"- {name}({list((call.get('arguments') or {}).keys())})")
    if len(calls) > max_calls:
        summary.append(f"- ... and {len(calls) - max_calls} more")
    return "\n".join(summary) if summary else "(no tool calls)"


def _trace_status(artifact: RunArtifact) -> str:
    trace = artifact.trace()
    return str(trace.get("status") or artifact.status() or "unknown")


def _final_text(artifact: RunArtifact) -> str:
    text = artifact.final_answer()
    if text:
        return text
    return str(artifact.trace().get("final_answer") or "")


def _strip_identifiers(text: str) -> str:
    """Best-effort removal of identifying tokens from a transcript."""
    text = re.sub(r"chat[_-]?id\s*[:=]\s*\S+", "[chat_id]", text, flags=re.IGNORECASE)
    text = re.sub(r"\bclaude\b", "[model]", text, flags=re.IGNORECASE)
    text = re.sub(r"\bgpt-?\d+(?:\.\d+)?(?:-\w+)*", "[model]", text, flags=re.IGNORECASE)
    text = re.sub(r"\bgemini-?\d+(?:\.\d+)?(?:-\w+)*", "[model]", text, flags=re.IGNORECASE)
    return text


def _render_absolute_prompt(
    artifact: RunArtifact,
    rubric: Rubric,
    case_prompt: str,
) -> str:
    return _load_template("judge_absolute.md").format(
        case_prompt=case_prompt,
        final_answer=_final_text(artifact)[:8000],
        tool_calls_brief=_trace_brief(artifact),
        trace_status=_trace_status(artifact),
        dimensions_block=_format_dimensions(rubric),
        pass_threshold=rubric.pass_threshold,
    )


def _render_pairwise_prompt(
    a: RunArtifact,
    b: RunArtifact,
    rubric: Rubric,
    case_prompt: str,
) -> str:
    return _load_template("judge_pairwise.md").format(
        case_prompt=case_prompt,
        final_answer_a=_strip_identifiers(_final_text(a))[:6000],
        final_answer_b=_strip_identifiers(_final_text(b))[:6000],
        tool_calls_a=_trace_brief(a),
        tool_calls_b=_trace_brief(b),
        dimensions_block=_format_dimensions(rubric),
    )


# --- JSON parsing ---------------------------------------------------------

_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model response, defensively."""
    block = _JSON_BLOCK.search(text)
    candidate = block.group(1) if block else text
    candidate = candidate.strip()
    # Try the whole thing first.
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    # Greedy match between the first '{' and the last '}'.
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise JudgeError(f"could not parse judge JSON: {exc}") from exc
    raise JudgeError("judge returned no JSON object")


# --- judge ----------------------------------------------------------------

class LLMJudge:
    """Provider-agnostic judge."""

    def __init__(self, model: str, settings: Settings) -> None:
        self._model = model
        self._settings = settings
        self._supports_vision = supports_vision(model)

    @property
    def model(self) -> str:
        return self._model

    # ---- public API --------------------------------------------------

    async def grade_absolute(
        self,
        artifact: RunArtifact,
        rubric: Rubric,
        *,
        case_prompt: str,
    ) -> RubricGrade:
        prompt = _render_absolute_prompt(artifact, rubric, case_prompt)
        screenshot = artifact.screenshot_bytes() if self._supports_vision else None
        try:
            raw = await self._invoke(prompt, image_bytes=screenshot)
        except Exception as exc:
            raise JudgeError(f"{type(exc).__name__}: {exc}") from exc
        data = _extract_json(raw)
        return self._parse_absolute(data, rubric)

    async def grade_pairwise(
        self,
        a: RunArtifact,
        b: RunArtifact,
        rubric: Rubric,
        *,
        case_prompt: str,
    ) -> PairwiseGrade:
        prompt = _render_pairwise_prompt(a, b, rubric, case_prompt)
        try:
            raw = await self._invoke(prompt, image_bytes=None)
        except Exception as exc:
            raise JudgeError(f"{type(exc).__name__}: {exc}") from exc
        data = _extract_json(raw)
        winner = data.get("winner", "tie")
        if winner not in {"A", "B", "tie"}:
            winner = "tie"
        return PairwiseGrade(
            winner=winner,
            justification=str(data.get("justification") or ""),
            evidence=[str(e) for e in (data.get("evidence") or [])],
        )

    # ---- parsing -----------------------------------------------------

    def _parse_absolute(self, data: dict[str, Any], rubric: Rubric) -> RubricGrade:
        dims_raw = data.get("dimensions") or []
        dims: list[DimensionScore] = []
        for dim in dims_raw:
            try:
                dims.append(
                    DimensionScore(
                        name=str(dim.get("name") or "?"),
                        score=float(dim.get("score") or 0),
                        justification=str(dim.get("justification") or ""),
                        evidence=str(dim.get("evidence") or ""),
                    )
                )
            except (TypeError, ValueError):
                continue
        if dims:
            overall = sum(d.score for d in dims) / len(dims)
        else:
            overall = float(data.get("overall_score") or 0)
        passed = bool(data.get("passed", overall >= rubric.pass_threshold))
        return RubricGrade(
            overall_score=round(overall, 3),
            passed=passed,
            dimensions=dims,
            evidence=[str(e) for e in (data.get("evidence") or [])],
        )

    # ---- provider routing -------------------------------------------

    async def _invoke(self, prompt: str, *, image_bytes: bytes | None) -> str:
        if self._model.startswith("claude"):
            return await self._invoke_anthropic(prompt, image_bytes)
        if self._model.startswith("gpt"):
            return await self._invoke_openai(prompt, image_bytes)
        if self._model.startswith("gemini"):
            return await self._invoke_gemini(prompt, image_bytes)
        raise JudgeError(f"unknown judge model family: {self._model}")

    async def _invoke_anthropic(self, prompt: str, image_bytes: bytes | None) -> str:
        if not self._settings.anthropic_api_key:
            raise JudgeError("ANTHROPIC_API_KEY missing in .env")
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=self._settings.anthropic_api_key)
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if image_bytes is not None:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": base64.b64encode(image_bytes).decode("ascii"),
                    },
                }
            )
        message = await client.messages.create(
            model=self._model,
            max_tokens=2048,
            messages=[{"role": "user", "content": content}],
        )
        # Concatenate text blocks.
        chunks: list[str] = []
        for block in message.content:
            if getattr(block, "type", None) == "text":
                chunks.append(block.text)  # type: ignore[attr-defined]
        return "\n".join(chunks)

    async def _invoke_openai(self, prompt: str, image_bytes: bytes | None) -> str:
        if not self._settings.openai_api_key:
            raise JudgeError("OPENAI_API_KEY missing in .env")
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self._settings.openai_api_key)
        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        if image_bytes is not None:
            uri = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
            content.append({"type": "input_image", "image_url": uri})
        response = await client.responses.create(
            model=self._model,
            input=[{"role": "user", "content": content}],
            max_output_tokens=2048,
        )
        return response.output_text or ""

    async def _invoke_gemini(self, prompt: str, image_bytes: bytes | None) -> str:
        if not self._settings.gemini_api_key:
            raise JudgeError("GEMINI_API_KEY missing in .env")
        # google-genai is sync; wrap in a thread.
        import asyncio

        from google import genai
        from google.genai import types

        def _call() -> str:
            client = genai.Client(api_key=self._settings.gemini_api_key)
            parts: list[Any] = [types.Part.from_text(text=prompt)]
            if image_bytes is not None:
                parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/png"))
            response = client.models.generate_content(
                model=self._model,
                contents=parts,
            )
            return response.text or ""

        return await asyncio.to_thread(_call)
