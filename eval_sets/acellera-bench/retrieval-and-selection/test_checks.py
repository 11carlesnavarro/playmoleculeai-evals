"""Tests for the retrieval-and-selection checks.

Every check is exercised three ways:

* the golden answer, built from ``fixtures/ground_truth.json`` itself, must
  score 1.0, so the expected values and the checks can never drift apart;
* rewrites of that golden answer that change only formatting must still
  score 1.0, so a correct agent is never marked wrong;
* near-miss answers, one wrong value at a time, must score 0.0, so a wrong
  agent is never marked right.

No network, no browser: the checks read CSVs from a temporary workspace.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from pmai_evals.eval_loader import load_eval_set
from pmai_evals.runner.artifacts import RunArtifact

checks = cast(
    Any,
    load_eval_set(
        "acellera-bench/retrieval-and-selection", root=Path("eval_sets")
    ).checks_module,
)

TRUTH = json.loads(
    (
        Path("eval_sets/acellera-bench/retrieval-and-selection/fixtures/ground_truth.json")
    ).read_text(encoding="utf-8")
)


# --- harness --------------------------------------------------------------

def artifact(tmp_path: Path, files: dict[str, str], answer: str = "") -> RunArtifact:
    """A RunArtifact whose workspace holds ``files`` and whose answer is ``answer``."""
    art = RunArtifact(run_dir=tmp_path / "run", case_id="c", model="m", seed=1)
    art.project_files_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (art.project_files_dir / name).write_text(content, encoding="utf-8")
    art.cell_dir.mkdir(parents=True, exist_ok=True)
    art.final_answer_path.write_text(answer, encoding="utf-8")
    return art


def csv_text(header: str, rows: list[str]) -> str:
    return "\n".join([header, *rows]) + "\n"


def score(check: Any, tmp_path: Path, files: dict[str, str], answer: str = "") -> float:
    return check(artifact(tmp_path, files, answer), {}).score


def evidence(check: Any, tmp_path: Path, files: dict[str, str], answer: str = "") -> str:
    return check(artifact(tmp_path, files, answer), {}).evidence


# --- golden answers, derived from the fixture -----------------------------

def golden_target() -> str:
    t = TRUTH["rs-uniprot"]
    return csv_text(
        "gene,accession,entry_name,sequence_length,residue_397",
        [f"{t['gene']},{t['accession']},{t['entry_name']},"
         f"{t['sequence_length']},{t['residue_397']}"],
    )


def golden_ligands() -> str:
    t = TRUTH["rs-ligands"]
    rows = [f"{c['comp_id']},{c['formula_weight']},{t['roles'][c['comp_id']]}"
            for c in t["components"]]
    return csv_text("het_code,formula_weight,role", rows)


def golden_structures() -> str:
    rows = [f"{e['pdb_id']},{e['resolution']}" for e in TRUTH["rs-search"]["entries"]]
    return csv_text("pdb_id,resolution", rows)


def golden_choice() -> str:
    t = TRUTH["rs-select"]
    return csv_text(
        "pdb_id,resolution,n_candidates",
        [f"{t['selected']},{t['best_resolution']},{len(t['candidates'])}"],
    )


def golden_mapping() -> str:
    probes = TRUTH["rs-numbering"]["probes"]
    rows = [f"{auth},{probes[auth]['uniprot_resid']},{probes[auth]['residue']}"
            for auth in sorted(probes, key=int)]
    return csv_text("auth_resid,uniprot_resid,residue", rows)


def golden_identity() -> str:
    t = TRUTH["rs-identity"]
    return csv_text(
        "alignment_length,identical_positions,percent_identity",
        [f"{t['alignment_length']},{t['identical_positions']},"
         f"{t['percent_identity']:.2f}"],
    )


def golden_metrics() -> str:
    t = TRUTH["rs-alphafold"]
    return csv_text(
        "n_residues,mean_plddt,n_below_70",
        [f"{t['n_residues']},{t['mean_plddt']:.2f},{t['n_below_70']}"],
    )


def golden_composition() -> str:
    rows = [f"{s['accession']},{s['auth_start']},{s['auth_end']},"
            f"{s['uniprot_start']},{s['uniprot_end']}"
            for s in TRUTH["rs-chimera"]["segments"]]
    return csv_text("accession,auth_start,auth_end,uniprot_start,uniprot_end", rows)


def golden_mutations() -> str:
    rows = [f"{m['accession']},{m['uniprot_resid']},{m['wild_type']},{m['mutant']}"
            for m in TRUTH["rs-chimera"]["mutations"]]
    return csv_text("accession,uniprot_resid,wild_type,mutant", rows)


def golden_calls() -> str:
    rows = []
    for pdb_id, codes in sorted(TRUTH["rs-classify"]["calls"].items()):
        rows.extend(f"{pdb_id},{c}" for c in codes) if codes else rows.append(f"{pdb_id},none")
    return csv_text("pdb_id,het_code", rows)


def golden_result() -> str:
    return csv_text(
        "n_structures,best_pdb_id,alternative",
        ["0,none,AlphaFold DB model AF-O00254-F1"],
    )


# --- shared behaviour: every check must reject a missing or empty file ----

FILE_CASES = [
    (lambda: checks.rs_uniprot_target, "target.csv", golden_target),
    (lambda: checks.rs_ligands_roles, "ligands.csv", golden_ligands),
    (lambda: checks.rs_search_structures, "structures.csv", golden_structures),
    (lambda: checks.rs_select_choice, "choice.csv", golden_choice),
    (lambda: checks.rs_numbering_mapping, "mapping.csv", golden_mapping),
    (lambda: checks.rs_identity_metrics, "identity.csv", golden_identity),
    (lambda: checks.rs_alphafold_metrics, "metrics.csv", golden_metrics),
    (lambda: checks.rs_chimera_composition, "composition.csv", golden_composition),
    (lambda: checks.rs_chimera_mutations, "mutations.csv", golden_mutations),
    (lambda: checks.rs_classify_calls, "ligand_calls.csv", golden_calls),
    (lambda: checks.rs_absent_result, "result.csv", golden_result),
]


@pytest.mark.parametrize("get_check,filename,golden", FILE_CASES)
def test_golden_answer_passes(tmp_path: Path, get_check: Any, filename: str, golden: Any) -> None:
    assert score(get_check(), tmp_path, {filename: golden()}) == 1.0


@pytest.mark.parametrize("get_check,filename,golden", FILE_CASES)
def test_missing_file_fails(tmp_path: Path, get_check: Any, filename: str, golden: Any) -> None:
    assert score(get_check(), tmp_path, {}) == 0.0


@pytest.mark.parametrize("get_check,filename,golden", FILE_CASES)
def test_header_only_file_fails(tmp_path: Path, get_check: Any, filename: str, golden: Any) -> None:
    header = golden().splitlines()[0]
    assert score(get_check(), tmp_path, {filename: header + "\n"}) == 0.0


@pytest.mark.parametrize("get_check,filename,golden", FILE_CASES)
def test_missing_column_fails(tmp_path: Path, get_check: Any, filename: str, golden: Any) -> None:
    """Dropping the last column must fail, and say which column is gone."""
    lines = golden().splitlines()
    header, *rows = lines
    columns = header.split(",")
    dropped = columns[-1]
    trimmed = csv_text(
        ",".join(columns[:-1]),
        [",".join(r.split(",")[:-1]) for r in rows],
    )
    result = get_check()(artifact(tmp_path, {filename: trimmed}), {})
    assert result.score == 0.0
    assert dropped in result.evidence


@pytest.mark.parametrize("get_check,filename,golden", FILE_CASES)
def test_formatting_variants_still_pass(
    tmp_path: Path, get_check: Any, filename: str, golden: Any
) -> None:
    """Upper-case headers, padding, a stray column and a blank last line."""
    header, *rows = golden().splitlines()
    noisy = csv_text(
        ",".join(c.upper() for c in header.split(",")) + ",note",
        [",".join(f" {cell} " for cell in row.split(",")) + ",ignored" for row in rows] + [""],
    )
    assert score(get_check(), tmp_path, {filename: noisy}) == 1.0


def perturb(cell: str) -> str:
    """Change a cell's meaning by more than any tolerance allows."""
    try:
        value = float(cell)
    except ValueError:
        return f"{cell}X" if cell.strip().lower() not in _EMPTY else "ZZZ"
    return f"{value + 1.0:g}" if value == int(value) else f"{value + 1.0:.4f}"


