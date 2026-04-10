"""Plan the (case × model × seed) execution matrix."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pmai_evals._io import write_json
from pmai_evals.schemas import CaseSpec, EvalSet, RunConfig


@dataclass(frozen=True, slots=True)
class MatrixEntry:
    """One unit of work in the run plan."""

    case: CaseSpec
    model: str
    seed: int

    @property
    def label(self) -> str:
        return f"{self.case.id}/{self.model}/seed-{self.seed}"

    def to_dict(self) -> dict[str, str | int]:
        return {"case_id": self.case.id, "model": self.model, "seed": self.seed}


def build_manifest(eval_set: EvalSet, config: RunConfig) -> list[MatrixEntry]:
    """Expand the matrix in deterministic order: model → case → seed.

    Ordering by model first lets the executor reuse one browser context per
    model and run all that model's cases sequentially without re-authing.
    """

    case_filter = set(config.case_filter or [])
    selected_cases: list[CaseSpec]
    if case_filter:
        selected_cases = [c for c in eval_set.cases if c.id in case_filter]
        missing = case_filter - {c.id for c in selected_cases}
        if missing:
            raise ValueError(f"unknown case ids in --case filter: {sorted(missing)}")
    else:
        selected_cases = list(eval_set.cases)

    matrix: list[MatrixEntry] = []
    for model in config.models:
        for case in selected_cases:
            for seed in range(config.seeds):
                matrix.append(MatrixEntry(case=case, model=model, seed=seed))
    return matrix


def write_manifest(manifest: list[MatrixEntry], path: Path) -> None:
    write_json(path, {"entries": [entry.to_dict() for entry in manifest]})
