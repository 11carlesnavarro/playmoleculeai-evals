The file `cdk_activities_raw.csv` is in your project workspace, a
raw ChEMBL activity export with ChEMBL's own column names.

Start from the molecules that have exactly one IC50 record for
target `CHEMBL301` (human CDK2) carrying a real potency value,
which means `standard_relation` is exactly `=`, `standard_units` is
`nM` and `standard_value` is not empty, and that have a structure in
the file. Use pIC50 = 9 - log10(IC50 in nM). Then work through these
steps in this order.
  1. Keep only the molecules whose pIC50 is 8.0 or more.
  2. Group what survives by Bemis-Murcko scaffold, computed with
     RDKit `MurckoScaffold.MurckoScaffoldSmiles` from the SMILES in
     the file, ignoring stereochemistry as that function does by
     default. Keep only the groups with 3 members or more.
  3. Take the group with the highest median pIC50. Several groups
     share that median, so break the tie: take the group with the
     most members, and if that still ties, the group whose scaffold
     SMILES comes first in alphabetical order.
  4. From that group take the molecule with the lowest
     `Descriptors.MolWt`, compared after rounding to 3 decimal
     places. If two molecules tie at that precision, take the one
     whose ChEMBL id comes first in alphabetical order. Compare the
     rounded values, not the raw ones: two molecules of the same
     formula can differ in the last bits of the calculation.

Save `choice.csv` to your project workspace with the columns
`n_kept,n_series,best_median_pic50,n_tied_on_median,chosen_scaffold,member_count,chosen_compound,chosen_mw`
and exactly one data row.
  - `n_kept`: molecules that survive step 1.
  - `n_series`: groups that survive step 2.
  - `best_median_pic50`: the median pIC50 of the group from step 3,
    to 3 decimal places.
  - `n_tied_on_median`: how many groups shared that highest median
    before the tie-break.
  - `chosen_scaffold`, `member_count`: the scaffold SMILES of the
    group from step 3 and how many members it has.
  - `chosen_compound`, `chosen_mw`: the ChEMBL id from step 4 and
    its molecular weight to 3 decimal places.
Also give the ChEMBL id of the chosen molecule inside
`<answer></answer>` tags.