_EMPTY = {"", "none", "n/a", "na", "null", "-", "--"}


def cell_addresses(golden_text: str) -> list[tuple[int, int]]:
    header, *rows = golden_text.strip().splitlines()
    return [(r, c) for r in range(len(rows)) for c in range(len(header.split(",")))]


# Free-text fields, checked by substance rather than by exact string. The
# prompt asks the agent to name a model, and there is no single canonical
# spelling, so "AlphaFold DB model AF-O00254-F1" and "the AlphaFold model"
# are both right. Demanding one exact string here would fail correct
# answers, which is the worse error.
FREE_TEXT_CELLS = {("result.csv", "alternative")}


@pytest.mark.parametrize("get_check,filename,golden", FILE_CASES)
def test_every_cell_matters(
    tmp_path: Path, get_check: Any, filename: str, golden: Any
) -> None:
    """Changing any one cell of the right answer must make the check fail.

    This is the leniency audit. A cell that can be changed without
    changing the verdict is a value the check silently ignores, which is
    how a wrong answer would slip through.
    """
    text = golden()
    header, *rows = text.strip().splitlines()
    survivors = []
    for row_index, col_index in cell_addresses(text):
        cells = rows[row_index].split(",")
        if col_index >= len(cells):
            continue
        if (filename, header.split(",")[col_index]) in FREE_TEXT_CELLS:
            continue
        original = cells[col_index]
        cells[col_index] = perturb(original)
        mutated = list(rows)
        mutated[row_index] = ",".join(cells)
        if score(get_check(), tmp_path, {filename: csv_text(header, mutated)}) != 0.0:
            column = header.split(",")[col_index]
            survivors.append(f"row {row_index} {column}={original!r} -> {cells[col_index]!r}")
    assert not survivors, f"{filename}: ignored cells: {survivors}"


