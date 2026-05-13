"""Programmatic checks for the structure-analysis eval set.

One function per case-assertion, grouped by case id. Expected values
and tolerances are baked into the function. Re-derive any hardcoded
constants with the matching ``development/test_case_<id>.py`` script
if source data changes.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, TypeVar

import numpy as np

_T = TypeVar("_T")

from pmai_evals.errors import AssertionConfigError
from pmai_evals.grading.assertions import PYTHON_CHECK_TYPE
from pmai_evals.runner.artifacts import RunArtifact
from pmai_evals.schemas import AssertionResult


# ---- shared helpers --------------------------------------------------------

_BLUE = 0x0000FF
_YELLOW = 0xFFFF00
_RED = 0xFF0000
_STICK_TYPES = ("ball-and-stick", "licorice", "sticks", "stick")
_ANSWER_RE = re.compile(
    r"<answer>\s*(-?\d+(?:\.\d+)?)\s*</answer>", re.IGNORECASE
)


def _parse_numeric_answer(artifact: RunArtifact) -> float | None:
    """Extract the float from a ``<answer>X.XX</answer>`` tag, or ``None``."""
    match = _ANSWER_RE.search(artifact.final_answer())
    return float(match.group(1)) if match else None


def _result(passed: bool, evidence: str) -> AssertionResult:
    return AssertionResult(
        assertion_type=PYTHON_CHECK_TYPE,
        passed=passed,
        evidence=evidence,
        config={},
    )


def _find_system(state: Any, name: str) -> dict[str, Any] | None:
    """Top-level system whose stem matches ``name`` case-insensitively."""
    if not isinstance(state, list):
        return None
    needle = Path(name).stem.lower()
    for entry in state:
        if (
            isinstance(entry, dict)
            and Path(str(entry.get("name", ""))).stem.lower() == needle
        ):
            return entry
    return None


def _normalize_color(value: Any) -> int | None:
    """Coerce ``#RRGGBB`` / integer / ``None`` into an int, or ``None``."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip().lstrip("#")
        if not text:
            return None
        try:
            return int(text, 16)
        except ValueError as exc:
            raise AssertionConfigError(f"invalid color {value!r}") from exc
    raise AssertionConfigError(
        f"color must be hex string or int, got {type(value).__name__}"
    )


def _chain_residues(
    hits: set[tuple[str, int]], chain: str = "A"
) -> set[int]:
    """Resids in ``hits`` whose chain matches ``chain`` (case-insensitive)."""
    target = chain.upper()
    return {r for c, r in hits if c.upper() == target}


def _selected_atom_mask(
    viewer_state: Any, viewer_selection: Any, system_name: str, mol: Any
) -> np.ndarray | None:
    """Atom mask of the user's viewer selection on ``system_name``, or ``None``."""
    system = _find_system(viewer_state, system_name)
    if system is None or not isinstance(viewer_selection, dict):
        return None
    mol_id = system.get("moleculeID")
    if not mol_id:
        return None
    sel = viewer_selection.get(mol_id)
    if not sel:
        return None
    try:
        return mol.atomselect(str(sel))
    except RuntimeError:
        return None


def _residues_from_mask(mol: Any, mask: np.ndarray) -> set[tuple[str, int]]:
    return set(zip(mol.chain[mask].tolist(), mol.resid[mask].tolist()))


def _selected_residues(
    viewer_state: Any, viewer_selection: Any, system_name: str, mol: Any
) -> set[tuple[str, int]]:
    """(chain, resid) pairs covered by the user's viewer selection."""
    mask = _selected_atom_mask(viewer_state, viewer_selection, system_name, mol)
    return _residues_from_mask(mol, mask) if mask is not None else set()


def _iter_visible_reps(state: Any, system_name: str) -> Iterator[dict[str, Any]]:
    system = _find_system(state, system_name)
    if system is None:
        return
    for rep in system.get("representations") or []:
        if rep.get("visibility", True) and rep.get("selection"):
            yield rep


def _residues_by_rep(
    state: Any,
    system_name: str,
    mol: Any,
    *,
    types: tuple[str, ...],
    color: int,
) -> set[tuple[str, int]]:
    """Residues covered by visible reps matching any of ``types`` and ``color``."""
    out: set[tuple[str, int]] = set()
    for rep in _iter_visible_reps(state, system_name):
        if not any(s in str(rep.get("type", "")).lower() for s in types):
            continue
        if _normalize_color(rep.get("color_value")) != color:
            continue
        try:
            mask = mol.atomselect(str(rep["selection"]))
        except RuntimeError:
            continue
        out |= _residues_from_mask(mol, mask)
    return out


def _two_set_check(
    hits: set[_T], must_hit: set[_T], must_not: set[_T], name: str,
) -> tuple[bool, str]:
    """Boundary-band check: all must-hit present, none of must-not present."""
    missing = must_hit - hits
    forbidden = hits & must_not
    passed = not missing and not forbidden
    evidence = (
        f"{name}: hit={len(hits)}, "
        f"missing_must_hit={len(missing)}, "
        f"forbidden_hit={len(forbidden)}"
    )
    return passed, evidence


# ---- per-case sections -----------------------------------------------------
# Add one banner-separated section per case as cases are wired up. Constants
# live next to the function that uses them, prefixed with the upper-cased
# case id (e.g. ``_SA1187_*``). Each section names the matching
# ``development/test_case_<id>.py`` script that regenerates its truth.
