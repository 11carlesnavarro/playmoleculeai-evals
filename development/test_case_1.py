
from moleculekit.molecule import Molecule


mol1 = Molecule("3OP5")
mol2 = Molecule("2V62")

mol1.filter("chain A")
mol2.filter("chain A")

from moleculekit.tools.sequencestructuralalignment import sequenceStructureAlignment

mol2_aligned, masks = sequenceStructureAlignment(mol2, mol1)
mol2 = mol2_aligned[0]

import numpy as np

mob_mask, ref_mask = masks[0]
mob_ca = np.where((mol2.name == "CA") & mob_mask)[0]
ref_ca = np.where((mol1.name == "CA") & ref_mask)[0]
diffs = [int(mol2.resid[mi]) for mi, ri in zip(mob_ca, ref_ca) if mol2.resname[mi] != mol1.resname[ri]]
print(f"{len(diffs)} differing residues on 2V62 chain A: {diffs}")

