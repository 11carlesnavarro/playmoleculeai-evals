"""Derive the canonical active-site residue set for mv-6316.

Active site is defined deterministically by the prompt: every protein residue
with any heavy atom within 6 Å of any heavy atom of SAH in 6FCX.

Re-run when the source PDB or cutoff changes. Paste the printed set into
eval_sets/molecular-visualization/checks.py.
"""

from __future__ import annotations

import numpy as np
from moleculekit.molecule import Molecule


PDB = "6FCX"
LIGANDS = ("SAH",)
CUTOFF_A = 6.0


m = Molecule(PDB)
ligand_sel = " or ".join(f"resname {r}" for r in LIGANDS)
selection = (
    f"protein and not hydrogen and same residue as "
    f"within {CUTOFF_A} of (({ligand_sel}) and not hydrogen)"
)
mask = m.atomselect(selection)

per_chain: dict[str, set[int]] = {}
for i in np.where(mask)[0]:
    per_chain.setdefault(str(m.chain[i]), set()).add(int(m.resid[i]))

print(f"# {PDB} active site = protein residues within {CUTOFF_A} Å of {LIGANDS}")
for c in sorted(per_chain):
    rs = per_chain[c]
    print(f"#   chain {c}: n={len(rs)}")
    print(f"_MV6316_ACTIVE_SITE_{c}: set[int] = {rs}")
