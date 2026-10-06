Consider every PDB entry that satisfies all of these conditions at
the same time:
  - it contains a polymer entity mapped to UniProt accession
    P00918 (human carbonic anhydrase 2),
  - the experimental method is X-ray diffraction,
  - the resolution is strictly better than 1.00 Å,
  - it was first released on or before 31 December 2025.
From that set choose one structure with this rule: take the lowest
resolution value, and if several entries share that value, take the
one whose PDB id comes first in alphabetical order.

Save `choice.csv` to your project workspace with the columns
`pdb_id,resolution,n_candidates`, where `n_candidates` is how many
entries matched the four conditions. Also give the PDB id you chose
inside `<answer></answer>` tags.
