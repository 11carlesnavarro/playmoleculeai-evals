The file `cdk_activities_raw.csv` is in your project workspace, a
raw ChEMBL activity export with ChEMBL's own column names.

Work with the molecules that have exactly one IC50 record for
target `CHEMBL301` (human CDK2) carrying a real potency value,
which means `standard_relation` is exactly `=`, `standard_units` is
`nM` and `standard_value` is not empty. Use
pIC50 = 9 - log10(IC50 in nM).

Compute the Bemis-Murcko scaffold of every one of those molecules
with RDKit `MurckoScaffold.MurckoScaffoldSmiles`, from the SMILES in
the file, and group them by that scaffold. Ignore stereochemistry,
which is what that function does by default, so two stereoisomers of
one skeleton count as one scaffold. Call a group with 5 members or
more a series.

Save `series.csv` to your project workspace with the columns
`n_molecules,n_without_structure,n_distinct_scaffolds,n_series,best_scaffold,best_count,best_median_pic50,largest_scaffold,largest_count`
and exactly one data row.
  - `n_molecules`: how many molecules you could compute a scaffold
    for.
  - `n_without_structure`: how many molecules you had to leave out
    because the file gives them no structure.
  - `n_distinct_scaffolds`: how many distinct scaffolds those
    molecules have.
  - `n_series`: how many of those groups are series.
  - `best_scaffold`, `best_count`, `best_median_pic50`: the series
    with the highest median pIC50, how many members it has, and
    that median to 3 decimal places.
  - `largest_scaffold`, `largest_count`: the scaffold with the most
    molecules, and how many it has.
