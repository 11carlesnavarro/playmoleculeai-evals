The file `guanidine_drugs.csv` is in your project workspace, with
the columns `name,chembl_id,smiles`.

For each molecule calculate these descriptors with RDKit, from the
SMILES in the file:
  - `mw`: `Descriptors.MolWt`, to 3 decimal places.
  - `clogp`: `Crippen.MolLogP`, to 3 decimal places.
  - `tpsa`: `Descriptors.TPSA`, to 2 decimal places.
  - `hbd`: `Lipinski.NumHDonors`.
  - `hba`: `Lipinski.NumHAcceptors`.
  - `rotatable_bonds`: `Lipinski.NumRotatableBonds`.

Save `properties.csv` to your project workspace with the columns
`name,mw,clogp,tpsa,hbd,hba,rotatable_bonds`, one row per molecule,
using the names exactly as the input file writes them.
