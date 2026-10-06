The files `P24941.fasta` (human CDK2) and `P06493.fasta` (human
CDK1) are in your project workspace. Align the two full sequences
with a global Needleman-Wunsch alignment, using the BLOSUM62
substitution matrix, a gap opening penalty of -11 and a gap
extension penalty of -1. Penalise end gaps exactly like internal
gaps.

Save `identity.csv` to your project workspace with the columns
`alignment_length,identical_positions,percent_identity`.
  - `alignment_length`: the number of columns in the alignment.
  - `identical_positions`: the number of columns where both
    sequences carry the same amino acid.
  - `percent_identity`: 100 × identical_positions ÷
    alignment_length, to 2 decimal places.
