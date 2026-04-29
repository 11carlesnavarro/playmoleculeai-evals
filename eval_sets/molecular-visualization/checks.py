"""Programmatic checks for the molecular-visualization eval set.

One function per case-assertion. Expected answers and thresholds are baked
into the function. Re-derive any hardcoded residue list with
development/test_case_1.py if the source PDBs change.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from pmai_evals.errors import AssertionConfigError
from pmai_evals.grading.assertions import PYTHON_CHECK_TYPE
from pmai_evals.runner.artifacts import RunArtifact
from pmai_evals.schemas import AssertionResult


_BLUE = 0x0000FF
_STICK_TYPES = ("ball-and-stick", "licorice", "sticks", "stick")
_RMSD_MAX_A = 5.0

_MV5483_REF, _MV5483_MOB = "3OP5", "2V62"
_MV6316_PDB = "6FCX"


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


def _chain_a_paired_rmsd(mob: Any, ref: Any) -> tuple[float, float, int]:
    """No-fit and Kabsch-optimal paired-CA RMSDs on chain A.

    ``optimal`` is the lower bound set by structural divergence between the
    two proteins, ``agent`` is what the cell actually exported.
    """
    from moleculekit.tools.sequencestructuralalignment import sequenceStructureAlignment
    from moleculekit.util import molRMSD

    mols, masks = sequenceStructureAlignment(
        mob, ref,
        molsel="protein and chain A",
        refsel="protein and chain A",
        maxalignments=1,
        nalignfragment=1,
    )
    mob_mask, ref_mask = masks[0]
    mob_ca = np.where((mob.name == "CA") & mob_mask)[0]
    ref_ca = np.where((ref.name == "CA") & ref_mask)[0]
    return (
        float(molRMSD(mob, ref, mob_ca, ref_ca)),
        float(molRMSD(mols[0], ref, mob_ca, ref_ca)),
        len(mob_ca),
    )


def _blue_stick_residues(state: Any, system_name: str, mol: Any) -> set[tuple[str, int]]:
    """Residues covered by visible blue ball-and-stick reps on ``system_name``.

    Each rep's selection is evaluated against the loaded ``mol`` so any valid
    selection grammar (``resid 1 2 3``, ranges, ``within X of ...``,
    ``same residue as ...``) resolves to the correct residue set.
    """
    system = _find_system(state, system_name)
    if system is None:
        return set()
    out: set[tuple[str, int]] = set()
    for rep in system.get("representations") or []:
        if not rep.get("visibility", True):
            continue
        if not any(s in str(rep.get("type", "")).lower() for s in _STICK_TYPES):
            continue
        if _normalize_color(rep.get("color_value")) != _BLUE:
            continue
        sel = rep.get("selection")
        if not sel:
            continue
        try:
            mask = mol.atomselect(str(sel))
        except Exception:
            continue
        for i in np.where(mask)[0]:
            out.add((str(mol.chain[i]), int(mol.resid[i])))
    return out


# Two-set truth: residues every reasonable alignment scoring agrees on.
# Ambiguous middle is excluded. See development/test_case_1.py.

_MV5483_MUST_HIT_2V62: set[int] = {
    16, 17, 19, 20, 21, 22, 25, 26, 27, 28, 33, 34, 42, 48, 51, 52, 54, 57,
    58, 64, 65, 66, 72, 80, 83, 84, 85, 87, 91, 96, 100, 102, 103, 104, 109,
    110, 111, 112, 114, 120, 122, 124, 126, 132, 133, 134, 136, 137, 139,
    140, 141, 147, 148, 150, 153, 160, 170, 175, 185, 190, 196, 198, 201,
    203, 204, 205, 207, 208, 209, 211, 219, 223, 227, 231, 233, 241, 242,
    245, 247, 252, 258, 259, 261, 262, 263, 265, 266, 267, 268, 271, 272,
    273, 275, 276, 278, 279, 281, 282, 283, 284, 285, 286, 290, 291, 292,
    293, 294, 295, 296, 297, 299, 301, 305, 307, 308, 310, 311, 314, 315,
    316, 317, 318, 319, 320, 322, 323, 325, 326, 327, 328, 329, 330,
}
_MV5483_MUST_NOT_HIT_2V62: set[int] = {
    15, 18, 23, 24, 29, 32, 43, 44, 45, 46, 55, 56, 59, 60, 61, 62, 63, 68,
    69, 70, 71, 73, 74, 75, 76, 77, 78, 79, 81, 82, 86, 88, 89, 90, 95, 97,
    98, 99, 101, 105, 106, 107, 108, 113, 115, 116, 117, 118, 119, 121, 123,
    125, 127, 128, 129, 130, 131, 135, 138, 142, 143, 144, 145, 146, 149,
    151, 152, 154, 155, 156, 157, 158, 159, 161, 162, 163, 164, 165, 166,
    167, 168, 169, 171, 172, 173, 174, 176, 177, 178, 179, 180, 181, 182,
    183, 184, 186, 187, 188, 189, 191, 192, 193, 194, 195, 197, 199, 200,
    202, 206, 210, 212, 213, 214, 215, 216, 217, 218, 220, 221, 222, 224,
    225, 226, 228, 229, 230, 232, 234, 235, 236, 237, 238, 239, 240, 243,
    244, 246, 248, 249, 250, 251, 253, 254, 255, 256, 257, 260, 264, 277,
    280, 287, 288, 289, 298, 300, 302, 303, 304, 306, 309, 312, 313, 321,
    324,
}
_MV5483_MUST_HIT_3OP5: set[int] = {
    24, 25, 27, 28, 29, 30, 33, 34, 35, 36, 58, 59, 67, 68, 75, 76, 82, 90,
    93, 94, 95, 97, 101, 106, 110, 112, 113, 114, 119, 120, 121, 122, 124,
    130, 132, 134, 136, 142, 143, 144, 150, 151, 152, 158, 159, 161, 164,
    171, 181, 186, 196, 201, 207, 209, 212, 214, 215, 216, 218, 219, 220,
    222, 230, 234, 238, 242, 244, 252, 253, 256, 258, 263, 269, 270, 272,
    273, 274, 276, 277, 278, 279, 281, 282, 283, 285, 286, 289, 290, 292,
    293, 294, 295, 296, 297, 301, 302, 303, 304, 305, 306, 307, 308, 310,
    312, 316, 318, 319, 321, 322, 325, 326, 327, 328, 329, 330, 331, 333,
    334, 336, 337, 338, 339, 340, 341,
}
_MV5483_MUST_NOT_HIT_3OP5: set[int] = {
    23, 26, 31, 32, 37, 51, 52, 53, 54, 65, 66, 69, 70, 71, 72, 73, 78, 79,
    80, 81, 83, 84, 85, 86, 87, 88, 89, 91, 92, 96, 98, 99, 100, 105, 107,
    108, 109, 111, 115, 116, 117, 118, 123, 125, 126, 127, 128, 129, 131,
    133, 135, 137, 138, 139, 140, 141, 145, 149, 153, 154, 155, 156, 157,
    160, 162, 163, 165, 166, 167, 168, 169, 170, 172, 173, 174, 175, 176,
    177, 178, 179, 180, 182, 183, 184, 185, 187, 188, 189, 190, 191, 192,
    193, 194, 195, 197, 198, 199, 200, 202, 203, 204, 205, 206, 208, 210,
    211, 213, 217, 221, 223, 224, 225, 226, 227, 228, 229, 231, 232, 233,
    235, 236, 237, 239, 240, 241, 243, 245, 246, 247, 248, 249, 250, 251,
    254, 255, 257, 259, 260, 261, 262, 264, 265, 266, 267, 268, 271, 275,
    288, 291, 298, 299, 300, 309, 311, 313, 314, 315, 317, 320, 323, 324,
    332, 335,
}


def mv5483_alignment(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """VRK2 chain A is within ``_RMSD_MAX_A`` of VRK1 chain A in the agent's export."""
    try:
        ref = artifact.load_system(_MV5483_REF)
        mob = artifact.load_system(_MV5483_MOB)
    except KeyError as exc:
        return _result(False, str(exc))
    agent, optimal, n = _chain_a_paired_rmsd(mob, ref)
    return _result(
        agent <= _RMSD_MAX_A,
        f"chain-A paired-CA RMSD: agent={agent:.2f} Å, optimal={optimal:.2f} Å "
        f"(agent ≤ {_RMSD_MAX_A:.2f} Å, n={n})",
    )


