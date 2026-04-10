"""Round-trip the bundled molecular-visualization eval set through the loader."""

from __future__ import annotations

from pathlib import Path

from pmai_evals.eval_loader import load_eval_set


def test_load_molecular_visualization() -> None:
    es = load_eval_set("molecular-visualization", root=Path("eval_sets"))
    assert es.spec.id == "molecular-visualization"
    assert es.spec.skill_under_test == "pmview"
    assert len(es.cases) == 10
    case_ids = [c.id for c in es.cases]
    assert "load-1crn" in case_ids
    assert "align-1crn-1cbn" in case_ids
    # Each case has at least one assertion
    for case in es.cases:
        assert case.assertions, f"case {case.id} has no assertions"
