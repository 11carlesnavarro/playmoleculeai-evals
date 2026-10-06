For PDB entry 2V5Z, list every non-polymer chemical component that
is not water. Save `ligands.csv` to your project workspace with the
columns `het_code,formula_weight,role`, one row per component.
  - `het_code`: the PDB chemical component identifier.
  - `formula_weight`: the formula weight in daltons as reported by
    the PDB chemical component dictionary.
  - `role`: write `cofactor` for a component that the enzyme uses
    as a redox cofactor, and `inhibitor` for the drug-like molecule
    bound in the active site. Use no other values.