@pytest.mark.parametrize("get_check,filename,golden", FILE_CASES)
def test_every_row_matters(
    tmp_path: Path, get_check: Any, filename: str, golden: Any
) -> None:
    """Dropping any one row of the right answer must make the check fail."""
    header, *rows = golden().strip().splitlines()
    survivors = []
    for index in range(len(rows)):
        kept = rows[:index] + rows[index + 1:]
        if score(get_check(), tmp_path, {filename: csv_text(header, kept)}) != 0.0:
            survivors.append(rows[index])
    assert not survivors, f"{filename}: droppable rows: {survivors}"


@pytest.mark.parametrize("get_check,filename,golden", FILE_CASES)
def test_byte_order_mark_still_passes(
    tmp_path: Path, get_check: Any, filename: str, golden: Any
) -> None:
    """A spreadsheet export puts a BOM before the first header cell."""
    assert score(get_check(), tmp_path, {filename: "﻿" + golden()}) == 1.0


@pytest.mark.parametrize("get_check,filename,golden", FILE_CASES)
def test_semicolon_delimiter_still_passes(
    tmp_path: Path, get_check: Any, filename: str, golden: Any
) -> None:
    """A semicolon-separated file under a .csv name is still the right answer."""
    text = golden()
    if any("," in line.split(",", 1)[-1] for line in text.splitlines() if '"' in line):
        pytest.skip("golden answer contains quoted commas")
    assert score(get_check(), tmp_path, {filename: text.replace(",", ";")}) == 1.0


@pytest.mark.parametrize("get_check,filename,golden", FILE_CASES)
def test_duplicate_rows_still_pass(
    tmp_path: Path, get_check: Any, filename: str, golden: Any
) -> None:
    """Writing a row twice repeats a claim; it does not change it."""
    header, *rows = golden().splitlines()
    assert score(get_check(), tmp_path, {filename: csv_text(header, rows + rows)}) == 1.0