def _two_set_check(
    hits: set[int], must_hit: set[int], must_not: set[int], name: str
) -> tuple[bool, str]:
    missing = must_hit - hits
    forbidden = hits & must_not
    passed = not missing and not forbidden
    evidence = (
        f"{name}: hit={len(hits)}, "
        f"missing_must_hit={len(missing)}, "
        f"forbidden_hit={len(forbidden)}"
    )
    return passed, evidence


def mv5483_diff_residues_highlighted(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """Pass iff blue chain-A sticks satisfy MUST_HIT/MUST_NOT_HIT on either system."""
    state = artifact.viewer_state()
    cases = [
        (_MV5483_MOB, _MV5483_MUST_HIT_2V62, _MV5483_MUST_NOT_HIT_2V62),
        (_MV5483_REF, _MV5483_MUST_HIT_3OP5, _MV5483_MUST_NOT_HIT_3OP5),
    ]
    results = []
    for name, must_hit, must_not in cases:
        try:
            mol = artifact.load_system(name)
        except KeyError:
            results.append((False, f"{name}: not loaded"))
            continue
        chain_a = {r for c, r in _blue_stick_residues(state, name, mol) if c.upper() == "A"}
        results.append(_two_set_check(chain_a, must_hit, must_not, name))
    for passed, evidence in results:
        if passed:
            return _result(True, evidence)
    return _result(False, "; ".join(ev for _, ev in results))


# Deterministic active site: protein residues with any heavy atom within 6 Å
# of SAH heavy atoms in 6FCX. See development/test_case_2.py.

_MV6316_ACTIVE_SITE_A: set[int] = {
    345, 348, 349, 365, 368, 369, 435, 438, 439, 453, 456, 459, 460, 461, 462,
    463, 464, 471, 475, 481, 482, 483, 484, 485, 486, 500, 509, 512, 513, 514,
    560, 572, 573, 702,
}
_MV6316_ACTIVE_SITE_B: set[int] = {
    345, 348, 349, 365, 368, 369, 435, 438, 439, 453, 456, 459, 460, 461, 462,
    463, 464, 471, 475, 481, 482, 483, 484, 485, 486, 500, 509, 513, 514, 559,
    560, 572, 573, 702,
}
def mv6316_active_site_highlighted(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """Pass iff blue stick reps on 6FCX cover exactly chain A's, chain B's,
    or the union active-site residues (within 6 Å of SAH)."""
    try:
        mol = artifact.load_system(_MV6316_PDB)
    except KeyError as exc:
        return _result(False, str(exc))
    hits = _blue_stick_residues(artifact.viewer_state(), _MV6316_PDB, mol)
    pocket_a = {("A", r) for r in _MV6316_ACTIVE_SITE_A}
    pocket_b = {("B", r) for r in _MV6316_ACTIVE_SITE_B}
    valid = {"A": pocket_a, "B": pocket_b, "A∪B": pocket_a | pocket_b}
    for label, expected in valid.items():
        if hits == expected:
            return _result(True, f"exact match against {label} (n={len(expected)})")
    diffs = ", ".join(
        f"{label}: missing={len(expected - hits)} extra={len(hits - expected)}"
        for label, expected in valid.items()
    )
    return _result(False, f"hit={len(hits)}; {diffs}")
