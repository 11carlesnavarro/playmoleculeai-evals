"""Unit tests for the assertion library.

Each assertion has at least one passing case and one failing case.
Hand-crafted artifacts via the ``artifact_with_trace`` fixture.
"""

from __future__ import annotations

import pytest

from pmai_evals.errors import AssertionConfigError
from pmai_evals.grading.assertions import (
    ASSERTION_REGISTRY,
    check_file_content_matches,
    check_file_exists,
    check_no_tool_error,
    check_output_contains,
    check_output_matches_regex,
    check_output_numeric_close,
    check_system_has_representation,
    check_system_representation_residues,
    check_tool_call_count,
    check_tool_call_order,
    check_tool_called,
    check_tool_called_with,
    check_viewer_has_molecule,
    check_viewer_system_count,
    extract_resids,
    find_system,
    normalize_color,
    run_assertions,
)

# --- output --------------------------------------------------------------

def test_output_contains_pass(artifact_with_trace) -> None:
    art = artifact_with_trace(final_answer="The SMILES is Cn1cnc2 ...")
    result = check_output_contains(art, {"value": "Cn1cnc2", "case_sensitive": True})
    assert result.passed
    assert "Cn1cnc2" in result.evidence


def test_output_contains_fail(artifact_with_trace) -> None:
    art = artifact_with_trace(final_answer="Hello world")
    result = check_output_contains(art, {"value": "missing"})
    assert not result.passed


def test_output_matches_regex(artifact_with_trace) -> None:
    art = artifact_with_trace(final_answer="rmsd = 1.234 Å")
    result = check_output_matches_regex(
        art, {"pattern": r"rmsd\s*=\s*\d+\.\d+", "ignore_case": True}
    )
    assert result.passed


def test_output_numeric_close(artifact_with_trace) -> None:
    art = artifact_with_trace(final_answer="The distance is 25.3 Å")
    result = check_output_numeric_close(
        art, {"value": 25.0, "tolerance": 1.0}
    )
    assert result.passed


def test_output_numeric_close_fail(artifact_with_trace) -> None:
    art = artifact_with_trace(final_answer="The distance is 100 Å")
    result = check_output_numeric_close(
        art, {"value": 25.0, "tolerance": 1.0}
    )
    assert not result.passed


# --- tool calls ----------------------------------------------------------

def test_tool_called_pass(artifact_with_trace) -> None:
    art = artifact_with_trace(
        tool_calls=[{"name": "pmview_load", "turn_index": 1, "arguments": {}}]
    )
    assert check_tool_called(art, {"name": "pmview_load"}).passed


def test_tool_called_fail(artifact_with_trace) -> None:
    art = artifact_with_trace(tool_calls=[])
    assert not check_tool_called(art, {"name": "pmview_load"}).passed


def test_tool_called_with(artifact_with_trace) -> None:
    art = artifact_with_trace(
        tool_calls=[
            {
                "name": "pmview_load",
                "turn_index": 1,
                "arguments": {"identifier": "1CRN"},
            }
        ]
    )
    assert check_tool_called_with(
        art,
        {"name": "pmview_load", "arguments": {"identifier": "1CRN"}},
    ).passed
    assert not check_tool_called_with(
        art,
        {"name": "pmview_load", "arguments": {"identifier": "9XYZ"}},
    ).passed


def test_tool_call_count(artifact_with_trace) -> None:
    art = artifact_with_trace(
        tool_calls=[
            {"name": "pmview_load", "turn_index": 1, "arguments": {}},
            {"name": "pmview_load", "turn_index": 2, "arguments": {}},
        ]
    )
    assert check_tool_call_count(
        art, {"name": "pmview_load", "op": ">=", "value": 2}
    ).passed
    assert not check_tool_call_count(
        art, {"name": "pmview_load", "op": "==", "value": 1}
    ).passed


def test_tool_call_order(artifact_with_trace) -> None:
    art = artifact_with_trace(
        tool_calls=[
            {"name": "pmview_load", "turn_index": 1, "arguments": {}},
            {"name": "pmview_align", "turn_index": 2, "arguments": {}},
        ]
    )
    assert check_tool_call_order(
        art, {"order": ["pmview_load", "pmview_align"]}
    ).passed
    assert not check_tool_call_order(
        art, {"order": ["pmview_align", "pmview_load"]}
    ).passed


