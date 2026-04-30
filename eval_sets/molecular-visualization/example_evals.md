2. `mv-6860`
Prompt: `4.0 Å and List specific protein–ligand contacts (hydrogen bonds, hydrophobics) and export a 2D interaction map`
Category: interaction analysis
Fixture: `scenario`
Eval mode: `hybrid`
Prerequisites: keep `0AlphaFold2CpunCSP11.pdb` and `betapinene.sdf` loaded in the trace scene.
Why keep: combines geometric filtering, contact typing, and an exportable 2D artifact in one strong eval.
Verification: listed contacts should respect the `4.0 Å` rule and the exported 2D map should match the visible interaction network.

3. `mv-8912`
Prompt: `Please mark the CDR sequences in this Fab`
Category: antibody annotation
Fixture: `scenario`
Eval mode: `hybrid`
Prerequisites: load the Fab PDB from the trace.
Why keep: adds antibody-specific annotation, which is both realistic and meaningfully different from pocket/contact tasks.
Verification: marked residues should match the expected Fab CDR regions.

4. `mv-7584`
Prompt: `Highlight the Fe atom of HEM, the C26 atom of UNK900, and the pseudo-oxo point, and add a local zoomed-in view`
Category: atom-level reactive geometry
Fixture: `scenario`
Eval mode: `hybrid`
Prerequisites: load `heme-BA.pdb` and `pseudo_oxo.pdb`, with HEM Fe, UNK900 C26, and the pseudo-oxo point visible.
Why keep: high-value atom-level visualization task with a local zoomed geometry check.
Verification: the three geometric points should be highlighted correctly and the zoomed inset centered on them.

5. `mv-0254`
Prompt: `load, 5TBY, 5N69, 8EFH, leave only the chains of the myosin ( all the chains representing the myosin) aling all the structures and compute the RMSD for all of them. color each structure with a diferent color`
Category: multi-structure alignment
Fixture: `standalone`
Eval mode: `hybrid`
Prerequisites: none beyond access to the listed PDBs.
Why keep: strong multi-structure alignment/RMSD case with explicit filtering and color separation.
Verification: only myosin chains should remain, each structure should have a different color, and RMSD should be reported for the aligned set.

6. `mv-6568`
Prompt: `Create a phosphatidylcholine/cholesterol membrane with a 1/0.1 ratio`
Category: membrane assembly
Fixture: `standalone`
Eval mode: `quantitative`
Prerequisites: none.
Why keep: distinct non-protein-ligand use case with an exact composition target and clear structural output.
Verification: the resulting membrane should contain phosphatidylcholine and cholesterol at the requested ratio.
