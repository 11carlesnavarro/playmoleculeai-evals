The file `cdk_activities_raw.csv` is in your project workspace, a
raw ChEMBL activity export with ChEMBL's own column names.

Work with the molecules that have exactly one IC50 record for
target `CHEMBL301` (human CDK2) carrying a real potency value,
which means `standard_relation` is exactly `=`, `standard_units` is
`nM` and `standard_value` is not empty, and that have a structure in
the file. Use pIC50 = 9 - log10(IC50 in nM).

An unordered pair of those molecules is an activity cliff when both
hold:
  - their Morgan fingerprint Tanimoto similarity is 0.8 or more,
    with radius 2 and 2048 bits, from RDKit
    `rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)`,
  - the absolute difference of their pIC50 values is 2.0 or more.
Consider every unordered pair.

Save `cliffs.csv` to your project workspace with the columns
`n_pairs,chembl_id_1,chembl_id_2,similarity,delta_pic50` and exactly
one data row.
  - `n_pairs`: how many pairs are activity cliffs.
  - The other four columns describe the single pair with the largest
    pIC50 difference: the two ChEMBL ids in either order, their
    Tanimoto similarity and their pIC50 difference as a positive
    number, both to 3 decimal places.
