PDB entry 3PBL is described as the human dopamine D3 receptor. Its
single polymer entity is a chimera: part of the modelled chain does
not come from the receptor at all. Work on chain A and save two
files to your project workspace.

`composition.csv`, with the columns
`accession,auth_start,auth_end,uniprot_start,uniprot_end`. Write
one row for each continuous segment of chain A that maps to a
UniProt entry. `auth_start` and `auth_end` must be residue numbers
as they appear in the PDB entry itself. They are not the sequential
position in the sequence, and the numbering in this entry is not
continuous. `uniprot_start` and `uniprot_end` are the matching
positions in that UniProt sequence.

`mutations.csv`, with the columns
`accession,uniprot_resid,wild_type,mutant`. Write one row for every
position where the construct sequence differs from the canonical
UniProt sequence of the segment that position belongs to. Use
one-letter codes, and number the position in the UniProt sequence
of that segment.