def test_no_tool_error(artifact_with_trace) -> None:
    good = artifact_with_trace(
        tool_calls=[{"name": "pmview_load", "turn_index": 1, "arguments": {}, "is_error": False}]
    )
    assert check_no_tool_error(good, {}).passed
    bad = artifact_with_trace(
        tool_calls=[
            {
                "name": "pmview_load",
                "turn_index": 1,
                "arguments": {},
                "is_error": True,
                "error": "boom",
            }
        ]
    )
    assert not check_no_tool_error(bad, {}).passed


# --- viewer state --------------------------------------------------------

def test_viewer_has_molecule(artifact_with_trace) -> None:
    art = artifact_with_trace(viewer_state={"systems": [{"name": "1CRN"}]})
    assert check_viewer_has_molecule(art, {"identifier": "1CRN"}).passed
    assert not check_viewer_has_molecule(art, {"identifier": "9XYZ"}).passed


def test_viewer_system_count(artifact_with_trace) -> None:
    art = artifact_with_trace(
        viewer_state={"systems": [{"name": "1CRN"}, {"name": "1CBN"}]}
    )
    assert check_viewer_system_count(art, {"value": 2}).passed
    assert check_viewer_system_count(art, {"value": 1, "op": ">="}).passed
    assert not check_viewer_system_count(art, {"value": 5}).passed


# --- file ----------------------------------------------------------------

def test_file_exists(artifact_with_trace, writer) -> None:
    art = artifact_with_trace()
    (writer.cell_dir / "extra.txt").write_text("hi", encoding="utf-8")
    assert check_file_exists(art, {"name": "extra.txt"}).passed
    assert not check_file_exists(art, {"name": "missing.txt"}).passed


def test_file_content_matches(artifact_with_trace, writer) -> None:
    art = artifact_with_trace()
    (writer.cell_dir / "extra.txt").write_text("RMSD = 1.23", encoding="utf-8")
    assert check_file_content_matches(
        art, {"name": "extra.txt", "pattern": r"RMSD\s*=\s*\d"}
    ).passed


# --- registry ------------------------------------------------------------

def test_registry_lists_all_assertion_types() -> None:
    expected = {
        "output_contains",
        "output_matches_regex",
        "output_numeric_close",
        "tool_called",
        "tool_called_with",
        "tool_call_count",
        "tool_call_order",
        "no_tool_error",
        "viewer_has_molecule",
        "viewer_system_count",
        "file_exists",
        "file_content_matches",
    }
    assert expected.issubset(set(ASSERTION_REGISTRY.keys()))


def test_run_assertions_unknown_type(artifact_with_trace) -> None:
    art = artifact_with_trace()
    with pytest.raises(AssertionConfigError):
        run_assertions(art, [{"type": "nope"}])


def test_run_assertions_missing_type(artifact_with_trace) -> None:
    art = artifact_with_trace()
    with pytest.raises(AssertionConfigError):
        run_assertions(art, [{"value": "x"}])  # type: ignore[list-item]


# --- structural helpers --------------------------------------------------

def testextract_resids_basic() -> None:
    sel = "protein and chain A and resid 16 17 19 20 and noh"
    assert extract_resids(sel) == {16, 17, 19, 20}


def testextract_resids_trailing_eos() -> None:
    assert extract_resids("resid 5 10 15") == {5, 10, 15}


def testextract_resids_multiple_clauses() -> None:
    sel = "resid 1 2 3 and chain A or resid 100 101"
    assert extract_resids(sel) == {1, 2, 3, 100, 101}


def testextract_resids_no_resid() -> None:
    assert extract_resids("protein and chain A") == set()


def testextract_resids_large_realistic() -> None:
    sel = (
        "protein and chain A and resid 16 17 19 20 21 22 25 26 27 28 30 31 "
        "33 34 42 48 49 51 52 54 57 58 64 65 66 72 80 83 84 85 87 91 92 93 "
        "94 96 100 102 103 104 109 110 111 112 114 120 122 124 126 and noh"
    )
    residues = extract_resids(sel)
    assert 16 in residues
    assert 126 in residues
    assert len(residues) > 40


def testfind_system_case_insensitive() -> None:
    state = [{"name": "3OP5", "representations": []}, {"name": "2v62", "representations": []}]
    assert find_system(state, "2V62") is state[1]
    assert find_system(state, "3op5") is state[0]
    assert find_system(state, "nothing") is None


