In PDB 1IEP (Abl kinase in complex with imatinib, ligand residue
name STI), restrict your analysis to chain A. Save two CSVs to
your project workspace:
  - `pocket.csv`: chain A protein residues with any heavy atom
    within 5 Å of any STI heavy atom. Columns
    `chain,resid,resname`, one row per residue.
  - `interactions.csv`: hydrogen bonds and hydrophobic / van der
    Waals contacts between STI and the chain A protein. Columns
    `chain,resid,resname,type` where `type` is one of `hbond` or
    `hydrophobic`. One row per (residue, interaction type) pair.
    A residue that participates in both classes contributes two
    rows.
