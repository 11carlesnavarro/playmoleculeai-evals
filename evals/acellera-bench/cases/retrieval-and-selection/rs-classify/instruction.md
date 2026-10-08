For each of these PDB entries find the drug-like ligands: 1AQ1,
1IEP, 1TTR, 2V5Z, 3ERT, 3PBL, 4EY7, 6FSK.

A non-polymer chemical component counts as a drug-like ligand when
all of these hold:
  - it is not water,
  - its formula weight is 250 Da or more,
  - its PDB chemical component identifier is not one of: 1PE, 12P,
    ACT, BME, BMA, CIT, DMS, EDO, EPE, FAD, FMT, GOL, HEM, HEZ,
    IPA, MAN, MES, MPD, NAD, NAG, P6G, PEG, PG4, PGE, SIA, SUC,
    TAR, TRS.

Save `ligand_calls.csv` to your project workspace with the columns
`pdb_id,het_code`, one row per drug-like ligand. If an entry has no
drug-like ligand, write a single row for it with the literal value
`none` in `het_code`. Every one of the eight entries must appear at
least once.
