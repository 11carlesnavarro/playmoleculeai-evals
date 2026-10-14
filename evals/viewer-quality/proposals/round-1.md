# Round 1

Status: done. Run `viewer-quality-train-20261009-122438`: 5.9 / 10 (baseline 5.9).

**Evidence (baseline review):** points lost on the camera (subject hidden or off center), key residues not
sticks, sticks and spheres too thick, overlapping labels. The agent's screenshot differed from the final view.

## PMAI (worktree `playmoleculeAI-viewer-quality`)

- `PMView.look()`: viewer state + screenshot after a 1 s wait. `include_screenshot` returns this pair.
- `pmview_screenshot` returns the image, not only the file.
- `pmai run --viewer-id` sends the viewer state and a screenshot with the prompt, as the app does.
- `viewer.md`: the result is the view; look at it and correct it before the answer.

## Skills (pmview only)

Camera section, "Composing a View", the isovalue, the stick size scale in `references/styles.md`.

## Result

Better: pocket-1hsg, pocket-1m17, slide, labels. Worse: compare-vrk, covalent, interface, cleanup.
Causes: sticks 0.8 to 1.45 (the scale was only in `styles.md`), unasked labels, dark palette colours,
hidden subjects (no camera direction in PMView).
