In PDB 3SPU, restrict your analysis to chain A and characterise
the binuclear zinc centre of the metallo-β-lactamase. Save to
your project workspace:
  - `coordination.csv` (columns
    `zinc,chain,resid,resname,atom,distance_A`): for each of the
    two zinc ions, every protein or solvent atom within 2.6 Å of
    it, with its distance to that zinc in Å. Label the two zincs
    consistently in the `zinc` column (`Zn1` / `Zn2`, in any
    order). One row per coordinating atom.
  - `metrics.csv`, one data row, columns
    `zn_zn_dist_A,bridge_resname,bridge_atom`: the distance
    between the two zinc ions in Å, and the residue name and
    atom name of the single atom lying within 2.6 Å of both
    zincs at once; if no atom bridges both, write `none` for
    both fields.
