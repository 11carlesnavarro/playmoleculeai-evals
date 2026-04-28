"""Programmatic checks for the molecular-visualization eval set.

One function per case-assertion. Expected answers and thresholds are baked
into the function. Re-derive any hardcoded residue list with
development/test_case_1.py if the source PDBs change.
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np

from pmai_evals.errors import AssertionConfigError
from pmai_evals.grading.assertions import PYTHON_CHECK_TYPE
from pmai_evals.runner.artifacts import RunArtifact
from pmai_evals.schemas import AssertionResult


_BLUE = 0x0000FF
_STICK_TYPES = ("ball-and-stick", "licorice", "sticks", "stick")
_RMSD_MAX_A = 5.0

_RESID_CLAUSE_RE = re.compile(
    r"\bresid\s+(.+?)(?=\s+(?:and|or|not)\b|[()]|$)", re.IGNORECASE
)
_RESID_RANGE_RE = re.compile(r"\b(\d+)\s+to\s+(\d+)\b", re.IGNORECASE)
_RESID_INT_RE = re.compile(r"\b\d+\b")


def _result(passed: bool, evidence: str) -> AssertionResult:
    return AssertionResult(
        assertion_type=PYTHON_CHECK_TYPE,
        passed=passed,
        evidence=evidence,
        config={},
    )


def _find_system(state: Any, name: str) -> dict[str, Any] | None:
    """Top-level system whose ``name`` matches case-insensitively."""
    if not isinstance(state, list):
        return None
    needle = name.lower()
    for entry in state:
        if isinstance(entry, dict) and str(entry.get("name", "")).lower() == needle:
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
    raise AssertionConfigError(f"color must be hex string or int, got {type(value).__name__}")


def _extract_resids(selection: str) -> set[int]:
    """Resids in pmview selections.

    Handles ``resid 1 2 3``, ``resid 16 to 17``, parenthesised disjunctions,
    and unions across multiple ``resid`` clauses.
    """
    out: set[int] = set()
    for clause in _RESID_CLAUSE_RE.finditer(selection):
        body = clause.group(1)
        for r in _RESID_RANGE_RE.finditer(body):
            out.update(range(int(r.group(1)), int(r.group(2)) + 1))
        bare = _RESID_RANGE_RE.sub(" ", body)
        for m in _RESID_INT_RE.finditer(bare):
            out.add(int(m.group()))
    return out


def _chain_a_paired_rmsd(mob: Any, ref: Any) -> tuple[float, int]:
    """No-fit paired-CA RMSD on chain A; pairing comes from moleculekit."""
    from moleculekit.tools.sequencestructuralalignment import sequenceStructureAlignment

    _, masks = sequenceStructureAlignment(
        mob, ref,
        molsel="protein and chain A",
        refsel="protein and chain A",
        maxalignments=1,
        nalignfragment=1,
    )
    mob_mask, ref_mask = masks[0]
    mob_ca = np.where((mob.name == "CA") & mob_mask)[0]
    ref_ca = np.where((ref.name == "CA") & ref_mask)[0]
    disp = mob.coords[mob_ca, :, 0] - ref.coords[ref_ca, :, 0]
    return float(np.sqrt((disp ** 2).sum(axis=1).mean())), len(mob_ca)


def _blue_chain_a_stick_resids(state: Any, system_name: str) -> set[int]:
    """Resids in visible blue stick reps that explicitly target chain A."""
    system = _find_system(state, system_name)
    if system is None:
        return set()
    out: set[int] = set()
    for rep in system.get("representations") or []:
        if not rep.get("visibility", True):
            continue
        if not any(s in str(rep.get("type", "")).lower() for s in _STICK_TYPES):
            continue
        sel = str(rep.get("selection", "")).lower()
        if "chain a" not in sel:
            continue
        if _normalize_color(rep.get("color_value")) != _BLUE:
            continue
        out |= _extract_resids(sel)
    return out


_MV5483_DIFF_2V62: set[int] = {
    137, 139, 140, 141, 147, 148, 150, 153, 160, 170, 175, 185, 190, 196,
    198, 201, 203, 204, 205, 207, 208, 209, 211, 219, 223, 227, 231, 233,
    241, 242, 245, 247, 252, 258, 259, 261, 262, 263, 265, 266, 267, 268,
    269, 270, 271, 272, 273, 274, 275, 276, 278, 279, 281, 282, 283, 284,
    285, 286, 290, 291, 292, 293, 294, 295, 296, 297, 299, 301, 305, 307,
    308, 310, 311, 314, 315, 316, 317, 318, 319, 320, 322, 323, 325, 326,
    327, 328, 329, 330,
}
_MV5483_DIFF_3OP5: set[int] = {
    148, 150, 151, 152, 158, 159, 161, 164, 171, 181, 186, 196, 201, 207,
    209, 212, 214, 215, 216, 218, 219, 220, 222, 230, 234, 238, 242, 244,
    252, 253, 256, 258, 263, 269, 270, 272, 273, 274, 276, 277, 278, 279,
    280, 281, 282, 283, 284, 285, 286, 287, 289, 290, 292, 293, 294, 295,
    296, 297, 301, 302, 303, 304, 305, 306, 307, 308, 310, 312, 316, 318,
    319, 321, 322, 325, 326, 327, 328, 329, 330, 331, 333, 334, 336, 337,
    338, 339, 340, 341,
}


def mv5483_alignment(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """VRK2 chain A is within ``_RMSD_MAX_A`` of VRK1 chain A in the agent's export."""
    try:
        ref = artifact.load_system("3OP5")
        mob = artifact.load_system("2V62")
    except KeyError as exc:
        return _result(False, str(exc))
    rmsd, n = _chain_a_paired_rmsd(mob, ref)
    return _result(
        rmsd <= _RMSD_MAX_A,
        f"chain-A paired-CA RMSD = {rmsd:.2f} Å (≤ {_RMSD_MAX_A:.2f} Å, n={n})",
    )


def _diff_summary(observed: set[int], expected: set[int], name: str) -> str:
    return (
        f"{name}: hit={len(observed)}, "
        f"missing={len(expected - observed)}, "
        f"extra={len(observed - expected)}"
    )


def mv5483_diff_residues_highlighted(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """The differing chain-A residues are highlighted in blue ball-and-stick.

    Either the mobile (2V62) or the reference (3OP5) qualifies; the resid set
    must equal the canonical answer exactly.
    """
    state = artifact.viewer_state()
    hits_2v62 = _blue_chain_a_stick_resids(state, "2V62")
    hits_3op5 = _blue_chain_a_stick_resids(state, "3OP5")
    if hits_2v62 == _MV5483_DIFF_2V62:
        return _result(True, f"2V62 exact match ({len(_MV5483_DIFF_2V62)} residues)")
    if hits_3op5 == _MV5483_DIFF_3OP5:
        return _result(True, f"3OP5 exact match ({len(_MV5483_DIFF_3OP5)} residues)")
    return _result(
        False,
        "no exact match — "
        f"{_diff_summary(hits_2v62, _MV5483_DIFF_2V62, '2V62')}; "
        f"{_diff_summary(hits_3op5, _MV5483_DIFF_3OP5, '3OP5')}",
    )
