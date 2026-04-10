"""Unit tests for the cost budget."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pmai_evals.errors import BudgetExceededError
from pmai_evals.runner.budget import Budget


def test_budget_charges_and_persists(tmp_path: Path) -> None:
    journal = tmp_path / "cost.json"
    budget = Budget(max_cost_usd=1.0, journal_path=journal)
    charge = budget.charge(
        case_id="c1",
        model="gpt-5.4-nano",
        seed=0,
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    assert charge.cost_usd > 0
    persisted = json.loads(journal.read_text())
    assert persisted["total_cost_usd"] == budget.total_cost_usd
    assert len(persisted["charges"]) == 1


def test_budget_exceeds(tmp_path: Path) -> None:
    journal = tmp_path / "cost.json"
    budget = Budget(max_cost_usd=0.001, journal_path=journal)
    budget.charge(
        case_id="c1",
        model="gpt-5.4-nano",
        seed=0,
        input_tokens=10_000_000,
        output_tokens=10_000_000,
    )
    with pytest.raises(BudgetExceededError):
        budget.check()


def test_budget_remaining(tmp_path: Path) -> None:
    journal = tmp_path / "cost.json"
    budget = Budget(max_cost_usd=10.0, journal_path=journal)
    assert budget.remaining_usd == 10.0


def test_budget_invalid_max(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        Budget(max_cost_usd=0, journal_path=tmp_path / "cost.json")