# --- rs-uniprot -----------------------------------------------------------

def test_uniprot_three_letter_residue_passes(tmp_path: Path) -> None:
    text = golden_target().replace(",C\n", ",Cys\n")
    assert score(checks.rs_uniprot_target, tmp_path, {"target.csv": text}) == 1.0


@pytest.mark.parametrize("wrong,field", [
    ("P27339", "accession"),
    ("519", "sequence_length"),
])
def test_uniprot_near_miss_fails(tmp_path: Path, wrong: str, field: str) -> None:
    t = TRUTH["rs-uniprot"]
    values = {
        "accession": t["accession"], "entry_name": t["entry_name"],
        "sequence_length": str(t["sequence_length"]), "residue_397": t["residue_397"],
    }
    values[field] = wrong
    text = csv_text(
        "gene,accession,entry_name,sequence_length,residue_397",
        [f"{t['gene']},{values['accession']},{values['entry_name']},"
         f"{values['sequence_length']},{values['residue_397']}"],
    )
    assert score(checks.rs_uniprot_target, tmp_path, {"target.csv": text}) == 0.0


def test_uniprot_wrong_residue_fails(tmp_path: Path) -> None:
    """Residue 397 is the point of the case: the sequence must be read."""
    text = golden_target().replace(",C\n", ",S\n")
    assert score(checks.rs_uniprot_target, tmp_path, {"target.csv": text}) == 0.0


def test_uniprot_non_numeric_length_fails(tmp_path: Path) -> None:
    text = golden_target().replace(",520,", ",about 520,")
    assert score(checks.rs_uniprot_target, tmp_path, {"target.csv": text}) == 0.0


# --- rs-ligands -----------------------------------------------------------

def test_ligands_swapped_roles_fails(tmp_path: Path) -> None:
    text = golden_ligands().replace("cofactor", "TEMP").replace("inhibitor", "cofactor")
    text = text.replace("TEMP", "inhibitor")
    assert score(checks.rs_ligands_roles, tmp_path, {"ligands.csv": text}) == 0.0


def test_ligands_missing_cofactor_fails(tmp_path: Path) -> None:
    """Reporting only the inhibitor is an incomplete answer, not a right one."""
    lines = golden_ligands().splitlines()
    text = csv_text(lines[0], [ln for ln in lines[1:] if not ln.startswith("FAD")])
    assert score(checks.rs_ligands_roles, tmp_path, {"ligands.csv": text}) == 0.0


def test_ligands_includes_water_fails(tmp_path: Path) -> None:
    text = golden_ligands() + "HOH,18.015,cofactor\n"
    assert score(checks.rs_ligands_roles, tmp_path, {"ligands.csv": text}) == 0.0


def test_ligands_rounded_weight_passes(tmp_path: Path) -> None:
    text = golden_ligands().replace("785.55", "785.6").replace("300.327", "300.33")
    assert score(checks.rs_ligands_roles, tmp_path, {"ligands.csv": text}) == 1.0


def test_ligands_wrong_weight_fails(tmp_path: Path) -> None:
    text = golden_ligands().replace("300.327", "663.4")
    assert score(checks.rs_ligands_roles, tmp_path, {"ligands.csv": text}) == 0.0


# --- rs-search ------------------------------------------------------------

def test_search_lowercase_ids_pass(tmp_path: Path) -> None:
    assert score(checks.rs_search_structures, tmp_path,
                 {"structures.csv": golden_structures().lower()}) == 1.0


def test_search_resolution_with_units_passes(tmp_path: Path) -> None:
    header, *rows = golden_structures().splitlines()
    text = csv_text(header, [f"{r} Å" for r in rows])
    assert score(checks.rs_search_structures, tmp_path, {"structures.csv": text}) == 1.0


