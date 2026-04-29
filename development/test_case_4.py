"""Derive the canonical lowest-RMSD answer for mv-3830.

The reference is STI (imatinib) from 1IEP chain A:201. The docked poses
live in ``eval_sets/molecular-visualization/fixtures/outlig0.sdf`` (same
compound, 20 conformers in a translated/rotated frame). The metric is
RDKit's symmetry-aware optimally-aligned RMSD via ``GetBestRMS``; the
answer is the minimum across all docked poses.

Re-run after re-docking. Paste the printed value into
eval_sets/molecular-visualization/checks.py.
"""

from __future__ import annotations

from pathlib import Path

from moleculekit.molecule import Molecule
from rdkit import Chem
from rdkit.Chem import rdMolAlign


REPO = Path(__file__).resolve().parent.parent
SDF = REPO / "eval_sets/molecular-visualization/fixtures/outlig0.sdf"


m = Molecule("1IEP")
m.filter("resname STI and chain A and resid 201")
ref_path = "/tmp/sti_ref_mv3830.sdf"
m.write(ref_path)
ref = next(iter(Chem.SDMolSupplier(ref_path, removeHs=True)))

poses = [p for p in Chem.SDMolSupplier(str(SDF), removeHs=True) if p is not None]
rmsds = [rdMolAlign.GetBestRMS(p, ref) for p in poses]
best_idx = min(range(len(rmsds)), key=lambda i: rmsds[i])

print(f"# 1IEP STI vs {SDF.name}: {len(poses)} poses, ref={ref.GetNumAtoms()} heavy atoms")
for i, r in enumerate(rmsds):
    print(f"#   pose {i:2d}: {r:.4f} Å")
print(f"_MV3830_EXPECTED_A: float = {rmsds[best_idx]:.4f}  # lowest, pose {best_idx}")
