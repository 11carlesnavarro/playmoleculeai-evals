The file `cdk_activities_raw.csv` is in your project workspace. It is
a raw ChEMBL activity export, with ChEMBL's own column names.

Tell me what is in it. Save `census.csv` to your project workspace
with the columns
`n_records,n_molecules,n_targets,n_ic50_records,n_ki_records,n_exact_relation,n_not_in_nm,n_missing_value`
and exactly one data row.
  - `n_records`: the number of data rows.
  - `n_molecules`: the number of distinct values of
    `molecule_chembl_id`.
  - `n_targets`: the number of distinct values of
    `target_chembl_id`.
  - `n_ic50_records`, `n_ki_records`: rows whose `standard_type` is
    `IC50` and rows whose `standard_type` is `Ki`.
  - `n_exact_relation`: rows whose `standard_relation` is exactly
    `=`.
  - `n_not_in_nm`: rows whose `standard_units` is anything other
    than `nM`, including rows where it is empty.
  - `n_missing_value`: rows whose `standard_value` is empty.
