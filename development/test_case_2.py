"""Derive the canonical active-site residue set for mv-6316.

Active site is defined deterministically by the prompt: every protein residue
with any heavy atom within 6 Å of any heavy atom of FAD or SAH in 6FCX.

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
ligand_idx = np.where(m.atomselect(f"({ligand_sel}) and not hydrogen"))[0]
protein_idx = np.where(m.atomselect("protein and not hydrogen"))[0]

lig_xyz = m.coords[ligand_idx, :, 0]
prot_xyz = m.coords[protein_idx, :, 0]

d2 = np.sum((prot_xyz[:, None, :] - lig_xyz[None, :, :]) ** 2, axis=-1)
near = np.any(d2 <= CUTOFF_A ** 2, axis=1)

near_atoms = protein_idx[near]
chains = sorted({str(m.chain[i]) for i in near_atoms})

per_chain: dict[str, set[int]] = {}
for i in near_atoms:
    per_chain.setdefault(str(m.chain[i]), set()).add(int(m.resid[i]))

print(f"# {PDB} active site = protein residues within {CUTOFF_A} Å of {LIGANDS}")
print(f"# chains with hits: {chains}")
for c in chains:
    rs = sorted(per_chain[c])
    print(f"#   chain {c}: n={len(rs)}")
    print(f"_MV6316_ACTIVE_SITE_{c}: set[int] = {set(rs)}")
