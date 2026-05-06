"""Plan the (case × model × seed) execution matrix."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pmai_evals._io import write_json
from pmai_evals.schemas import CaseSpec, EvalSet, RunConfig


@dataclass(frozen=True, slots=True)
class MatrixEntry:
    case: CaseSpec
    model: str
    seed: int

    @property
    def label(self) -> str:
        return f"{self.case.id}/{self.model}/seed-{self.seed}"


def build_manifest(eval_set: EvalSet, config: RunConfig) -> list[MatrixEntry]:
    """Expand the matrix in deterministic order: model → case → seed.

    Model-major order lets the executor reuse one browser context per
    model and run all that model's cases sequentially without re-authing.
    """
    case_filter = set(config.case_filter or [])
    if case_filter:
        selected = [c for c in eval_set.cases if c.id in case_filter]
        missing = case_filter - {c.id for c in selected}
        if missing:
            raise ValueError(f"unknown case ids in --case filter: {sorted(missing)}")
    else:
        selected = list(eval_set.cases)

    return [
        MatrixEntry(case=case, model=model, seed=seed)
        for model in config.models
        for case in selected
        for seed in range(config.seeds)
    ]


def write_manifest(manifest: list[MatrixEntry], path: Path) -> None:
    write_json(
        path,
        {
            "entries": [
                {"case_id": e.case.id, "model": e.model, "seed": e.seed}
                for e in manifest
            ]
        },
    )
