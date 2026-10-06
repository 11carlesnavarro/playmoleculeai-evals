"""Mean reward per case: a Harbor job against the old harness runs in the archive.

uv run python scripts/compare_old.py jobs/acellera-noviewer [old run glob, default *_stap-noviewer]
"""

import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

OLD = Path("/fast_shared/users/carles/data/playmoleculeAIdata/evals-archive-2026-10-05/runs")


def cell(values: list[float]) -> str:
    return f"{mean(values):.2f} (n={len(values)})" if values else "-"


def main(job: Path, old_glob: str = "*_stap-noviewer") -> None:
    old, new, errors = defaultdict(list), defaultdict(list), defaultdict(int)
    for g in OLD.glob(f"{old_glob}/*/*/seed-*/grade.json"):
        scores = [a["score"] for a in json.loads(g.read_text())["assertions"]]
        old[g.parts[-4]].append(mean(scores) if scores else 0.0)
    results = sorted(job.glob("*/result.json"))
    if not results:
        sys.exit(f"{job}: no trial results (*/result.json)")
    for r in results:
        result = json.loads(r.read_text())
        case = result["task_name"].split("/")[-1]
        rewards = (result.get("verifier_result") or {}).get("rewards")
        if rewards is None:  # no verifier result: an infra error, not a 0 of the agent
            errors[case] += 1
        else:
            new[case].append(rewards["reward"])
    print(f"{'case':18} {'old':>12} {'new':>12}  errors")
    for case in sorted(new.keys() | errors.keys()):
        o, n = old.get(case, []), new.get(case, [])
        print(f"{case:18} {cell(o):>12} {cell(n):>12}  {errors[case] or ''}")
    both = [c for c in new if c in old]
    if not both:
        return
    print(
        f"\n{len(both)} cases in both: old {mean(mean(old[c]) for c in both):.2f}, "
        f"new {mean(mean(new[c]) for c in both):.2f}; {sum(errors.values())} trials with no reward"
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]), *sys.argv[2:])
