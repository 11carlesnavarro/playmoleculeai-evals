Human 1-acyl-sn-glycerol-3-phosphate acyltransferase beta (UniProt
O15120, gene AGPAT2) has no experimental structure. Retrieve its
AlphaFold DB model, version v6, which is the file
`AF-O15120-F1-model_v6.pdb`.

Save `metrics.csv` to your project workspace with the columns
`n_residues,mean_plddt,n_below_70`. Take one pLDDT value per
residue, read from the B-factor column of that residue's CA atom.
  - `n_residues`: the number of residues in the model.
  - `mean_plddt`: the mean of those per-residue values, to 2
    decimal places.
  - `n_below_70`: how many residues have pLDDT below 70.
