"""Top-level pydantic models shared across layers.

Layer-local types live in the layer's own ``schemas.py`` (e.g.
``trace/schemas.py``); cross-layer types live here.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CaseStatus(StrEnum):
    """Final disposition of a single (case × model × seed) cell."""

    completed = "completed"
    failed = "failed"
    timed_out = "timed_out"
    skipped_over_budget = "skipped_over_budget"
    pending = "pending"


# --- model registry --------------------------------------------------------

class ModelEntry(BaseModel):
    """One row of ``pricing.yaml``."""

    model_config = ConfigDict(extra="forbid")

    id: str
    provider: Literal["openai", "anthropic", "google"]
    tier: Literal["flagship", "cheap"]
    input_per_mtok_usd: float = 0.0
    output_per_mtok_usd: float = 0.0
    cached_input_per_mtok_usd: float = 0.0
    supports_vision: bool = True


class ModelRegistry(BaseModel):
    """Top-level shape of ``pricing.yaml``."""

    model_config = ConfigDict(extra="forbid")

    models: list[ModelEntry]

    def get(self, model_id: str) -> ModelEntry:
        for entry in self.models:
            if entry.id == model_id:
                return entry
        raise KeyError(f"Unknown model id: {model_id}")

    def by_tier(self, tier: Literal["flagship", "cheap", "all"]) -> list[ModelEntry]:
        if tier == "all":
            return list(self.models)
        return [m for m in self.models if m.tier == tier]


# --- eval set / cases ------------------------------------------------------

class AssertionSpec(BaseModel):
    """One assertion declared in ``cases.yaml``."""

    model_config = ConfigDict(extra="allow")

    type: str


class RubricCaseConfig(BaseModel):
    """Per-case rubric override."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    dimensions: list[RubricDimensionSpec] | None = None


class RubricDimensionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    question: str
    scale: tuple[int, int] = (1, 5)


class CaseSpec(BaseModel):
    """One case in ``cases.yaml``. Validated on load."""

    model_config = ConfigDict(extra="forbid")

    id: str
    prompt: str
    difficulty: Literal["trivial", "easy", "medium", "hard"] = "easy"
    tags: list[str] = Field(default_factory=list)
    fixtures: list[str] = Field(default_factory=list)
    timeout_s: int | None = None
    expected_cost_usd: float | None = None
    assertions: list[AssertionSpec] = Field(default_factory=list)
    rubric: RubricCaseConfig = Field(default_factory=RubricCaseConfig)


class EvalSetSpec(BaseModel):
    """``eval_set.yaml`` shape."""

    model_config = ConfigDict(extra="forbid")

    id: str
    skill_under_test: str
    description: str = ""
    difficulty: str = "mixed"
    requires_browser: bool = True
    default_timeout_s: int = 300
    default_expected_cost_usd: float = 0.05
    rubric_path: str | None = None
    tags: list[str] = Field(default_factory=list)


class EvalSet(BaseModel):
    """Loaded eval set: spec + cases + filesystem root."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    spec: EvalSetSpec
    cases: list[CaseSpec]
    root: Path

    def fixture_path(self, name: str) -> Path:
        return self.root / "fixtures" / name


# --- runtime config snapshot ----------------------------------------------

class RunConfig(BaseModel):
    """One CLI invocation's choices, frozen into ``run.json``."""

    model_config = ConfigDict(extra="forbid")

    eval_set_id: str
    models: list[str]
    seeds: int = 1
    max_cost_usd: float
    headless: bool
    tier: Literal["flagship", "cheap", "all"] | None = None
    case_filter: list[str] | None = None
    run_label: str
    judge_model: str


class RunRecord(BaseModel):
    """``run.json`` on disk."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    eval_set: str
    started_at: datetime
    finished_at: datetime | None = None
    git_sha: str | None = None
    config: RunConfig
    environment: dict[str, str] = Field(default_factory=dict)


class CostCharge(BaseModel):
    """Single rollout's cost contribution."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    model: str
    seed: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    cost_usd: float


class CostJournal(BaseModel):
    """``cost.json`` on disk."""

    model_config = ConfigDict(extra="forbid")

    max_cost_usd: float
    total_cost_usd: float = 0.0
    charges: list[CostCharge] = Field(default_factory=list)


class CaseSummary(BaseModel):
    """Per-case summary entry inside ``summary.json``."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    model: str
    seed: int
    status: CaseStatus
    cost_usd: float = 0.0
    artifact_dir: str
    error: str | None = None


class RunSummary(BaseModel):
    """``summary.json`` on disk after a run completes."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    eval_set: str
    started_at: datetime
    finished_at: datetime
    cases: list[CaseSummary]
    total_cost_usd: float
    aborted_over_budget: bool


# --- grading shapes (cross-layer) ----------------------------------------

class AssertionResult(BaseModel):
    """One assertion's verdict."""

    model_config = ConfigDict(extra="forbid")

    assertion_type: str
    passed: bool
    evidence: str
    config: dict[str, Any]


class DimensionScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    score: float
    justification: str
    evidence: str


class RubricGrade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_score: float
    passed: bool
    dimensions: list[DimensionScore]
    evidence: list[str] = Field(default_factory=list)


class CaseGradeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assertions_passed: int
    assertions_total: int
    rubric_passed: bool | None = None


class CaseGrade(BaseModel):
    """``grade.json`` on disk."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    model: str
    seed: int
    assertions: list[AssertionResult]
    rubric: RubricGrade | None = None
    summary: CaseGradeSummary
    judge_model: str | None = None
    judge_error: str | None = None


class PairwiseGrade(BaseModel):
    """LLM judge output for a blind pairwise comparison."""

    model_config = ConfigDict(extra="forbid")

    winner: Literal["A", "B", "tie"]
    justification: str
    evidence: list[str] = Field(default_factory=list)


# Resolve forward refs
RubricCaseConfig.model_rebuild()
