The file `cdk_activities_raw.csv` is in your project workspace, a
raw ChEMBL activity export with ChEMBL's own column names. It holds
records for two targets: `CHEMBL301` is human CDK2 and `CHEMBL308`
is human CDK1.

A record carries a real potency value only when `standard_type` is
`IC50`, `standard_relation` is exactly `=`, `standard_units` is `nM`
and `standard_value` is not empty. Use pIC50 = 9 - log10(IC50 in
nM).

For each target take the molecules that have exactly one such
record for it, so each of them has a single pIC50 per target and
nothing has to be averaged. For every molecule that qualifies on
both targets, compute delta = pIC50(CDK2) - pIC50(CDK1). A positive
delta means the molecule is more potent on CDK2.

Save `selectivity.csv` to your project workspace with the columns
`n_cdk2_once,n_cdk1_once,n_shared,median_delta,n_above_one_log,fraction_above_one_log,most_selective,most_selective_delta`
and exactly one data row.
  - `n_cdk2_once`, `n_cdk1_once`: molecules with exactly one such
    record for CDK2, and for CDK1.
  - `n_shared`: molecules that qualify on both targets.
  - `median_delta`: the median delta, to 3 decimal places.
  - `n_above_one_log`: molecules whose absolute delta is strictly
    greater than 1.0.
  - `fraction_above_one_log`: `n_above_one_log` divided by
    `n_shared`, to 3 decimal places.
  - `most_selective`, `most_selective_delta`: the ChEMBL id with the
    largest delta and that delta, to 3 decimal places.
