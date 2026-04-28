"""Tests for the molecular-visualization helpers (no fixtures, no I/O)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from pmai_evals.errors import AssertionConfigError
from pmai_evals.eval_loader import load_eval_set


checks = cast(Any, load_eval_set("molecular-visualization", root=Path("eval_sets")).checks_module)


# --- _extract_resids -----------------------------------------------------

def test_extract_resids_space_separated() -> None:
    assert checks._extract_resids("resid 5 10 15") == {5, 10, 15}


def test_extract_resids_with_neighbours() -> None:
    sel = "protein and chain A and resid 16 17 19 20 and noh"
    assert checks._extract_resids(sel) == {16, 17, 19, 20}


def test_extract_resids_multiple_clauses() -> None:
    sel = "resid 1 2 3 and chain A or resid 100 101"
    assert checks._extract_resids(sel) == {1, 2, 3, 100, 101}


def test_extract_resids_range_syntax() -> None:
    sel = "protein and chain A and (resid 16 to 19 or resid 25 to 27 or resid 42)"
    assert checks._extract_resids(sel) == {16, 17, 18, 19, 25, 26, 27, 42}


def test_extract_resids_no_resid() -> None:
    assert checks._extract_resids("protein and chain A") == set()


# --- _find_system --------------------------------------------------------

def test_find_system_case_insensitive() -> None:
    state = [{"name": "3OP5"}, {"name": "2v62"}]
    assert checks._find_system(state, "2V62") is state[1]
    assert checks._find_system(state, "3op5") is state[0]
    assert checks._find_system(state, "missing") is None


def test_find_system_non_list() -> None:
    assert checks._find_system({"systems": []}, "x") is None
    assert checks._find_system(None, "x") is None


# --- _normalize_color ----------------------------------------------------

def test_normalize_color_variants() -> None:
    assert checks._normalize_color(None) is None
    assert checks._normalize_color("") is None
    assert checks._normalize_color(255) == 255
    assert checks._normalize_color("#0000FF") == 255
    assert checks._normalize_color("0000ff") == 255
    assert checks._normalize_color("#BDBDBD") == 0xBDBDBD


def test_normalize_color_invalid() -> None:
    with pytest.raises(AssertionConfigError):
        checks._normalize_color("not-a-color")
    with pytest.raises(AssertionConfigError):
        checks._normalize_color(3.14)  # type: ignore[arg-type]