def test_search_one_missing_entry_fails(tmp_path: Path) -> None:
    header, *rows = golden_structures().splitlines()
    result = checks.rs_search_structures(
        artifact(tmp_path, {"structures.csv": csv_text(header, rows[:-1])}), {})
    assert result.score == 0.0
    assert rows[-1].split(",")[0] in result.evidence


def test_search_one_extra_entry_fails(tmp_path: Path) -> None:
    """An entry above 1.0 Å does not meet the stated conditions."""
    text = golden_structures() + "1CA2,2.0\n"
    result = checks.rs_search_structures(artifact(tmp_path, {"structures.csv": text}), {})
    assert result.score == 0.0
    assert "1CA2" in result.evidence


def test_search_wrong_resolution_fails(tmp_path: Path) -> None:
    text = golden_structures().replace("1LUG,0.95", "1LUG,1.95")
    assert score(checks.rs_search_structures, tmp_path, {"structures.csv": text}) == 0.0


# --- rs-select ------------------------------------------------------------

def test_select_tied_but_wrong_alphabetical_fails(tmp_path: Path) -> None:
    """The tie-break is stated in the prompt, so ignoring it is wrong."""
    t = TRUTH["rs-select"]
    other = next(p for p in t["tied_at_best"] if p != t["selected"])
    text = golden_choice().replace(t["selected"], other)
    result = checks.rs_select_choice(artifact(tmp_path, {"choice.csv": text}), {})
    assert result.score == 0.0
    assert "tie-break" in result.evidence


def test_select_wrong_candidate_count_fails(tmp_path: Path) -> None:
    t = TRUTH["rs-select"]
    text = csv_text("pdb_id,resolution,n_candidates",
                    [f"{t['selected']},{t['best_resolution']},{len(t['candidates']) + 5}"])
    assert score(checks.rs_select_choice, tmp_path, {"choice.csv": text}) == 0.0


def test_select_answer_tag_variants(tmp_path: Path) -> None:
    selected = TRUTH["rs-select"]["selected"]
    assert score(checks.rs_select_answer_tag, tmp_path, {},
                 f"text <answer>{selected.lower()}</answer>") == 1.0
    assert score(checks.rs_select_answer_tag, tmp_path, {},
                 f"<answer> {selected} </answer>") == 1.0


def test_select_answer_tag_uses_last_tag(tmp_path: Path) -> None:
    selected = TRUTH["rs-select"]["selected"]
    assert score(checks.rs_select_answer_tag, tmp_path, {},
                 f"<answer>1CA2</answer> on reflection <answer>{selected}</answer>") == 1.0


def test_select_answer_tag_missing_or_wrong_fails(tmp_path: Path) -> None:
    assert score(checks.rs_select_answer_tag, tmp_path, {}, "the answer is 3K34") == 0.0
    assert score(checks.rs_select_answer_tag, tmp_path, {}, "<answer>1CA2</answer>") == 0.0


# --- rs-numbering ---------------------------------------------------------

def test_numbering_extra_rows_are_ignored(tmp_path: Path) -> None:
    """Listing the whole chain is a superset of the answer, so it passes."""
    text = golden_mapping() + "70,90,K\n71,91,A\n"
    assert score(checks.rs_numbering_mapping, tmp_path, {"mapping.csv": text}) == 1.0


def test_numbering_identity_mapping_fails(tmp_path: Path) -> None:
    """Assuming PDB numbering equals UniProt numbering is the trap here."""
    probes = TRUTH["rs-numbering"]["probes"]
    rows = [f"{a},{a},{probes[a]['residue']}" for a in sorted(probes, key=int)]
    text = csv_text("auth_resid,uniprot_resid,residue", rows)
    assert score(checks.rs_numbering_mapping, tmp_path, {"mapping.csv": text}) == 0.0


def test_numbering_one_probe_missing_fails(tmp_path: Path) -> None:
    header, *rows = golden_mapping().splitlines()
    result = checks.rs_numbering_mapping(
        artifact(tmp_path, {"mapping.csv": csv_text(header, rows[1:])}), {})
    assert result.score == 0.0
    assert "no row for auth_resid" in result.evidence


