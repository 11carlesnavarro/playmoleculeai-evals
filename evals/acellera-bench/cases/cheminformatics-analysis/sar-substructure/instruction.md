The file `cdk_activities_raw.csv` is in your project workspace, a
raw ChEMBL activity export with ChEMBL's own column names.

Work with the molecules that have exactly one IC50 record for
target `CHEMBL301` (human CDK2) carrying a real potency value,
which means `standard_relation` is exactly `=`, `standard_units` is
`nM` and `standard_value` is not empty. One record and one only, so
every molecule has a single pIC50 and nothing has to be averaged.
A molecule with no structure in the file cannot be used here.
Use pIC50 = 9 - log10(IC50 in nM).

For each of these four groups, given as SMARTS, split those
molecules into the ones whose structure matches the SMARTS at least
once and the ones whose structure does not match, then compare the
two medians. Match each molecule's `canonical_smiles` exactly as the
file writes it, with nothing removed from it:
  - `sulfonamide`: `S(=O)(=O)N`
  - `nitrile`: `C#N`
  - `carboxylic_acid`: `[CX3](=O)[OX2H1]`
  - `halogen`: `[F,Cl,Br,I]`

Save `substructure.csv` to your project workspace with the columns
`group,n_with,median_with,median_without,difference`, one row per
group, using the four group names exactly as written above.
`difference` is `median_with` minus `median_without`. Give the three
pIC50 values in each row to 3 decimal places.
