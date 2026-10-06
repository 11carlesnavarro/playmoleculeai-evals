The file `cdk_activities_raw.csv` is in your project workspace, a
raw ChEMBL activity export with ChEMBL's own column names.

Work with the IC50 records for target `CHEMBL301` (human CDK2) that
carry a real potency value, which means `standard_relation` is
exactly `=`, `standard_units` is `nM` and `standard_value` is not
empty. Use pIC50 = 9 - log10(IC50 in nM).

Some molecules were measured many times, and those measurements do
not always agree. For one molecule, call the spread the difference
between the highest and the lowest pIC50 among its own records.

Save `repeats.csv` to your project workspace with the columns
`n_measured_once,n_measured_more_than_once,widest_molecule,widest_spread,widest_record_count`
and exactly one data row.
  - `n_measured_once`: molecules with exactly one such record.
  - `n_measured_more_than_once`: molecules with two or more.
  - `widest_molecule`: the ChEMBL id of the molecule with the
    largest spread.
  - `widest_spread`: that spread in log units, to 3 decimal places.
  - `widest_record_count`: how many such records that molecule has.
