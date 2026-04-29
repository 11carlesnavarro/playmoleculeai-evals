"""Derive canonical MUST_HIT / MUST_NOT_HIT residue sets for mv-5483.

A residue is MUST_HIT iff every reasonable alignment scoring pairs it across
3OP5/2V62 and reports a different amino acid. It is MUST_NOT_HIT iff every
scoring pairs it and reports the same amino acid. The remainder is the
ambiguous middle (gapped under some scoring, scoring-dependent residue
identity), excluded from grading.

Re-run when the source PDBs change. Paste the printed sets into
eval_sets/molecular-visualization/checks.py.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
from Bio.Align import PairwiseAligner, substitution_matrices
from Bio.SeqUtils import seq1
from moleculekit.molecule import Molecule


def chain_a(pdb: str) -> tuple[str, list[int]]:
    m = Molecule(pdb)
    m.filter("protein and chain A")
    idx = np.where(m.atomselect("name CA"))[0]
    seq = "".join(seq1(str(m.resname[i])) for i in idx)
    return seq, [int(m.resid[i]) for i in idx]


REF_PDB, MOB_PDB = "3OP5", "2V62"
ref_seq, ref_resid = chain_a(REF_PDB)
mob_seq, mob_resid = chain_a(MOB_PDB)


def per_resid_labels(scoring: "Mapping[str, object]") -> tuple[dict[int, bool], dict[int, bool]]:
    """For each paired position return is-different. Gapped positions are absent."""
    a = PairwiseAligner()
    a.mode = "global"
    for k, v in scoring.items():
        setattr(a, k, v)
    rb, mb = a.align(ref_seq, mob_seq)[0].aligned
    ref_lbl: dict[int, bool] = {}
    mob_lbl: dict[int, bool] = {}
    for (rs, re), (ms, _) in zip(rb, mb):
        for k in range(re - rs):
            differs = ref_seq[rs + k] != mob_seq[ms + k]
            ref_lbl[ref_resid[rs + k]] = differs
            mob_lbl[mob_resid[ms + k]] = differs
    return ref_lbl, mob_lbl


SCORINGS = {
    "default":  {},
    "affine":   {"match_score": 2, "mismatch_score": -1,
                 "open_gap_score": -10, "extend_gap_score": -0.5},
    "blosum62": {"substitution_matrix": substitution_matrices.load("BLOSUM62"),
                 "open_gap_score": -11, "extend_gap_score": -1},
}

per_method = {name: per_resid_labels(s) for name, s in SCORINGS.items()}

for sys_index, sys_name in enumerate((REF_PDB, MOB_PDB)):
    labels = [per_method[m][sys_index] for m in SCORINGS]
    universe = set().union(*labels)
    must_hit = sorted(r for r in universe
                      if all(r in lbl and lbl[r] for lbl in labels))
    must_not = sorted(r for r in universe
                      if all(r in lbl and not lbl[r] for lbl in labels))
    ambiguous = sorted(universe - set(must_hit) - set(must_not))
    print(f"\n# {sys_name} chain A — derived from {list(SCORINGS)}")
    print(f"#   MUST_HIT n={len(must_hit)}  MUST_NOT n={len(must_not)}  ambiguous n={len(ambiguous)}")
    print(f"_MV5483_MUST_HIT_{sys_name}: set[int] = {set(must_hit)}")
    print(f"_MV5483_MUST_NOT_HIT_{sys_name}: set[int] = {set(must_not)}")
