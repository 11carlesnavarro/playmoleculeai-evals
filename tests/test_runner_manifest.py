"""Unit tests for matrix planning."""

from __future__ import annotations

from pathlib import Path

import pytest

from pmai_evals.runner.manifest import build_manifest, write_manifest
from pmai_evals.schemas import (
    AssertionSpec,
    CaseSpec,
    EvalSet,
    EvalSetSpec,
    RunConfig,
)


def _eval_set(tmp_path: Path) -> EvalSet:
    spec = EvalSetSpec(id="t", skill_under_test="x", description="d")
    cases = [
        CaseSpec(
            id="case-a",
            prompt="p",
            assertions=[AssertionSpec(type="output_contains", value="x")],
        ),
        CaseSpec(
            id="case-b",
            prompt="p",
            assertions=[],
        ),
    ]
    return EvalSet(spec=spec, cases=cases, root=tmp_path)


def _config(**overrides) -> RunConfig:
    base = {
        "eval_set_id": "t",
        "models": ["gpt-5.4", "claude-sonnet-4-6"],
        "seeds": 1,
        "max_cost_usd": 1.0,
        "headless": True,
        "tier": None,
        "case_filter": None,
        "run_label": "test",
        "judge_model": "claude-sonnet-4-6",
    }
    base.update(overrides)
    return RunConfig(**base)


def test_build_manifest_orders_by_model(tmp_path: Path) -> None:
    es = _eval_set(tmp_path)
    cfg = _config()
    manifest = build_manifest(es, cfg)
    assert len(manifest) == 4  # 2 models × 2 cases × 1 seed
    assert manifest[0].model == "gpt-5.4"
    assert manifest[2].model == "claude-sonnet-4-6"


def test_build_manifest_seeds(tmp_path: Path) -> None:
    es = _eval_set(tmp_path)
    cfg = _config(seeds=3)
    manifest = build_manifest(es, cfg)
    assert len(manifest) == 12


def test_build_manifest_case_filter(tmp_path: Path) -> None:
    es = _eval_set(tmp_path)
    cfg = _config(case_filter=["case-a"])
    manifest = build_manifest(es, cfg)
    assert all(entry.case.id == "case-a" for entry in manifest)
    assert len(manifest) == 2


def test_build_manifest_unknown_case(tmp_path: Path) -> None:
    es = _eval_set(tmp_path)
    cfg = _config(case_filter=["nope"])
    with pytest.raises(ValueError):
        build_manifest(es, cfg)


def test_write_manifest(tmp_path: Path) -> None:
    es = _eval_set(tmp_path)
    cfg = _config()
    manifest = build_manifest(es, cfg)
    path = tmp_path / "manifest.json"
    write_manifest(manifest, path)
    assert path.exists()
    assert path.read_text().strip().startswith("{")
