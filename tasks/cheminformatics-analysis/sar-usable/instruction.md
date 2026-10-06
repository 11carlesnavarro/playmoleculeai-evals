The file `cdk_activities_raw.csv` is in your project workspace, a
raw ChEMBL activity export with ChEMBL's own column names.

I care only about the IC50 records for target `CHEMBL301`, which is
human CDK2. Before I use this data I need to know how much of it
carries a real potency value. A record carries one only when
`standard_relation` is exactly `=`, `standard_units` is `nM` and
`standard_value` is not empty.

Save `usable.csv` to your project workspace with the columns
`n_molecules_any_record,n_molecules_with_value,n_molecules_without_value,n_molecules_potent,n_flagged_records,largest_flagged_nm`
and exactly one data row. The first four columns count distinct
molecules, not records.
  - `n_molecules_any_record`: molecules with at least one CDK2 IC50
    record of any kind.
  - `n_molecules_with_value`: molecules with at least one record
    that carries a real potency value.
  - `n_molecules_without_value`: molecules with no such record.
  - `n_molecules_potent`: molecules with at least one such record
    whose value is strictly below 100 nM.
  - `n_flagged_records`: CDK2 IC50 records whose
    `data_validity_comment` is not empty.
  - `largest_flagged_nm`: among those flagged records, the largest
    value that carries a real potency value, in nM.
