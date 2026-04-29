"""Tests for the molecular-visualization helpers (no fixtures, no I/O)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from pmai_evals.errors import AssertionConfigError
from pmai_evals.eval_loader import load_eval_set


checks = cast(Any, load_eval_set("molecular-visualization", root=Path("eval_sets")).checks_module)


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
