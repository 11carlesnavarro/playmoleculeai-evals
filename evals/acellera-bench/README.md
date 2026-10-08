# acellera-bench

40 cases in 5 sets, ported from the old harness. Code grades them: each case has the old `tests/checks.py` and `tests/assertions.json`, and `pmai_evals.legacy` runs the old check functions unchanged. The port gives the old scores on 480 old trials.

```text
cases/3d-reasoning/               dr-0001 ... dr-0010
cases/cheminformatics-analysis/   sar-*
cases/molecular-visualization/    mv-* (viewer cases: make viewer first)
cases/retrieval-and-selection/    rs-*
cases/structure-analysis/         sa-*
```

## Job files

| File | What | Cost (gpt-6-luna) |
|---|---|---|
| `sample.yaml` | one cheap case from each of 4 sets | less than $0.01 |
| `noviewer.yaml` | the 4 sets without the viewer, once | about $0.60 |
| `viewer.yaml` | mv-1jpz, mv-2ity, mv-7fab with the viewer | less than $0.05 |
| `sa-models.yaml` | phase 3: 3 model and effort arms on structure-analysis (needs `FIREWORKS_API_KEY`) | about $0.50 |
| `skills-ab.yaml` | phase 3: with and without skills on structure-analysis | about $0.35 |

```bash
make run JOB=evals/acellera-bench/sample.yaml
make run JOB=evals/acellera-bench/sample.yaml CASE=structure-analysis/sa-0071   # one case
```

## Status

The results of the runs (phases 2, 3 and 5.7) are in `docs/implementation-plan.md`. Next: the full molecular-visualization set (10 cases). Note: these code checks gave 1.0 to some views that nobody can read (mv-1jpz, mv-2ity, mv-7fab). That is why viewer-quality grades the image.
