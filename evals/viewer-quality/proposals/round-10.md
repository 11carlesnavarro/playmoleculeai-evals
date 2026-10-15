# Round 10

Status: proposed. Your decision 1 from round 9 is still open (below).

## Where we are

Round 9 scored 9.2, the best round. It lost 12 points in 5 cases (`round-9.md`, Result). The camera, focus and state
changes worked. Most lost points are things the agent could see in its own last image (a strand over AQ4, flat sticks
under cartoon, a heme colour close to a chain). Two losses come from things the agent did not know how to do, and one
from a PMView bug. All tests below ran on this host (sidecar, PMView build of round 9).

## Change 1: a file loaded into an empty view is framed

PMView main (commit 08d2a8f) turns Mol*'s camera reset off when it draws an SDF with several entries or trajectory
frames. That is right when you switch entries, but it is also off for the first file in an empty view. The camera stays
where it was and the view is blank. poses had a blank first image in rounds 8 and 9. On this host: `outlig0.sdf`
loaded, 1 representation, camera not moved, blank screenshot. A user who opens such a file sees the same.

The fix goes in the one helper that all these paths use:

```ts
export async function withCameraResetSuppressed(molstar, fn) {
  const canvas3d = molstar.canvas3d;
  if (!canvas3d?.reprCount.value) return fn();   // empty view: Mol* frames the new drawing
  ...
```

Not tested yet: we test it on this host before the run.

## Change 2: three skill lines from measured facts

**Superpose two proteins.** compare spent 211 s (round 8: 241 s) aligning two kinases by hand: its own sequence
alignment, Biopython in the sandbox, sequences pasted by hand (one typo), its own fit. MoleculeKit does it in the
viewer's Python:

```python
mob.align('protein and name CA', refmol=ref, refsel='protein and name CA', mode='structure')  # TM-align, in place
```

On this host (3OP5 onto 2V62): 1.9 s (7.6 s the first time), 304 residues aligned, RMSD 2.1 Å. 12 of the 15 ATP site
residues land within 1 Å of a CA of the other protein (the glycine loop 4 to 7 Å).

**A bond between two representations.** covalent drew the ligand and Cys12 as one representation to keep the S–C
bond, so Cys12 got the ligand colour (1 point, rounds 8 and 9). On this host (6OIM): with two representations the bond
is missing. With `params={'includeParent': True}` on both, the bond shows, each half in the colour of its atom.

```
two reps                 both with includeParent
 SG    C25                SG ── C25
 (S)   (ligand)           yellow│teal
```

Side effects seen: a bond to an atom that nothing draws shows as a short stub (CB to CA), and aromatic rings show as
double bonds instead of dashes.

**Transparent atoms still hide the subject.** The skill lists "draw them thin or transparent" and "cut them away
(clip)" as cures. Both transparent cases failed the "not hidden" line (pocket-1m17 round 9 at 0.66, pocket-1hsg round 8
at 0.18: 4 points each). covalent: `clip=11` left 19 of 41 ligand atoms in sight; a camera turn gave 37 of 41.

```diff
-Leave them out of the representations, draw them thin or transparent, turn the camera, or cut them away (`pmv.settings(clip=...)`).
+A transparent layer still hides it. Leave them out of the representations or turn the camera.
+`pmv.visible(mol, sel)` tells how many atoms of the subject are in sight and which residues cover the others.
```

## Your decision 1: the agent's images show the whole viewport

Today each image to the agent is PMView's crop: 47 of 72 in round 9, 6 of them under half the viewport. New evidence:

- hbonds lost 1 point: its last image was 26% of the viewport, and it said "the ligand takes up a good portion of the
  view". The user saw it small.
- cleanup and covalent measured the subject size against the crop.
- No case where the crop helped. Cost about +2% ($0.004 a run).

Change: one argument in `look()` (PMAI `pmview.py:43`), `{"autocrop": False}`. Saved screenshots keep the crop. I
recommend yes.

## Not now

- A scene report with each image (subject size, share in sight, what covers it): no proof yet that the agent acts on
  it. `pmv.visible` gives part of it and ran in 3 of 15 trials. First see what Change 2 and decision 1 do.
- `pmv.contacts` (contacts as data): 20 calls, 248 s of hand code in 10 cases, but no lost point.
- A colour distance rule (chains heme, 1 point in rounds 8 and 9).
- Small API errors, 1 step each: `len(mol)` (5 trials; MoleculeKit API), "This molecule is not displayed" after
  `hold=True` (1), `get_viewer_state()` in code shows the view before the changes (17 calls).
- Work after the first good view: 48 steps, 503 s, 28% of the cost (cleanup, slide). No tool cause found.

## How we will know

compare: time to the first image and the sticks line. covalent: the colour line. pocket-1m17, pocket-1hsg: the
"not hidden" lines. hbonds: the size line. poses: the first image is not blank.

Before we apply: commit the round 9 state in the four repos. Run: about $0.22.
