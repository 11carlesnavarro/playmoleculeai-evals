"""Tests for the cheminformatics-analysis checks.

Every check is exercised four ways:

* the golden answer, built from ``fixtures/ground_truth.json`` itself, must
  score 1.0, so the expected values and the checks can never drift apart;
* rewrites of that golden answer that change only formatting must still
  score 1.0, so a correct agent is never marked wrong;
* every single cell and every single row of the golden answer, changed or
  removed one at a time, must score 0.0, so no value is silently ignored;
* the wrong answers that the raw export invites must score 0.0: counting
  records as molecules, ignoring the relation or the unit column, reading
  `<= 100` where the prompt says below 100, taking `>=` where it says
  strictly greater, missing the molecule with no structure, skipping the
  stated tie-break, and inventing hERG data.

No network, no browser: the checks read CSVs from a temporary workspace.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from pmai_evals.eval_loader import load_eval_set
from pmai_evals.runner.artifacts import RunArtifact

SET_DIR = Path("eval_sets/acellera-bench/cheminformatics-analysis")

checks = cast(
    Any,
    load_eval_set("acellera-bench/cheminformatics-analysis", root=Path("eval_sets")).checks_module,
)

TRUTH = json.loads((SET_DIR / "fixtures/ground_truth.json").read_text(encoding="utf-8"))


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


def replace_cell(text: str, column: str, value: str, row_index: int = 0) -> str:
    """The same CSV with one cell of one row rewritten."""
    header, *rows = text.strip().splitlines()
    columns = header.split(",")
    cells = rows[row_index].split(",")
    cells[columns.index(column)] = value
    rows[row_index] = ",".join(cells)
    return csv_text(header, rows)


def row_of(text: str, *values: Any) -> str:
    return ",".join(str(v) for v in values)


# --- golden answers, derived from the fixture -----------------------------

CENSUS_HEADER = ("n_records,n_molecules,n_targets,n_ic50_records,n_ki_records,"
                 "n_exact_relation,n_not_in_nm,n_missing_value")
USABLE_HEADER = ("n_molecules_any_record,n_molecules_with_value,"
                 "n_molecules_without_value,n_molecules_potent,"
                 "n_flagged_records,largest_flagged_nm")
REPEATS_HEADER = ("n_measured_once,n_measured_more_than_once,widest_molecule,"
                  "widest_spread,widest_record_count")
SERIES_HEADER = ("n_molecules,n_without_structure,n_distinct_scaffolds,n_series,"
                 "best_scaffold,best_count,best_median_pic50,largest_scaffold,"
                 "largest_count")
SELECTIVITY_HEADER = ("n_cdk2_once,n_cdk1_once,n_shared,median_delta,"
                      "n_above_one_log,fraction_above_one_log,most_selective,"
                      "most_selective_delta")
CLIFFS_HEADER = "n_pairs,chembl_id_1,chembl_id_2,similarity,delta_pic50"
CHOICE_HEADER = ("n_kept,n_series,best_median_pic50,n_tied_on_median,"
                 "chosen_scaffold,member_count,chosen_compound,chosen_mw")


def golden_census() -> str:
    t = TRUTH["sar-1-census"]
    return csv_text(CENSUS_HEADER, [row_of(
        CENSUS_HEADER, t["n_records"], t["n_molecules"], t["n_targets"],
        t["n_ic50_records"], t["n_ki_records"], t["n_exact_relation"],
        t["n_not_in_nm"], t["n_missing_value"],
    )])


def golden_properties() -> str:
    t = TRUTH["sar-2-descriptors"]
    rows = [
        f"{name},{d['mw']:.3f},{d['clogp']:.3f},{d['tpsa']:.2f},"
        f"{d['hbd']},{d['hba']},{d['rotatable_bonds']}"
        for name, d in sorted(t.items())
    ]
    return csv_text("name,mw,clogp,tpsa,hbd,hba,rotatable_bonds", rows)


def golden_usable() -> str:
    t = TRUTH["sar-3-usable"]
    return csv_text(USABLE_HEADER, [row_of(
        USABLE_HEADER, t["n_molecules_any_record"], t["n_molecules_with_value"],
        t["n_molecules_without_value"], t["n_molecules_potent"],
        t["n_flagged_records"], f"{t['largest_flagged_nm']:.1f}",
    )])


def golden_repeats() -> str:
    t = TRUTH["sar-4-repeats"]
    return csv_text(REPEATS_HEADER, [row_of(
        REPEATS_HEADER, t["n_molecules_measured_once"],
        t["n_molecules_measured_more_than_once"], t["widest_molecule"],
        f"{t['widest_spread']:.3f}", t["widest_record_count"],
    )])


def golden_substructure() -> str:
    t = TRUTH["sar-5-substructure"]
    rows = [
        f"{group},{d['n_with']},{d['median_with']:.3f},"
        f"{d['median_without']:.3f},{d['difference']:.3f}"
        for group, d in sorted(t.items())
    ]
    return csv_text("group,n_with,median_with,median_without,difference", rows)


def golden_series() -> str:
    t = TRUTH["sar-6-series"]
    return csv_text(SERIES_HEADER, [row_of(
        SERIES_HEADER, t["n_molecules"], t["n_without_structure"],
        t["n_distinct_scaffolds"], t["n_series"], t["best_scaffold"],
        t["best_count"], f"{t['best_median_pic50']:.3f}", t["largest_scaffold"],
        t["largest_count"],
    )])


def golden_selectivity() -> str:
    t = TRUTH["sar-7-selectivity"]
    return csv_text(SELECTIVITY_HEADER, [row_of(
        SELECTIVITY_HEADER, t["n_cdk2_once"], t["n_cdk1_once"], t["n_shared"],
        f"{t['median_delta']:.3f}", t["n_above_one_log"],
        f"{t['fraction_above_one_log']:.3f}", t["most_selective"],
        f"{t['most_selective_delta']:.3f}",
    )])


def golden_cliffs() -> str:
    t = TRUTH["sar-8-cliffs"]
    first, second = t["largest_pair"]
    return csv_text(CLIFFS_HEADER, [row_of(
        CLIFFS_HEADER, t["n_cliff_pairs"], first, second,
        f"{t['largest_similarity']:.3f}", f"{t['largest_delta']:.3f}",
    )])


def golden_choice() -> str:
    t = TRUTH["sar-9-multistep"]
    return csv_text(CHOICE_HEADER, [row_of(
        CHOICE_HEADER, t["n_kept"], t["n_series"], f"{t['best_median_pic50']:.3f}",
        t["n_tied_on_median"], t["chosen_scaffold"], t["member_count"],
        t["chosen_compound"], f"{t['chosen_mw']:.3f}",
    )])


def golden_herg_window() -> str:
    rows = [f"{e['chembl_id']},{e['pic50']:.3f},unavailable"
            for e in TRUTH["sar-10-absent"]["top"]]
    return csv_text("chembl_id,cdk2_pic50,herg_pic50", rows)


# --- shared behaviour, applied to every file check ------------------------

FILE_CASES = [
    (lambda: checks.sar_census, "census.csv", golden_census),
    (lambda: checks.sar_descriptors_properties, "properties.csv", golden_properties),
    (lambda: checks.sar_usable_counts, "usable.csv", golden_usable),
    (lambda: checks.sar_repeats_summary, "repeats.csv", golden_repeats),
    (lambda: checks.sar_substructure_trend, "substructure.csv", golden_substructure),
    (lambda: checks.sar_series_summary, "series.csv", golden_series),
    (lambda: checks.sar_selectivity_summary, "selectivity.csv", golden_selectivity),
    (lambda: checks.sar_cliffs_summary, "cliffs.csv", golden_cliffs),
    (lambda: checks.sar_multistep_choice, "choice.csv", golden_choice),
    (lambda: checks.sar_absent_window, "herg_window.csv", golden_herg_window),
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
    header, *rows = golden().strip().splitlines()
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
    header, *rows = golden().strip().splitlines()
    noisy = csv_text(
        ",".join(c.upper() for c in header.split(",")) + ",note",
        [",".join(f" {cell} " for cell in row.split(",")) + ",ignored" for row in rows] + [""],
    )
    assert score(get_check(), tmp_path, {filename: noisy}) == 1.0


def perturb(cell: str) -> str:
    """Change a cell's meaning by more than any tolerance allows.

    The step is at least 1 and at least 1% of the value, so a big number
    such as 1230000.0 moves too, and a whole number stays whole so that it
    fails on its value and not on its shape.
    """
    try:
        value = float(cell)
    except ValueError:
        return f"{cell}X" if cell.strip().lower() not in _EMPTY else "ZZZ"
    step = max(1.0, abs(value) * 0.01)
    if value == int(value):
        return f"{value + max(1.0, round(step)):.0f}"
    return f"{value + step:.4f}"


_EMPTY = {"", "none", "n/a", "na", "null", "-", "--", "nan"}


@pytest.mark.parametrize("get_check,filename,golden", FILE_CASES)
def test_every_cell_matters(
    tmp_path: Path, get_check: Any, filename: str, golden: Any
) -> None:
    """Changing any one cell of the right answer must make the check fail.

    This is the leniency audit. A cell that can be changed without changing
    the verdict is a value the check silently ignores, which is how a wrong
    answer would slip through.
    """
    header, *rows = golden().strip().splitlines()
    columns = header.split(",")
    survivors = []
    for row_index, row in enumerate(rows):
        for col_index in range(len(columns)):
            cells = row.split(",")
            if col_index >= len(cells):
                continue
            original = cells[col_index]
            cells[col_index] = perturb(original)
            mutated = list(rows)
            mutated[row_index] = ",".join(cells)
            if score(get_check(), tmp_path, {filename: csv_text(header, mutated)}) != 0.0:
                survivors.append(
                    f"row {row_index} {columns[col_index]}={original!r} -> {cells[col_index]!r}"
                )
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
    assert score(get_check(), tmp_path, {filename: golden().replace(",", ";")}) == 1.0


@pytest.mark.parametrize("get_check,filename,golden", FILE_CASES)
def test_tab_delimiter_still_passes(
    tmp_path: Path, get_check: Any, filename: str, golden: Any
) -> None:
    assert score(get_check(), tmp_path, {filename: golden().replace(",", "\t")}) == 1.0


@pytest.mark.parametrize("get_check,filename,golden", FILE_CASES)
def test_duplicate_rows_still_pass(
    tmp_path: Path, get_check: Any, filename: str, golden: Any
) -> None:
    """Writing a row twice repeats a claim; it does not change it."""
    header, *rows = golden().strip().splitlines()
    assert score(get_check(), tmp_path, {filename: csv_text(header, rows + rows)}) == 1.0


@pytest.mark.parametrize("get_check,filename,golden", FILE_CASES)
def test_units_after_the_number_still_pass(
    tmp_path: Path, get_check: Any, filename: str, golden: Any
) -> None:
    """A trailing unit is formatting. ``313.324 Da`` is the same claim."""
    header, *rows = golden().strip().splitlines()

    def annotate(cell: str) -> str:
        try:
            float(cell)
        except ValueError:
            return cell
        return f"{cell} units"

    tagged = [",".join(annotate(c) for c in row.split(",")) for row in rows]
    assert score(get_check(), tmp_path, {filename: csv_text(header, tagged)}) == 1.0


def _is_float(cell: str) -> bool:
    try:
        float(cell)
    except ValueError:
        return False
    return True


@pytest.mark.parametrize("get_check,filename,golden", FILE_CASES)
def test_prose_instead_of_a_number_fails(
    tmp_path: Path, get_check: Any, filename: str, golden: Any
) -> None:
    """A cell that describes the value instead of giving it is not an answer."""
    header, *rows = golden().strip().splitlines()
    columns = header.split(",")
    numeric = [i for i, cell in enumerate(rows[0].split(","))
               if _is_float(cell) and columns[i] != "chembl_id"]
    assert numeric, f"{filename}: no numeric column to test"
    cells = rows[0].split(",")
    cells[numeric[0]] = f"about {cells[numeric[0]]}"
    mutated = [",".join(cells), *rows[1:]]
    assert score(get_check(), tmp_path, {filename: csv_text(header, mutated)}) == 0.0


# --- the set declares what these checks provide ---------------------------

def test_every_assertion_names_an_existing_check() -> None:
    """A typo in cases.yaml must not silently skip an assertion."""
    cases = yaml.safe_load((SET_DIR / "cases.yaml").read_text(encoding="utf-8"))["cases"]
    named = {a["function"] for case in cases for a in case["assertions"]}
    missing = sorted(name for name in named if not hasattr(checks, name))
    assert not missing, f"cases.yaml names checks that do not exist: {missing}"
    assert len(cases) == 10
    assert sum(len(c["assertions"]) for c in cases) == 12


def test_difficulty_mix_is_two_five_three() -> None:
    cases = yaml.safe_load((SET_DIR / "cases.yaml").read_text(encoding="utf-8"))["cases"]
    counts = {level: sum(1 for c in cases if c["difficulty"] == level)
              for level in ("easy", "medium", "hard")}
    assert counts == {"easy": 2, "medium": 5, "hard": 3}, counts


def test_no_case_preloads_the_answer_key() -> None:
    """ground_truth.json holds every answer. It must never reach the agent."""
    cases = yaml.safe_load((SET_DIR / "cases.yaml").read_text(encoding="utf-8"))["cases"]
    for case in cases:
        loaded = (case.get("preload") or {}).get("project", {}).get("files", [])
        assert "ground_truth.json" not in loaded, case["id"]
        assert loaded, f"{case['id']} loads no input file"


# --- sar-census -----------------------------------------------------------

def test_census_records_counted_as_molecules_fails(tmp_path: Path) -> None:
    """7,752 records are 5,037 molecules. Counting rows is the classic error."""
    t = TRUTH["sar-1-census"]
    text = replace_cell(golden_census(), "n_molecules", str(t["n_records"]))
    assert score(checks.sar_census, tmp_path, {"census.csv": text}) == 0.0


def test_census_all_records_called_exact_fails(tmp_path: Path) -> None:
    """2,466 records carry a censored or missing relation."""
    t = TRUTH["sar-1-census"]
    text = replace_cell(golden_census(), "n_exact_relation", str(t["n_records"]))
    assert score(checks.sar_census, tmp_path, {"census.csv": text}) == 0.0


def test_census_units_column_ignored_fails(tmp_path: Path) -> None:
    """Claiming every record is in nM misses 117 that are not."""
    text = replace_cell(golden_census(), "n_not_in_nm", "0")
    assert score(checks.sar_census, tmp_path, {"census.csv": text}) == 0.0


def test_census_ic50_and_ki_swapped_fails(tmp_path: Path) -> None:
    t = TRUTH["sar-1-census"]
    text = golden_census()
    text = replace_cell(text, "n_ic50_records", str(t["n_ki_records"]))
    text = replace_cell(text, "n_ki_records", str(t["n_ic50_records"]))
    assert score(checks.sar_census, tmp_path, {"census.csv": text}) == 0.0


# --- sar-descriptors ------------------------------------------------------

def test_descriptors_name_case_and_spacing_pass(tmp_path: Path) -> None:
    header, *rows = golden_properties().strip().splitlines()
    shouted = [",".join([r.split(",")[0].upper(), *r.split(",")[1:]]) for r in rows]
    assert score(checks.sar_descriptors_properties, tmp_path,
                 {"properties.csv": csv_text(header, shouted)}) == 1.0


def test_descriptors_swapped_molecules_fail(tmp_path: Path) -> None:
    """Right numbers against the wrong names is a wrong answer."""
    header, *rows = golden_properties().strip().splitlines()
    names = [r.split(",")[0] for r in rows]
    swapped = [",".join([names[(i + 1) % len(names)], *r.split(",")[1:]])
               for i, r in enumerate(rows)]
    assert score(checks.sar_descriptors_properties, tmp_path,
                 {"properties.csv": csv_text(header, swapped)}) == 0.0


def test_descriptors_extra_molecule_fails(tmp_path: Path) -> None:
    text = golden_properties() + "aspirin,180.159,1.310,63.60,1,3,2\n"
    assert score(checks.sar_descriptors_properties, tmp_path,
                 {"properties.csv": text}) == 0.0


def test_descriptors_duplicate_contradictory_row_fails(tmp_path: Path) -> None:
    header, *rows = golden_properties().strip().splitlines()
    doubled = [*rows, rows[0].replace(",3,", ",9,", 1)]
    result = checks.sar_descriptors_properties(
        artifact(tmp_path, {"properties.csv": csv_text(header, doubled)}), {}
    )
    assert result.score == 0.0
    assert "two different" in result.evidence


# --- sar-usable -----------------------------------------------------------

def test_usable_relation_filter_ignored_fails(tmp_path: Path) -> None:
    """Treating every record as a value gives 2,920 instead of 2,117."""
    t = TRUTH["sar-3-usable"]
    text = golden_usable()
    text = replace_cell(text, "n_molecules_with_value", str(t["n_molecules_any_record"]))
    text = replace_cell(text, "n_molecules_without_value", "0")
    assert score(checks.sar_usable_counts, tmp_path, {"usable.csv": text}) == 0.0


def test_usable_boundary_included_fails(tmp_path: Path) -> None:
    """`<= 100 nM` gives 835 molecules; the prompt says strictly below."""
    text = replace_cell(golden_usable(), "n_molecules_potent", "835")
    assert score(checks.sar_usable_counts, tmp_path, {"usable.csv": text}) == 0.0


def test_usable_unfiltered_potency_fails(tmp_path: Path) -> None:
    """Ignoring relation and units together gives 905 molecules."""
    text = replace_cell(golden_usable(), "n_molecules_potent", "905")
    assert score(checks.sar_usable_counts, tmp_path, {"usable.csv": text}) == 0.0


@pytest.mark.parametrize("written", ["1230000", "1230000.0", "1.23e+06", "1230000.0 nM"])
def test_usable_flagged_value_forms_pass(tmp_path: Path, written: str) -> None:
    """1,230,000 nM is the same claim however a writer formats it."""
    text = replace_cell(golden_usable(), "largest_flagged_nm", written)
    assert score(checks.sar_usable_counts, tmp_path, {"usable.csv": text}) == 1.0


# --- sar-repeats ----------------------------------------------------------

def test_repeats_runner_up_molecule_fails(tmp_path: Path) -> None:
    """The second widest spread is 3.820, so the tolerance cannot reach it."""
    t = TRUTH["sar-4-repeats"]
    text = replace_cell(golden_repeats(), "widest_spread",
                        f"{t['runner_up_spread']:.3f}")
    assert score(checks.sar_repeats_summary, tmp_path, {"repeats.csv": text}) == 0.0


def test_repeats_ratio_instead_of_log_fails(tmp_path: Path) -> None:
    """A spread reported as a concentration ratio is not log units."""
    text = replace_cell(golden_repeats(), "widest_spread", "43120.0")
    assert score(checks.sar_repeats_summary, tmp_path, {"repeats.csv": text}) == 0.0


def test_repeats_two_decimals_pass(tmp_path: Path) -> None:
    t = TRUTH["sar-4-repeats"]
    text = replace_cell(golden_repeats(), "widest_spread",
                        f"{t['widest_spread']:.2f}")
    assert score(checks.sar_repeats_summary, tmp_path, {"repeats.csv": text}) == 1.0


def test_repeats_lower_case_identifier_passes(tmp_path: Path) -> None:
    t = TRUTH["sar-4-repeats"]
    text = replace_cell(golden_repeats(), "widest_molecule",
                        t["widest_molecule"].lower())
    assert score(checks.sar_repeats_summary, tmp_path, {"repeats.csv": text}) == 1.0


# --- sar-substructure -----------------------------------------------------

def test_substructure_group_name_variants_pass(tmp_path: Path) -> None:
    """`Carboxylic Acid` and `carboxylic-acid` name the same group."""
    text = golden_substructure()
    text = text.replace("carboxylic_acid,", "Carboxylic Acid,")
    text = text.replace("halogen,", "HALOGEN,")
    assert score(checks.sar_substructure_trend, tmp_path,
                 {"substructure.csv": text}) == 1.0


def test_substructure_wrong_group_name_fails(tmp_path: Path) -> None:
    text = golden_substructure().replace("nitrile,", "cyano,")
    result = checks.sar_substructure_trend(
        artifact(tmp_path, {"substructure.csv": text}), {}
    )
    assert result.score == 0.0
    assert "nitrile" in result.evidence


def test_substructure_difference_sign_matters(tmp_path: Path) -> None:
    """Nitrile lowers the median. A positive difference reverses the claim."""
    t = TRUTH["sar-5-substructure"]["nitrile"]
    header, *rows = golden_substructure().strip().splitlines()
    flipped = [r if not r.startswith("nitrile,")
               else r.rsplit(",", 1)[0] + f",{abs(t['difference']):.3f}" for r in rows]
    assert score(checks.sar_substructure_trend, tmp_path,
                 {"substructure.csv": csv_text(header, flipped)}) == 0.0


def test_substructure_stripped_counterions_fail(tmp_path: Path) -> None:
    """Salt stripping changes two of the four groups, so the prompt forbids it.

    Seven of the 1,670 molecules are written as a salt or a mixture. Their
    counterions carry a carboxylic acid or a halogen, so an agent that
    removes them reports 55 instead of 56 and 745 instead of 748, and the
    two differences move by 0.018 and 0.028 log units, which is far more
    than the tolerance. The prompt therefore says to match the SMILES
    exactly as the file writes it. Measured on the fixture; the other three
    chemistry cases were measured too and are invariant, so only this
    prompt needed the sentence.
    """
    stripped = {"carboxylic_acid": (55, -1.3103), "halogen": (745, 0.3285)}
    header, *rows = golden_substructure().strip().splitlines()
    for group, (n_with, difference) in stripped.items():
        mutated = []
        for row in rows:
            cells = row.split(",")
            if cells[0] == group:
                cells[1] = str(n_with)
                cells[4] = f"{difference:.3f}"
            mutated.append(",".join(cells))
        text = csv_text(header, mutated)
        assert score(checks.sar_substructure_trend, tmp_path,
                     {"substructure.csv": text}) == 0.0, group


def test_substructure_duplicate_contradictory_row_fails(tmp_path: Path) -> None:
    text = golden_substructure() + "nitrile,70,7.500,6.463,1.037\n"
    result = checks.sar_substructure_trend(
        artifact(tmp_path, {"substructure.csv": text}), {}
    )
    assert result.score == 0.0
    assert "two different" in result.evidence


# --- sar-series -----------------------------------------------------------

def _rewritten_smiles(smiles: str) -> str:
    """The same molecule, written from a different starting atom."""
    from rdkit import Chem, RDLogger
    RDLogger.DisableLog("rdApp.*")
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    other = Chem.MolToSmiles(mol, rootedAtAtom=mol.GetNumAtoms() - 1, canonical=False)
    assert other != smiles
    return other


def test_series_non_canonical_scaffold_passes(tmp_path: Path) -> None:
    """The same scaffold written differently is the same scaffold."""
    t = TRUTH["sar-6-series"]
    text = replace_cell(golden_series(), "best_scaffold",
                        _rewritten_smiles(t["best_scaffold"]))
    assert score(checks.sar_series_summary, tmp_path, {"series.csv": text}) == 1.0


def test_series_scaffolds_swapped_fails(tmp_path: Path) -> None:
    """The best series by median is not the most populated one."""
    t = TRUTH["sar-6-series"]
    text = golden_series()
    text = replace_cell(text, "best_scaffold", t["largest_scaffold"])
    text = replace_cell(text, "largest_scaffold", t["best_scaffold"])
    assert score(checks.sar_series_summary, tmp_path, {"series.csv": text}) == 0.0


def test_series_structureless_molecule_missed_fails(tmp_path: Path) -> None:
    """1,671 molecules carry one value but only 1,670 carry a structure."""
    t = TRUTH["sar-6-series"]
    text = golden_series()
    text = replace_cell(text, "n_molecules", str(t["n_molecules"] + 1))
    text = replace_cell(text, "n_without_structure", "0")
    assert score(checks.sar_series_summary, tmp_path, {"series.csv": text}) == 0.0


def test_series_all_scaffolds_counted_as_series_fails(tmp_path: Path) -> None:
    """776 scaffolds are not 69 series: the 5-member rule decides."""
    t = TRUTH["sar-6-series"]
    text = replace_cell(golden_series(), "n_series", str(t["n_distinct_scaffolds"]))
    assert score(checks.sar_series_summary, tmp_path, {"series.csv": text}) == 0.0


def test_series_unparseable_scaffold_fails(tmp_path: Path) -> None:
    text = replace_cell(golden_series(), "best_scaffold", "not a smiles")
    assert score(checks.sar_series_summary, tmp_path, {"series.csv": text}) == 0.0


# --- sar-selectivity ------------------------------------------------------

def test_selectivity_mean_reported_as_median_fails(tmp_path: Path) -> None:
    """0.321 against 0.328: the tightest gap in the set, and it must fail.

    Every rounding of the mean is tested, because the tolerance has to
    reject it at 1, 2, 3 and 4 decimal places.
    """
    mean = TRUTH["sar-7-selectivity"]["mean_delta"]
    for places in (4, 3, 2, 1):
        written = f"{mean:.{places}f}"
        text = replace_cell(golden_selectivity(), "median_delta", written)
        assert score(checks.sar_selectivity_summary, tmp_path,
                     {"selectivity.csv": text}) == 0.0, written


def test_selectivity_two_decimals_pass(tmp_path: Path) -> None:
    t = TRUTH["sar-7-selectivity"]
    text = replace_cell(golden_selectivity(), "median_delta",
                        f"{t['median_delta']:.2f}")
    assert score(checks.sar_selectivity_summary, tmp_path,
                 {"selectivity.csv": text}) == 1.0


def test_selectivity_inclusive_threshold_fails(tmp_path: Path) -> None:
    """One molecule sits at exactly one log, so `>=` gives 56 not 55."""
    text = replace_cell(golden_selectivity(), "n_above_one_log", "56")
    assert score(checks.sar_selectivity_summary, tmp_path,
                 {"selectivity.csv": text}) == 0.0


def test_selectivity_percent_instead_of_fraction_fails(tmp_path: Path) -> None:
    t = TRUTH["sar-7-selectivity"]
    text = replace_cell(golden_selectivity(), "fraction_above_one_log",
                        f"{100 * t['fraction_above_one_log']:.1f}")
    assert score(checks.sar_selectivity_summary, tmp_path,
                 {"selectivity.csv": text}) == 0.0


def test_selectivity_lower_case_identifier_passes(tmp_path: Path) -> None:
    t = TRUTH["sar-7-selectivity"]
    text = replace_cell(golden_selectivity(), "most_selective",
                        t["most_selective"].lower())
    assert score(checks.sar_selectivity_summary, tmp_path,
                 {"selectivity.csv": text}) == 1.0


# --- sar-cliffs -----------------------------------------------------------

def test_cliffs_pair_in_either_order_passes(tmp_path: Path) -> None:
    t = TRUTH["sar-8-cliffs"]
    first, second = t["largest_pair"]
    text = csv_text(CLIFFS_HEADER, [row_of(
        CLIFFS_HEADER, t["n_cliff_pairs"], second, first,
        f"{t['largest_similarity']:.3f}", f"{t['largest_delta']:.3f}",
    )])
    assert score(checks.sar_cliffs_summary, tmp_path, {"cliffs.csv": text}) == 1.0


def test_cliffs_negative_delta_passes(tmp_path: Path) -> None:
    """The pair is unordered, so the sign of the difference carries nothing."""
    t = TRUTH["sar-8-cliffs"]
    text = replace_cell(golden_cliffs(), "delta_pic50", f"{-t['largest_delta']:.3f}")
    assert score(checks.sar_cliffs_summary, tmp_path, {"cliffs.csv": text}) == 1.0


def runner_up_cliff_row(n_pairs: int) -> str:
    """The second largest cliff, written as if it were the answer."""
    t = TRUTH["sar-8-cliffs"]
    first, second = t["runner_up_pair"]
    return csv_text(CLIFFS_HEADER, [row_of(
        CLIFFS_HEADER, n_pairs, first, second,
        f"{t['runner_up_similarity']:.3f}", f"{t['runner_up_delta']:.3f}",
    )])


def test_cliffs_runner_up_pair_fails(tmp_path: Path) -> None:
    """The runner-up cliff: 3.209 log units at similarity 0.817."""
    text = runner_up_cliff_row(TRUTH["sar-8-cliffs"]["n_cliff_pairs"])
    assert score(checks.sar_cliffs_summary, tmp_path, {"cliffs.csv": text}) == 0.0


def test_cliffs_boundary_pair_excluded_fails(tmp_path: Path) -> None:
    """Reading `0.8 or more` as `above 0.8` drops the winning pair.

    The winning pair sits exactly on the cut-off, so a strict reading loses
    both the pair and one from the count, and the runner-up moves up.
    """
    text = runner_up_cliff_row(TRUTH["sar-8-cliffs"]["n_cliff_pairs"] - 1)
    assert score(checks.sar_cliffs_summary, tmp_path, {"cliffs.csv": text}) == 0.0


# --- sar-multistep --------------------------------------------------------

def test_multistep_tie_break_skipped_fails(tmp_path: Path) -> None:
    """Another group shares the median with 5 members; the rule takes 7."""
    text = golden_choice()
    text = replace_cell(text, "chosen_scaffold",
                        "O=C(c1ccc(Nc2nccc(-c3cnc[nH]3)n2)cc1)N1CCCC1")
    text = replace_cell(text, "member_count", "5")
    assert score(checks.sar_multistep_choice, tmp_path, {"choice.csv": text}) == 0.0


def test_multistep_tie_count_matters(tmp_path: Path) -> None:
    """Reporting one tied group hides that the tie-break was needed."""
    text = replace_cell(golden_choice(), "n_tied_on_median", "1")
    assert score(checks.sar_multistep_choice, tmp_path, {"choice.csv": text}) == 0.0


def test_multistep_mw_tie_break_skipped_fails(tmp_path: Path) -> None:
    """CHEMBL495696 weighs the same as the winner and loses on the id.

    This is the case a real run got wrong. Both molecules are C17H11N7,
    but RDKit sums the atomic weights in atom order, so the raw doubles
    are 313.32400000000007 and 313.324. An agent that sorted the raw
    floats saw CHEMBL495696 as lighter and never reached the tie-break.
    The prompt now says to compare the weights rounded to 3 decimal
    places, so the tie is real and this answer is wrong.
    """
    text = replace_cell(golden_choice(), "chosen_compound", "CHEMBL495696")
    assert score(checks.sar_multistep_choice, tmp_path, {"choice.csv": text}) == 0.0


def test_multistep_mw_twins_really_tie_at_three_places(tmp_path: Path) -> None:
    """The answer key's tie must be a tie under the rule the prompt states.

    Guards the rule itself, not the check: if a future RDKit changed these
    weights so that they no longer round to the same 3 decimal places, the
    prompt's tie-break would never fire and the key would be arbitrary.
    """
    from rdkit import Chem, RDLogger
    from rdkit.Chem import Descriptors
    RDLogger.DisableLog("rdApp.*")

    truth = TRUTH["sar-9-multistep"]
    smiles = {
        "CHEMBL359794": "c1ccc(Nc2nccc(-c3cnn4ncccc34)n2)cc1",
        "CHEMBL495696": "c1ccc(Nc2nccc(-c3cnn4ncccc34)n2)cc1",
    }
    rows = list(csv.DictReader(
        (SET_DIR / "fixtures/cdk_activities_raw.csv").open(encoding="utf-8", newline="")
    ))
    weights = {}
    for row in rows:
        if row["molecule_chembl_id"] in smiles and row["canonical_smiles"]:
            mol = Chem.MolFromSmiles(row["canonical_smiles"])
            weights[row["molecule_chembl_id"]] = round(Descriptors.MolWt(mol), 3)
    assert set(weights) == set(smiles), weights
    assert len(set(weights.values())) == 1, f"no longer a tie: {weights}"
    assert next(iter(weights.values())) == truth["chosen_mw"]
    assert truth["n_tied_on_mw"] == 2
    assert truth["chosen_compound"] == min(weights)


def test_multistep_heavier_member_fails(tmp_path: Path) -> None:
    text = golden_choice()
    text = replace_cell(text, "chosen_compound", "CHEMBL186101")
    text = replace_cell(text, "chosen_mw", "316.368")
    assert score(checks.sar_multistep_choice, tmp_path, {"choice.csv": text}) == 0.0


def test_multistep_answer_tag(tmp_path: Path) -> None:
    chosen = TRUTH["sar-9-multistep"]["chosen_compound"]
    assert score(checks.sar_multistep_answer_tag, tmp_path, {},
                 f"<answer>{chosen}</answer>") == 1.0
    assert score(checks.sar_multistep_answer_tag, tmp_path, {},
                 f"<answer>{chosen.lower()}</answer>") == 1.0
    assert score(checks.sar_multistep_answer_tag, tmp_path, {},
                 f"the answer is {chosen}") == 0.0
    assert score(checks.sar_multistep_answer_tag, tmp_path, {},
                 "<answer>CHEMBL495696</answer>") == 0.0


def test_multistep_last_answer_tag_wins(tmp_path: Path) -> None:
    """An agent that corrects itself is judged on its final answer."""
    chosen = TRUTH["sar-9-multistep"]["chosen_compound"]
    answer = f"<answer>CHEMBL999</answer> sorry, <answer>{chosen}</answer>"
    assert score(checks.sar_multistep_answer_tag, tmp_path, {}, answer) == 1.0


# --- sar-absent -----------------------------------------------------------

@pytest.mark.parametrize("marker", ["unavailable", "N/A", "not in file", "", "none",
                                    "no data", "Unavailable."])
def test_absent_unavailable_synonyms_pass(tmp_path: Path, marker: str) -> None:
    rows = [f"{e['chembl_id']},{e['pic50']:.3f},{marker}"
            for e in TRUTH["sar-10-absent"]["top"]]
    text = csv_text("chembl_id,cdk2_pic50,herg_pic50", rows)
    assert score(checks.sar_absent_window, tmp_path, {"herg_window.csv": text}) == 1.0


def test_absent_invented_herg_value_fails(tmp_path: Path) -> None:
    text = replace_cell(golden_herg_window(), "herg_pic50", "5.2")
    result = checks.sar_absent_window(artifact(tmp_path, {"herg_window.csv": text}), {})
    assert result.score == 0.0
    assert "invented" in result.evidence


def test_absent_predicted_herg_value_fails(tmp_path: Path) -> None:
    """A hedged number is still a number the file does not hold."""
    text = replace_cell(golden_herg_window(), "herg_pic50", "~5.5 (predicted)")
    assert score(checks.sar_absent_window, tmp_path, {"herg_window.csv": text}) == 0.0


def next_ranked_row() -> str:
    t = TRUTH["sar-10-absent"]
    return f"{t['next_chembl_id']},{t['next_pic50']:.3f},unavailable"


def test_absent_wrong_top_molecules_fail(tmp_path: Path) -> None:
    """Rank 6 is not in the top 5, even with hERG correctly left out."""
    top = TRUTH["sar-10-absent"]["top"]
    rows = [f"{e['chembl_id']},{e['pic50']:.3f},unavailable" for e in top[:4]]
    rows.append(next_ranked_row())
    text = csv_text("chembl_id,cdk2_pic50,herg_pic50", rows)
    assert score(checks.sar_absent_window, tmp_path, {"herg_window.csv": text}) == 0.0


def test_absent_extra_molecule_fails(tmp_path: Path) -> None:
    text = golden_herg_window() + next_ranked_row() + "\n"
    assert score(checks.sar_absent_window, tmp_path, {"herg_window.csv": text}) == 0.0


@pytest.mark.parametrize("tag,expected", [
    ("no", 1.0),
    ("No", 1.0),
    ("no.", 1.0),
    ("none", 1.0),
    ("no, the file has no hERG column", 1.0),
    ("yes", 0.0),
    ("Yes, hERG data is present", 0.0),
    ("maybe", 0.0),
    ("", 0.0),
])
def test_absent_answer_tag(tmp_path: Path, tag: str, expected: float) -> None:
    assert score(checks.sar_absent_answer_tag, tmp_path, {},
                 f"<answer>{tag}</answer>") == expected


def test_absent_answer_tag_missing_fails(tmp_path: Path) -> None:
    assert score(checks.sar_absent_answer_tag, tmp_path, {},
                 "the file holds no hERG data") == 0.0
