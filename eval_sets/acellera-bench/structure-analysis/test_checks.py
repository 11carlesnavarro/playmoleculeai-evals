"""Tests for the structure-analysis helpers (no fixtures, no I/O)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from pmai_evals.errors import AssertionConfigError
from pmai_evals.eval_loader import load_eval_set


checks = cast(
    Any,
    load_eval_set("acellera-bench/structure-analysis", root=Path("eval_sets")).checks_module,
)


def test_find_system_case_insensitive() -> None:
    state = [{"name": "3OP5"}, {"name": "2v62"}]
    assert checks._find_system(state, "2V62") is state[1]
    assert checks._find_system(state, "3op5") is state[0]
    assert checks._find_system(state, "missing") is None


def test_find_system_non_list() -> None:
    assert checks._find_system({"systems": []}, "x") is None
    assert checks._find_system(None, "x") is None


def test_normalize_color_variants() -> None:
    assert checks._normalize_color(None) is None
    assert checks._normalize_color("") is None
    assert checks._normalize_color(255) == 255
    assert checks._normalize_color("#0000FF") == 255
    assert checks._normalize_color("0000ff") == 255


def test_normalize_color_invalid() -> None:
    with pytest.raises(AssertionConfigError):
        checks._normalize_color("not-a-color")


def test_chain_residues_filters_by_chain() -> None:
    hits = {("A", 10), ("A", 11), ("B", 10), ("b", 12)}
    assert checks._chain_residues(hits, "A") == {10, 11}
    assert checks._chain_residues(hits, "B") == {10, 12}


def test_two_set_check_pass_and_fail() -> None:
    passed, _ = checks._two_set_check({1, 2, 3}, {1, 2}, {4, 5}, "x")
    assert passed is True
    passed, _ = checks._two_set_check({1, 4}, {1, 2}, {4, 5}, "x")
    assert passed is False


def test_parse_numeric_answer_basic() -> None:
    class Stub:
        def final_answer(self) -> str:
            return "the answer is <answer>1.40</answer> Å"

    assert checks._parse_numeric_answer(cast(Any, Stub())) == 1.40

    class Empty:
        def final_answer(self) -> str:
            return "no tag here"

    assert checks._parse_numeric_answer(cast(Any, Empty())) is None
