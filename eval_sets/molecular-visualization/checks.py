"""Programmatic checks for the molecular-visualization eval set.

Functions here are referenced from ``cases.yaml`` via:

    - type: python_check
      function: <function_name>
      kwargs: {...}

The eval loader imports this module under a unique namespace per eval set,
so names can be short — no dotted paths.
"""

from __future__ import annotations

from typing import Any

from pmai_evals.grading.assertions import extract_resids, find_system
from pmai_evals.runner.artifacts import RunArtifact
from pmai_evals.schemas import AssertionResult


def _fail(config: dict[str, Any], evidence: str) -> AssertionResult:
    return AssertionResult(
        assertion_type="python_check",
        passed=False,
        evidence=evidence,
        config=config,
    )

_AA3TO1: dict[str, str] = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "MSE": "M",  # selenomethionine → methionine, common in crystals
}


def _chain_ca_residues(mol: Any, chain: str) -> list[tuple[int, str]]:
    """Return ``[(resid, one_letter), ...]`` for CA atoms of ``chain``.

    Non-standard residues map to ``X`` so they still participate in the
    alignment (as mismatches) instead of being dropped.
    """
    import numpy as np

    mask = mol.atomselect(f"protein and chain {chain} and name CA")
    out: list[tuple[int, str]] = []
    for i in np.where(mask)[0]:
        resid = int(mol.resid[i])
        one = _AA3TO1.get(str(mol.resname[i]).upper(), "X")
        out.append((resid, one))
    return out


def _differing_mobile_resids(
    ref_residues: list[tuple[int, str]],
    mob_residues: list[tuple[int, str]],
) -> set[int]:
    """Return the set of mobile residue numbers whose aligned ref residue
    is a different amino acid.

    Uses biopython's ``PairwiseAligner`` (global, default scoring). Only
    positions inside ``.aligned`` blocks are considered — gaps are not
    counted as "differing".
    """
    from Bio.Align import PairwiseAligner

    ref_seq = "".join(c for _, c in ref_residues)
    mob_seq = "".join(c for _, c in mob_residues)

    aligner = PairwiseAligner()
    aligner.mode = "global"
    alignment = aligner.align(ref_seq, mob_seq)[0]
    ref_blocks, mob_blocks = alignment.aligned

    diffs: set[int] = set()
    for (r_start, r_end), (m_start, m_end) in zip(ref_blocks, mob_blocks):
        for offset in range(r_end - r_start):
            r_i = r_start + offset
            m_i = m_start + offset
            if ref_seq[r_i] != mob_seq[m_i]:
                diffs.add(mob_residues[m_i][0])
    return diffs


def vrk_differing_residues_correct(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """Check that the agent's ball-and-stick selection on the mobile system
    matches the set of residues that truly differ between the two aligned
    kinases, within a Jaccard overlap tolerance.

    Config:
        reference:  logical system name of the reference (e.g. "3OP5")
        mobile:     logical system name of the mobile (e.g. "2V62")
        chain:      chain id to compare in both systems (default "A")
        min_jaccard: minimum Jaccard overlap of agent vs. ground truth
        min_ground_truth: fail early if sequence diff yields fewer than
                    this many residues (prevents pass-by-noise)
    """
    ref_name = config["reference"]
    mob_name = config["mobile"]
    chain = config.get("chain", "A")
    min_jaccard = float(config.get("min_jaccard", 0.5))
    min_ground_truth = int(config.get("min_ground_truth", 20))

    if not artifact.system_files():
        return _fail(config, "no exported systems (systems/ missing)")
    try:
        ref_mol = artifact.load_system(ref_name)
        mob_mol = artifact.load_system(mob_name)
    except KeyError as exc:
        return _fail(config, str(exc))

    ref_residues = _chain_ca_residues(ref_mol, chain)
    mob_residues = _chain_ca_residues(mob_mol, chain)
    if not ref_residues or not mob_residues:
        return _fail(
            config,
            f"empty chain {chain!r} in one system "
            f"(ref={len(ref_residues)}, mob={len(mob_residues)})",
        )

    ground_truth = _differing_mobile_resids(ref_residues, mob_residues)
    if len(ground_truth) < min_ground_truth:
        return _fail(
            config,
            f"ground-truth diff set too small: {len(ground_truth)} residues "
            f"(min {min_ground_truth}); check chain and alignment",
        )

    state = artifact.viewer_state()
    system = find_system(state, mob_name)
    agent_resids: set[int] = set()
    if system is not None:
        for rep in system.get("representations", []) or []:
            rtype = str(rep.get("type", "")).lower()
            if "ball" in rtype or "licorice" in rtype or "stick" in rtype:
                agent_resids |= extract_resids(str(rep.get("selection", "")))
    if not agent_resids:
        return _fail(
            config,
            f"no ball-and-stick selection found on {mob_name!r}",
        )

    intersection = ground_truth & agent_resids
    union = ground_truth | agent_resids
    jaccard = len(intersection) / len(union) if union else 0.0

    evidence = (
        f"jaccard={jaccard:.2f} (threshold {min_jaccard:.2f}); "
        f"ground_truth={len(ground_truth)} agent={len(agent_resids)} "
        f"overlap={len(intersection)}"
    )
    return AssertionResult(
        assertion_type="python_check",
        passed=jaccard >= min_jaccard,
        evidence=evidence,
        config=config,
    )
