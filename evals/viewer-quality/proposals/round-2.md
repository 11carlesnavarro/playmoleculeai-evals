# Round 2

Status: done. Run `viewer-quality-train-20261009-143543`: 7.0 / 10 (7.5 without vq-deepsite-7y5k, stopped by
an OpenAI bio flag).

**Evidence (round 1 traces):** the docstring says size 1 is normal (sticks draw at 0.15); 7 errors from mask
selections; 5 from `label_fields` strings; 4 failed `import palette` in the viewer; the blank line rule is
not needed (the viewer parses the whole code with `ast`).

## Change: rewrite of the pmview skill

| File | Before | After |
|---|---|---|
| `SKILL.md` | 139 lines | 72: model, call table, selections, camera, "A good view" |
| `references/representations.md` | (`styles.md`, 52) | sizes, colours, labels as they draw here |
| `references/volumes.md` | in `SKILL.md` | the isosurface |
| `references/selection.md` | 118 lines | 33 |

Removed: coding guidelines, "do not set X unless the user asks", the palette skill link, `styles.md`.

## Result

Better: pocket-1hsg 6 → 10, pocket-1m17 6 → 10, cleanup 7 → 10, compare-vrk 1 → 6, covalent 3 → 6,
poses 5 → 7. Worse: hbonds 8 → 6. Still wrong: big sticks and spheres (6 views), unasked labels, camera.
