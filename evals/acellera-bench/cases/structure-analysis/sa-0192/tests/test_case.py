"""tests/test_case.py of every ported task: one test per old assertion, scored as the old grader did."""

import json
from pathlib import Path

import checks
import pytest

from pmai_evals.legacy import check
from pmai_evals.reward import partial

SPECS = json.loads((Path(__file__).parent / "assertions.json").read_text())


@pytest.mark.parametrize("spec", SPECS, ids=[s["function"] for s in SPECS])
def test_check(spec):
    assert partial(check(checks, spec["function"], **spec["kwargs"])) > 0
