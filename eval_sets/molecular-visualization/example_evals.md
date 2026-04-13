1. `mv-3830`
Prompt: `Display the 1IEP complex and compute the RMSD of the docked ligand relative to the experimental structure`
Category: docking validation
Fixture: `scenario`
Eval mode: `quantitative`
Prerequisites: load experimental `1IEP` and the uploaded docked pose from `output (1).pdbqt`.
Why keep: strongest direct pose-validation task in the pool, with a numeric target and a visible overlay.
Verification: computed ligand RMSD should match the docked-vs-experimental overlay within tolerance.

2. `mv-5483`
Prompt: `show the VRK2 structure , aligned to the VRK1 and with residues that differs in ball and stick color in blue`
Category: comparative structure alignment
Fixture: `scenario`
Eval mode: `hybrid`
Prerequisites: load the VRK1 and VRK2 structures from the `servier` trace context.
Why keep: clean alignment-plus-difference-highlighting task that broadens coverage beyond ligand-pocket work.
Verification: VRK2 should be superposed onto VRK1 and differing residues should appear in blue ball-and-stick.

3. `mv-8144`
Prompt: `so take in consideration of mettk3-mettl14 complex pdb id 5il1 so first find interface residue of mettl3 and mettl14`
Category: protein-protein interface analysis
Fixture: `standalone`
Eval mode: `quantitative`
Prerequisites: none beyond access to `5IL1`.
Why keep: realistic residue-level interface task with a crisp structural answer.
Verification: reported METTL3 and METTL14 interface residues should match inter-chain contact geometry in `5IL1`.

4. `mv-6860`
Prompt: `4.0 Å and List specific protein–ligand contacts (hydrogen bonds, hydrophobics) and export a 2D interaction map`
Category: interaction analysis
Fixture: `scenario`
Eval mode: `hybrid`
Prerequisites: keep `0AlphaFold2CpunCSP11.pdb` and `betapinene.sdf` loaded in the trace scene.
Why keep: combines geometric filtering, contact typing, and an exportable 2D artifact in one strong eval.
Verification: listed contacts should respect the `4.0 Å` rule and the exported 2D map should match the visible interaction network.

5. `mv-6316`
Prompt: `please load 6fcx and highlight the active site`
Category: active-site visualization
Fixture: `standalone`
Eval mode: `quantitative`
Prerequisites: none beyond access to `6FCX`.
Why keep: simple but durable baseline for load + site highlighting on a real enzyme.
Verification: the active site around `FAD`/`SAH` should be highlighted and centered consistently.

6. `mv-5499`
Prompt: `Measure the distance betweent the sulfur atoms of A:V161C, B:V161C`
Category: geometric measurement
Fixture: `scenario`
Eval mode: `quantitative`
Prerequisites: load the `8AYF` mutant dimer with the `V161C` sidechains visible on chains `A` and `B`.
Why keep: strongest pure measurement prompt in the set, with a single unambiguous numeric answer.
Verification: the reported sulfur-sulfur distance should match the structure coordinates.

7. `mv-8912`
Prompt: `Please mark the CDR sequences in this Fab`
Category: antibody annotation
Fixture: `scenario`
Eval mode: `hybrid`
Prerequisites: load the Fab PDB from the trace.
Why keep: adds antibody-specific annotation, which is both realistic and meaningfully different from pocket/contact tasks.
Verification: marked residues should match the expected Fab CDR regions.

8. `mv-7584`
Prompt: `Highlight the Fe atom of HEM, the C26 atom of UNK900, and the pseudo-oxo point, and add a local zoomed-in view`
Category: atom-level reactive geometry
Fixture: `scenario`
Eval mode: `hybrid`
Prerequisites: load `heme-BA.pdb` and `pseudo_oxo.pdb`, with HEM Fe, UNK900 C26, and the pseudo-oxo point visible.
Why keep: high-value atom-level visualization task with a local zoomed geometry check.
Verification: the three geometric points should be highlighted correctly and the zoomed inset centered on them.

9. `mv-0254`
Prompt: `load, 5TBY, 5N69, 8EFH, leave only the chains of the myosin ( all the chains representing the myosin) aling all the structures and compute the RMSD for all of them. color each structure with a diferent color`
Category: multi-structure alignment
Fixture: `standalone`
Eval mode: `hybrid`
Prerequisites: none beyond access to the listed PDBs.
Why keep: strong multi-structure alignment/RMSD case with explicit filtering and color separation.
Verification: only myosin chains should remain, each structure should have a different color, and RMSD should be reported for the aligned set.

10. `mv-6568`
Prompt: `Create a phosphatidylcholine/cholesterol membrane with a 1/0.1 ratio`
Category: membrane assembly
Fixture: `standalone`
Eval mode: `quantitative`
Prerequisites: none.
Why keep: distinct non-protein-ligand use case with an exact composition target and clear structural output.
Verification: the resulting membrane should contain phosphatidylcholine and cholesterol at the requested ratio.
