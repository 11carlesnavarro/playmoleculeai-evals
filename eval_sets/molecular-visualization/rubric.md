# Rubric — molecular-visualization

This is the human-readable rubric for the `molecular-visualization` eval set.
The machine-readable version is `rubric.yaml` in this same directory; the
two must agree, but only `rubric.yaml` is loaded by the judge.

## Dimensions

### `correctness` (1–5)

Does the response correctly answer the prompt? Are factual claims (PDB IDs,
residue names, distances, SMILES, RMSD values) accurate to the expected
ground truth or within tolerance? Score `1` for confidently wrong; `5` for
fully correct with no hedging.

### `visualization_quality` (1–5)

Is the viewer state appropriate for the question? Is the camera positioned
to make the relevant structure clearly visible? Are representations and
coloring informative for the asked question? Use the screenshot.

### `communication` (1–5)

Is the final text answer clear, concise, and free of hedging? Does it
directly address the question without unrequested digressions, excessive
disclaimers, or restating the prompt?

## Pass threshold

Mean across enabled dimensions ≥ `3.5`.
