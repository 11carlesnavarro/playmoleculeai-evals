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
    check_tool_call_count,
    check_tool_call_order,
    check_tool_called,
    check_tool_called_with,
    check_viewer_color_scheme_is,
    check_viewer_has_molecule,
    check_viewer_has_residue,
    check_viewer_representation_is,
    check_viewer_system_count,
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


def test_viewer_representation_is(artifact_with_trace) -> None:
    art = artifact_with_trace(
        viewer_state={"representations": [{"representation": "cartoon"}]}
    )
    assert check_viewer_representation_is(art, {"representation": "cartoon"}).passed


def test_viewer_color_scheme_is(artifact_with_trace) -> None:
    art = artifact_with_trace(viewer_state={"color_scheme": "by_chain"})
    assert check_viewer_color_scheme_is(art, {"scheme": "chain"}).passed


def test_viewer_has_residue(artifact_with_trace) -> None:
    art = artifact_with_trace(viewer_state={"residues": ["HEM", "ALA"]})
    assert check_viewer_has_residue(art, {"name": "HEM"}).passed
    assert not check_viewer_has_residue(art, {"name": "TRP"}).passed


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
        "viewer_representation_is",
        "viewer_color_scheme_is",
        "viewer_has_residue",
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