def test_numbering_contradictory_rows_fail(tmp_path: Path) -> None:
    text = golden_mapping() + "122,999,I\n"
    result = checks.rs_numbering_mapping(artifact(tmp_path, {"mapping.csv": text}), {})
    assert result.score == 0.0
    assert "two different answers" in result.evidence


def test_numbering_answer_tag(tmp_path: Path) -> None:
    diff = TRUTH["rs-numbering"]["differences"][0]
    assert score(checks.rs_numbering_answer_tag, tmp_path, {},
                 f"<answer>{diff['uniprot_resid']}</answer>") == 1.0
    assert score(checks.rs_numbering_answer_tag, tmp_path, {},
                 f"<answer>Val{diff['uniprot_resid']}Ile</answer>") == 1.0


def test_numbering_answer_tag_pdb_number_fails_with_hint(tmp_path: Path) -> None:
    diff = TRUTH["rs-numbering"]["differences"][0]
    result = checks.rs_numbering_answer_tag(
        artifact(tmp_path, {}, f"<answer>{diff['auth_resid']}</answer>"), {})
    assert result.score == 0.0
    assert "PDB numbering" in result.evidence


# --- rs-identity ----------------------------------------------------------

def test_identity_rounding_variants_pass(tmp_path: Path) -> None:
    t = TRUTH["rs-identity"]
    for percent in (f"{t['percent_identity']:.2f}", f"{t['percent_identity']:.4f}",
                    f"{t['percent_identity']:.1f}"):
        text = csv_text("alignment_length,identical_positions,percent_identity",
                        [f"{t['alignment_length']},{t['identical_positions']},{percent}"])
        assert score(checks.rs_identity_metrics, tmp_path, {"identity.csv": text}) == 1.0


def test_identity_percent_of_shorter_sequence_fails(tmp_path: Path) -> None:
    """Dividing by sequence length instead of alignment length is wrong."""
    t = TRUTH["rs-identity"]
    text = csv_text("alignment_length,identical_positions,percent_identity",
                    [f"{t['alignment_length']},{t['identical_positions']},"
                     f"{100 * t['identical_positions'] / 297:.2f}"])
    assert score(checks.rs_identity_metrics, tmp_path, {"identity.csv": text}) == 0.0


def test_identity_wrong_alignment_length_fails(tmp_path: Path) -> None:
    t = TRUTH["rs-identity"]
    text = csv_text("alignment_length,identical_positions,percent_identity",
                    [f"298,{t['identical_positions']},{t['percent_identity']:.2f}"])
    assert score(checks.rs_identity_metrics, tmp_path, {"identity.csv": text}) == 0.0


# --- rs-alphafold ---------------------------------------------------------

def test_alphafold_mean_off_by_one_fails(tmp_path: Path) -> None:
    t = TRUTH["rs-alphafold"]
    text = csv_text("n_residues,mean_plddt,n_below_70",
                    [f"{t['n_residues']},{t['mean_plddt'] + 1:.2f},{t['n_below_70']}"])
    assert score(checks.rs_alphafold_metrics, tmp_path, {"metrics.csv": text}) == 0.0


def test_alphafold_wrong_low_confidence_count_fails(tmp_path: Path) -> None:
    t = TRUTH["rs-alphafold"]
    text = csv_text("n_residues,mean_plddt,n_below_70",
                    [f"{t['n_residues']},{t['mean_plddt']:.2f},{t['n_below_70'] + 1}"])
    assert score(checks.rs_alphafold_metrics, tmp_path, {"metrics.csv": text}) == 0.0


def test_alphafold_percent_sign_passes(tmp_path: Path) -> None:
    t = TRUTH["rs-alphafold"]
    text = csv_text("n_residues,mean_plddt,n_below_70",
                    [f"{t['n_residues']},{t['mean_plddt']:.2f}%,{t['n_below_70']}"])
    assert score(checks.rs_alphafold_metrics, tmp_path, {"metrics.csv": text}) == 1.0


# --- rs-chimera -----------------------------------------------------------