def testfind_system_non_list() -> None:
    assert find_system({"systems": []}, "x") is None
    assert find_system(None, "x") is None


def testnormalize_color_variants() -> None:
    assert normalize_color(None) is None
    assert normalize_color(255) == 255
    assert normalize_color("#0000FF") == 255
    assert normalize_color("0000ff") == 255
    assert normalize_color("#BDBDBD") == 0xBDBDBD


def testnormalize_color_invalid_raises() -> None:
    with pytest.raises(AssertionConfigError):
        normalize_color("not-a-color")
    with pytest.raises(AssertionConfigError):
        normalize_color(3.14)  # type: ignore[arg-type]


# --- structural assertions -----------------------------------------------

_SAMPLE_STATE = [
    {
        "name": "3OP5",
        "representations": [
            {"type": "cartoon", "color_value": 0xBDBDBD, "selection": "protein and chain A"},
        ],
    },
    {
        "name": "2V62",
        "representations": [
            {"type": "cartoon", "color_value": 0xF4B921, "selection": "protein and chain A"},
            {
                "type": "ball-and-stick",
                "color_value": 255,
                "selection": "protein and chain A and resid 16 17 19 20 21 22 and noh",
            },
        ],
    },
]


def test_system_has_representation_blue_ballstick(artifact_with_trace) -> None:
    art = artifact_with_trace(viewer_state=_SAMPLE_STATE)  # type: ignore[arg-type]
    result = check_system_has_representation(
        art,
        {"system": "2V62", "style": "ball-and-stick", "color": "#0000FF"},
    )
    assert result.passed, result.evidence


def test_system_has_representation_wrong_color(artifact_with_trace) -> None:
    art = artifact_with_trace(viewer_state=_SAMPLE_STATE)  # type: ignore[arg-type]
    result = check_system_has_representation(
        art,
        {"system": "2V62", "style": "ball-and-stick", "color": "#FF0000"},
    )
    assert not result.passed
    assert "no representation matched" in result.evidence


def test_system_has_representation_missing_system(artifact_with_trace) -> None:
    art = artifact_with_trace(viewer_state=_SAMPLE_STATE)  # type: ignore[arg-type]
    result = check_system_has_representation(art, {"system": "unknown"})
    assert not result.passed
    assert "not present" in result.evidence


def test_system_representation_residues_min_count(artifact_with_trace) -> None:
    art = artifact_with_trace(viewer_state=_SAMPLE_STATE)  # type: ignore[arg-type]
    result = check_system_representation_residues(
        art,
        {"system": "2V62", "style": "ball-and-stick", "min_count": 5},
    )
    assert result.passed
    # 6 residues in the fixture selection
    assert "6 residues" in result.evidence


def test_system_representation_residues_below_min(artifact_with_trace) -> None:
    art = artifact_with_trace(viewer_state=_SAMPLE_STATE)  # type: ignore[arg-type]
    result = check_system_representation_residues(
        art,
        {"system": "2V62", "style": "ball-and-stick", "min_count": 100},
    )
    assert not result.passed
    assert "expected >= 100" in result.evidence


def test_system_representation_residues_must_include(artifact_with_trace) -> None:
    art = artifact_with_trace(viewer_state=_SAMPLE_STATE)  # type: ignore[arg-type]
    result = check_system_representation_residues(
        art,
        {
            "system": "2V62",
            "style": "ball-and-stick",
            "must_include": [16, 17, 20],
        },
    )
    assert result.passed


def test_system_representation_residues_missing_required(artifact_with_trace) -> None:
    art = artifact_with_trace(viewer_state=_SAMPLE_STATE)  # type: ignore[arg-type]
    result = check_system_representation_residues(
        art,
        {
            "system": "2V62",
            "style": "ball-and-stick",
            "must_include": [16, 999],
        },
    )
    assert not result.passed
    assert "999" in result.evidence


def test_viewer_system_count_list_shape(artifact_with_trace) -> None:
    """Regression: ``systems_tree`` is a top-level JSON array, not a dict."""
    art = artifact_with_trace(viewer_state=_SAMPLE_STATE)  # type: ignore[arg-type]
    result = check_viewer_system_count(art, {"value": 2, "op": ">="})
    assert result.passed, result.evidence
