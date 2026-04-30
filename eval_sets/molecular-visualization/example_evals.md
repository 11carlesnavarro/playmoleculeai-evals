2. `mv-0254`
Prompt: `load, 5TBY, 5N69, 8EFH, leave only the chains of the myosin ( all the chains representing the myosin) aling all the structures and compute the RMSD for all of them. color each structure with a diferent color`
Category: multi-structure alignment
Fixture: `standalone`
Eval mode: `hybrid`
Prerequisites: none beyond access to the listed PDBs.
Why keep: strong multi-structure alignment/RMSD case with explicit filtering and color separation.
Verification: only myosin chains should remain, each structure should have a different color, and RMSD should be reported for the aligned set.

3. `mv-6568`
Prompt: `Create a phosphatidylcholine/cholesterol membrane with a 1/0.1 ratio`
Category: membrane assembly
Fixture: `standalone`
Eval mode: `quantitative`
Prerequisites: none.
Why keep: distinct non-protein-ligand use case with an exact composition target and clear structural output.
Verification: the resulting membrane should contain phosphatidylcholine and cholesterol at the requested ratio.