def test_chimera_missing_fusion_fails_with_named_evidence(tmp_path: Path) -> None:
    """Reporting only the receptor is exactly the mistake this case targets."""
    t = TRUTH["rs-chimera"]
    rows = [f"{s['accession']},{s['auth_start']},{s['auth_end']},"
            f"{s['uniprot_start']},{s['uniprot_end']}"
            for s in t["segments"] if s["accession"] != t["fusion_accession"]]
    text = csv_text("accession,auth_start,auth_end,uniprot_start,uniprot_end", rows)
    result = checks.rs_chimera_composition(artifact(tmp_path, {"composition.csv": text}), {})
    assert result.score == 0.0
    assert t["fusion_accession"] in result.evidence


def test_chimera_modelled_residue_reading_also_passes(tmp_path: Path) -> None:
    """3PBL does not model the receptor's first 30 residues.

    Reporting the span that has coordinates is as true as reporting the
    construct span, so both must pass.
    """
    rows = [f"{s['accession']},{s['auth_start']},{s['auth_end']},"
            f"{s['uniprot_start']},{s['uniprot_end']}"
            for s in TRUTH["rs-chimera"]["observed_segments"]]
    text = csv_text("accession,auth_start,auth_end,uniprot_start,uniprot_end", rows)
    result = checks.rs_chimera_composition(artifact(tmp_path, {"composition.csv": text}), {})
    assert result.score == 1.0
    assert "modelled residues" in result.evidence


def test_chimera_sequential_index_fails(tmp_path: Path) -> None:
    """SIFTS returns a sequential index next to the author numbering.

    For 3PBL the receptor's first segment is index 11-230 but author
    residues 2-221, and an agent that reports the index has not given a
    residue number that exists in the entry.
    """
    text = csv_text("accession,auth_start,auth_end,uniprot_start,uniprot_end",
                    ["P35462,11,230,2,221",
                     "P00720,1002,1161,2,161",
                     "P35462,319,400,319,400"])
    assert score(checks.rs_chimera_composition, tmp_path, {"composition.csv": text}) == 0.0


def test_chimera_merged_segments_fail(tmp_path: Path) -> None:
    """The receptor is split in two; one merged span hides the fusion."""
    text = csv_text("accession,auth_start,auth_end,uniprot_start,uniprot_end",
                    ["P35462,2,400,2,400"])
    assert score(checks.rs_chimera_composition, tmp_path, {"composition.csv": text}) == 0.0


def test_chimera_mutations_three_letter_codes_pass(tmp_path: Path) -> None:
    three = {v: k for k, v in checks._THREE_TO_ONE.items()}
    rows = [f"{m['accession']},{m['uniprot_resid']},"
            f"{three[m['wild_type']].title()},{three[m['mutant']].title()}"
            for m in TRUTH["rs-chimera"]["mutations"]]
    text = csv_text("accession,uniprot_resid,wild_type,mutant", rows)
    assert score(checks.rs_chimera_mutations, tmp_path, {"mutations.csv": text}) == 1.0


def test_chimera_mutations_only_receptor_fails(tmp_path: Path) -> None:
    t = TRUTH["rs-chimera"]
    rows = [f"{m['accession']},{m['uniprot_resid']},{m['wild_type']},{m['mutant']}"
            for m in t["target_mutations"]]
    text = csv_text("accession,uniprot_resid,wild_type,mutant", rows)
    assert score(checks.rs_chimera_mutations, tmp_path, {"mutations.csv": text}) == 0.0


def test_chimera_mutation_direction_matters(tmp_path: Path) -> None:
    """Swapping wild type and mutant reverses the claim, so it must fail."""
    rows = [f"{m['accession']},{m['uniprot_resid']},{m['mutant']},{m['wild_type']}"
            for m in TRUTH["rs-chimera"]["mutations"]]
    text = csv_text("accession,uniprot_resid,wild_type,mutant", rows)
    assert score(checks.rs_chimera_mutations, tmp_path, {"mutations.csv": text}) == 0.0


# --- rs-classify ----------------------------------------------------------

