"""Unit tests for the molecular-visualization eval-set checks module.

The check functions are loaded through the standard eval loader so the
import path matches production. Fixtures from ``conftest.py`` build
in-memory Molecules and write them into an artifact directory shaped
like a real run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pmai_evals.eval_loader import load_eval_set


@pytest.fixture(scope="module")
def checks():
    es = load_eval_set("molecular-visualization", root=Path("eval_sets"))
    assert es.checks_module is not None
    return es.checks_module


# --- helpers --------------------------------------------------------------

def test_normalise_rgb_int_and_string_match(checks) -> None:
    assert checks._normalise_rgb(0x0000FF) == "rgb=0000FF"
    assert checks._normalise_rgb("#0000FF") == "rgb=0000FF"
    assert checks._normalise_rgb("0000ff") == "rgb=0000FF"
    assert checks._normalise_rgb("not-a-color") is None
    assert checks._normalise_rgb("") is None
    assert checks._normalise_rgb(None) is None


def test_cartoon_color_key_normalises_int_and_string(checks) -> None:
    int_form = {
        "representations": [{"type": "cartoon", "color_value": 0x0000FF}],
    }
    string_form = {
        "representations": [{"type": "cartoon", "color_value": "#0000FF"}],
    }
    assert checks._cartoon_color_key(int_form) == checks._cartoon_color_key(string_form)


def test_cartoon_color_key_falls_back_to_scheme(checks) -> None:
    sys = {"representations": [{"type": "cartoon", "color": "by-chain"}]}
    assert checks._cartoon_color_key(sys) == "scheme=by-chain"


# --- all_systems_distinct_colors -----------------------------------------

def test_all_systems_distinct_colors_pass(checks, artifact_factory) -> None:
    state = [
        {
            "name": "A",
            "representations": [{"type": "cartoon", "color_value": 0xFF0000}],
        },
        {
            "name": "B",
            "representations": [{"type": "cartoon", "color_value": 0x00FF00}],
        },
    ]
    artifact = artifact_factory(viewer_state=state)
    result = checks.all_systems_distinct_colors(artifact, {})
    assert result.passed, result.evidence


def test_all_systems_distinct_colors_collision(checks, artifact_factory) -> None:
    """Same RGB expressed differently should still be detected as a clash."""
    state = [
        {
            "name": "A",
            "representations": [{"type": "cartoon", "color_value": 0x0000FF}],
        },
        {
            "name": "B",
            "representations": [{"type": "cartoon", "color_value": "#0000FF"}],
        },
    ]
    artifact = artifact_factory(viewer_state=state)
    result = checks.all_systems_distinct_colors(artifact, {})
    assert not result.passed
    assert "share cartoon colors" in result.evidence


def test_all_systems_distinct_colors_missing_cartoon(checks, artifact_factory) -> None:
    state = [
        {"name": "A", "representations": [{"type": "ball-and-stick"}]},
        {
            "name": "B",
            "representations": [{"type": "cartoon", "color_value": 0xFF0000}],
        },
    ]
    artifact = artifact_factory(viewer_state=state)
    result = checks.all_systems_distinct_colors(artifact, {})
    assert not result.passed
    assert "no cartoon rep" in result.evidence


# --- structures_coaligned ------------------------------------------------

def test_structures_coaligned_pass(checks, artifact_factory, build_protein_mol) -> None:
    a = build_protein_mol(n_residues=10)
    b = build_protein_mol(n_residues=10, x_offset=0.2)  # 0.2 Å shift
    artifact = artifact_factory(systems=[("A", a), ("B", b)])
    result = checks.structures_coaligned(artifact, {"max_rmsd_a": 1.0})
    assert result.passed, result.evidence


def test_structures_coaligned_fail_when_far_apart(
    checks, artifact_factory, build_protein_mol
) -> None:
    a = build_protein_mol(n_residues=10)
    b = build_protein_mol(n_residues=10, x_offset=20.0)  # way off
    artifact = artifact_factory(systems=[("A", a), ("B", b)])
    result = checks.structures_coaligned(artifact, {"max_rmsd_a": 1.0})
    assert not result.passed
    assert "RMSD" in result.evidence


def test_structures_coaligned_needs_two_systems(checks, artifact_factory, build_protein_mol) -> None:
    artifact = artifact_factory(systems=[("A", build_protein_mol(n_residues=5))])
    result = checks.structures_coaligned(artifact, {})
    assert not result.passed
    assert "need" in result.evidence


# --- reported_rmsd_matches -----------------------------------------------

def test_reported_rmsd_matches_pass(
    checks, artifact_factory, build_protein_mol
) -> None:
    a = build_protein_mol(n_residues=10)
    b = build_protein_mol(n_residues=10, x_offset=0.2)
    artifact = artifact_factory(
        systems=[("REFA", a), ("MOBB", b)], final_answer="RMSD MOBB = 0.20 Å"
    )
    result = checks.reported_rmsd_matches(
        artifact, {"reference": "REFA", "tolerance_a": 0.5}
    )
    assert result.passed, result.evidence


def test_reported_rmsd_matches_fails_on_lying_value(
    checks, artifact_factory, build_protein_mol
) -> None:
    a = build_protein_mol(n_residues=10)
    b = build_protein_mol(n_residues=10, x_offset=20.0)
    artifact = artifact_factory(
        systems=[("REFA", a), ("MOBB", b)], final_answer="RMSD MOBB = 0.50 Å"
    )
    result = checks.reported_rmsd_matches(
        artifact, {"reference": "REFA", "tolerance_a": 1.0}
    )
    assert not result.passed
    assert "Δ" in result.evidence


def test_reported_rmsd_matches_no_lines(
    checks, artifact_factory, build_protein_mol
) -> None:
    a = build_protein_mol(n_residues=10)
    b = build_protein_mol(n_residues=10)
    artifact = artifact_factory(
        systems=[("REFA", a), ("MOBB", b)], final_answer="no rmsd here"
    )
    result = checks.reported_rmsd_matches(artifact, {"reference": "REFA"})
    assert not result.passed
    assert "no RMSD lines" in result.evidence


# --- active_site_residues_correct ----------------------------------------

def test_active_site_residues_correct_pass(
    checks, artifact_factory, mol_with_cofactor
) -> None:
    state = [
        {
            "name": "MOL",
            "representations": [
                # Highlight residues 2 3 4: matches the engineered pocket.
                {
                    "type": "ball-and-stick",
                    "selection": "chain A and resid 2 3 4",
                },
            ],
        },
    ]
    artifact = artifact_factory(systems=[("MOL", mol_with_cofactor)], viewer_state=state)
    result = checks.active_site_residues_correct(
        artifact,
        {
            "system": "MOL",
            "cofactor_resnames": ["FAD"],
            "cutoff_a": 5.0,
            "min_jaccard": 0.5,
            "min_ground_truth": 3,
        },
    )
    assert result.passed, result.evidence


def test_active_site_residues_correct_misses(
    checks, artifact_factory, mol_with_cofactor
) -> None:
    state = [
        {
            "name": "MOL",
            "representations": [
                # Highlights residue 8, which is far from FAD: zero overlap.
                {"type": "ball-and-stick", "selection": "chain A and resid 8"},
            ],
        },
    ]
    artifact = artifact_factory(systems=[("MOL", mol_with_cofactor)], viewer_state=state)
    result = checks.active_site_residues_correct(
        artifact,
        {
            "system": "MOL",
            "cofactor_resnames": ["FAD"],
            "cutoff_a": 5.0,
            "min_jaccard": 0.5,
            "min_ground_truth": 3,
        },
    )
    assert not result.passed
    assert "jaccard" in result.evidence


def test_active_site_residues_correct_drops_whole_protein_default(
    checks, artifact_factory, mol_with_cofactor
) -> None:
    """A rep covering >90% of the protein is treated as a default backbone
    and ignored, so the agent without a real highlight still fails."""
    state = [
        {
            "name": "MOL",
            "representations": [
                {"type": "cartoon", "selection": "protein"},
            ],
        },
    ]
    artifact = artifact_factory(systems=[("MOL", mol_with_cofactor)], viewer_state=state)
    result = checks.active_site_residues_correct(
        artifact,
        {
            "system": "MOL",
            "cofactor_resnames": ["FAD"],
            "cutoff_a": 5.0,
            "min_jaccard": 0.5,
            "min_ground_truth": 3,
        },
    )
    assert not result.passed
    assert "no highlight representation" in result.evidence
