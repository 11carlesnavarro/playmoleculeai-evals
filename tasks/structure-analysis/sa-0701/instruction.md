In PDB 3ERT, characterise the binding pocket of the bound ligand
(residue name OHT) in chain A. Save to your project workspace:
  - `pocket.csv` (columns `chain,resid,resname`): the chain A
    protein residues within 5 Å of OHT.
  - `metrics.csv`, a single data row with columns
    `center_x,center_y,center_z,res_hydrophobic_fraction,net_formal_charge,closest_resid,closest_dist_A`:
      - the centroid of OHT's heavy atoms, in Å;
      - the fraction of pocket residues that are hydrophobic by
        the Kyte-Doolittle hydropathy index (index > 0);
      - the pocket's net formal charge;
      - the pocket residue closest to OHT (its resid) and that
        minimum residue-to-ligand distance, in Å.