def test_classify_empty_cell_counts_as_none(tmp_path: Path) -> None:
    text = golden_calls().replace(",none", ",")
    assert score(checks.rs_classify_calls, tmp_path, {"ligand_calls.csv": text}) == 1.0


def test_classify_excluded_cofactor_fails(tmp_path: Path) -> None:
    """FAD is on the exclusion list the prompt spells out."""
    text = golden_calls() + "2V5Z,FAD\n"
    result = checks.rs_classify_calls(artifact(tmp_path, {"ligand_calls.csv": text}), {})
    assert result.score == 0.0
    assert "2V5Z" in result.evidence


def test_classify_missing_entry_fails(tmp_path: Path) -> None:
    header, *rows = golden_calls().splitlines()
    text = csv_text(header, [r for r in rows if not r.startswith("1TTR")])
    result = checks.rs_classify_calls(artifact(tmp_path, {"ligand_calls.csv": text}), {})
    assert result.score == 0.0
    assert "1TTR" in result.evidence


def test_classify_none_plus_code_is_contradictory(tmp_path: Path) -> None:
    text = golden_calls() + "1TTR,STU\n"
    result = checks.rs_classify_calls(artifact(tmp_path, {"ligand_calls.csv": text}), {})
    assert result.score == 0.0
    assert "none" in result.evidence


def test_classify_hallucinated_ligand_for_empty_entry_fails(tmp_path: Path) -> None:
    header, *rows = golden_calls().splitlines()
    text = csv_text(header, [r if r != "1TTR,none" else "1TTR,RET" for r in rows])
    assert score(checks.rs_classify_calls, tmp_path, {"ligand_calls.csv": text}) == 0.0


def test_classify_unlisted_entry_is_ignored(tmp_path: Path) -> None:
    text = golden_calls() + "9XYZ,ABC\n"
    assert score(checks.rs_classify_calls, tmp_path, {"ligand_calls.csv": text}) == 1.0


# --- rs-absent ------------------------------------------------------------

def test_absent_invented_structure_fails(tmp_path: Path) -> None:
    text = csv_text("n_structures,best_pdb_id,alternative", ["1,4XYZ,none"])
    result = checks.rs_absent_result(artifact(tmp_path, {"result.csv": text}), {})
    assert result.score == 0.0
    assert "invented" in result.evidence


def test_absent_right_count_but_named_structure_fails(tmp_path: Path) -> None:
    """Saying zero and still naming an id is a contradiction, so it fails."""
    text = csv_text("n_structures,best_pdb_id,alternative", ["0,7XYZ,AlphaFold"])
    assert score(checks.rs_absent_result, tmp_path, {"result.csv": text}) == 0.0


def test_absent_without_alternative_fails(tmp_path: Path) -> None:
    text = csv_text("n_structures,best_pdb_id,alternative", ["0,none,none"])
    result = checks.rs_absent_result(artifact(tmp_path, {"result.csv": text}), {})
    assert result.score == 0.0
    assert "alternative" in result.evidence


def test_absent_homology_alternative_fails(tmp_path: Path) -> None:
    """The case asks for the AlphaFold model, so another suggestion is wrong."""
    text = csv_text("n_structures,best_pdb_id,alternative", ["0,none,a PAR1 homology model"])
    assert score(checks.rs_absent_result, tmp_path, {"result.csv": text}) == 0.0


def test_absent_accession_named_alternative_passes(tmp_path: Path) -> None:
    text = csv_text("n_structures,best_pdb_id,alternative", ["0,none,AF-O00254-F1-model_v6"])
    assert score(checks.rs_absent_result, tmp_path, {"result.csv": text}) == 1.0


def test_absent_answer_tag(tmp_path: Path) -> None:
    assert score(checks.rs_absent_answer_tag, tmp_path, {}, "<answer>0</answer>") == 1.0
    assert score(checks.rs_absent_answer_tag, tmp_path, {}, "<answer>3</answer>") == 0.0
    assert score(checks.rs_absent_answer_tag, tmp_path, {}, "there are none") == 0.0
