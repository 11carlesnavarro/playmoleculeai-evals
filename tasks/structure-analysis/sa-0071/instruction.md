A DeepSite pocket-prediction job has already been run on the
7Y5K complex; its output is in your project workspace
(`7Y5K_prepared.pdb`, `output.csv`, `output.cube`,
`output.pdb`). Take DeepSite's highest-scoring predicted pocket
and characterise it against `7Y5K_prepared.pdb`. Save to your
project workspace:
  - `pocket.csv`, one data row, columns
    `center_x,center_y,center_z,host_chain,interface` where the
    center is DeepSite's predicted pocket center, `host_chain`
    is the protein chain contributing the most atoms within 6 Å
    of that center, and `interface` is `yes` if any other
    protein chain has an atom within 8 Å of the center else
    `no`.
  - `pocket_residues.csv` (columns `chain,resid`): the protein
    residues with any atom within 8 Å of the center.
  - `marker.pdb`: a single atom placed at the pocket center.
