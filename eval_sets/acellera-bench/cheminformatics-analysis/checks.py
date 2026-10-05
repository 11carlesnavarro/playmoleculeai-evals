"""Programmatic checks for the cheminformatics-analysis eval set.

One function per case-assertion. Every expected value is read from
``fixtures/ground_truth.json``, which
``development/build_sar_ground_truth.py`` derives from the frozen fixtures
that the cases load into the workspace. The agent and the check therefore
work from the same bytes: grading needs no network and no expected answer
can drift.

The input is the raw ChEMBL export, so the answers depend on handling
censored relations, units other than nM, missing values, repeat
measurements and one molecule with no structure. Each question is shaped so
that the exact answer survives every legitimate choice, which is what lets
these checks stay exact without failing a correct agent.

Grading contract, applied by every check here:

* A missing file, a missing required column or an unparseable data row
  fails. Silently dropping a bad row would let a broken answer pass.
* Formatting never decides the verdict. Headers, identifiers and group
  names are normalised, numbers may carry units, and a scaffold may be
  written in any SMILES form of the same molecule.
* Where the prompt asks for an exact set, the check compares sets.
* Numeric tolerances only absorb the rounding the prompt asks for. Each
  one is smaller than the gap to the nearest wrong answer, and the comment
  beside it names that gap.
"""

from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from pmai_evals.grading.assertions import PYTHON_CHECK_TYPE
from pmai_evals.runner.artifacts import RunArtifact
from pmai_evals.schemas import AssertionResult

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Values an agent may write when it means "there is nothing here".
_EMPTY_MARKERS = {"", "none", "n/a", "na", "null", "-", "--", "nan"}
# Words an agent may write for a value the input file does not hold. The
# trick case accepts any of them, and nothing else.
_UNAVAILABLE = {
    "unavailable", "not available", "not applicable", "no data",
    "no data in file", "missing", "not in file", "not in the file",
    "absent", "unknown", "no herg data",
}

_NUMBER = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
# A CSV cell must lead with its number. That accepts a trailing unit such as
# "313.324 Da" but rejects prose like "about 520", where the number would
# otherwise be lifted out of a sentence that claims something else.
_LEADING_NUMBER = re.compile(r"^[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_ANSWER_TAG = re.compile(r"<answer>(.*?)</answer>", re.IGNORECASE | re.DOTALL)

# Rounding tolerances. Each prompt states the number of decimal places it
# wants, and the fixture stores 4. These tolerances accept the asked
# rounding and one decimal less, because an agent that computed the value
# correctly and wrote 0.33 instead of 0.328 is right about the chemistry.
#
# Nothing wrong fits inside them. The tightest gap in the set is 0.0067,
# between the median delta of sar-selectivity (0.328) and its mean
# (0.3213), which is the commonest wrong answer for that cell; the mean
# stays outside the tolerance at every rounding, 0.3213, 0.321, 0.32 and
# 0.3. The next tightest is 0.0167, between the winning cliff's Tanimoto
# similarity (0.8) and the runner-up's (0.8167). Every other pair of a
# right and a wrong answer here is more than 0.1 apart.
_TOL_3DP = 0.0055
_TOL_2DP = 0.055
# A value copied straight out of the fixture, where the prompt asks for no
# rounding at all. Wide enough for an agent that rounds to one decimal, and
# the nearest wrong answer for any such cell is more than 10 units away.
_COPIED_TOLERANCE = 0.06


class _RowError(ValueError):
    """A data row that cannot be read the way the prompt specified."""


# --- results --------------------------------------------------------------

def _result(score: float | bool, evidence: str) -> AssertionResult:
    return AssertionResult(
        assertion_type=PYTHON_CHECK_TYPE,
        score=float(score),
        evidence=evidence,
        config={},
    )


@lru_cache(maxsize=1)
def _truth() -> dict[str, Any]:
    with (FIXTURES / "ground_truth.json").open(encoding="utf-8") as handle:
        return json.load(handle)


# --- reading agent output -------------------------------------------------

def _delimiter(header_line: str) -> str:
    """Comma unless the header clearly uses semicolons or tabs instead.

    Some writers emit a semicolon- or tab-separated file under a ``.csv``
    name. Reading it as one wide column would fail a correct answer for a
    reason that has nothing to do with the science.
    """
    if "," in header_line:
        return ","
    for candidate in (";", "\t"):
        if candidate in header_line:
            return candidate
    return ","


def _read_rows(artifact: RunArtifact, filename: str) -> list[dict[str, str]] | None:
    """Data rows of an agent CSV with normalised headers, or None if absent.

    Header cells are stripped and lower-cased so ``CHEMBL_ID``,
    ``chembl_id`` and `` ChEMBL Id `` all address the same column.
    ``utf-8-sig`` drops the byte-order mark that spreadsheet exports put in
    front of the first header. Fully blank rows are dropped: writers add
    them and they carry no claim.
    """
    path = artifact.project_files_dir / filename
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    first_line = text.splitlines()[0] if text.strip() else ""
    reader = csv.DictReader(text.splitlines(True), delimiter=_delimiter(first_line))
    if reader.fieldnames is None:
        return []
    headers = [(name or "").strip().lower().replace(" ", "_") for name in reader.fieldnames]
    rows = []
    for raw in reader:
        row = {}
        for header, key in zip(headers, reader.fieldnames, strict=True):
            value = raw.get(key)
            row[header] = "" if value is None else str(value).strip()
        if any(row.values()):
            rows.append(row)
    return rows


def _require_columns(rows: list[dict[str, str]], *columns: str) -> str | None:
    """Name the first required column that no row provides, else None."""
    present = set(rows[0]) if rows else set()
    missing = [c for c in columns if c not in present]
    return ", ".join(missing) if missing else None


def _cell(row: dict[str, str], column: str) -> str:
    value = row.get(column)
    if value is None:
        raise _RowError(f"column {column!r} missing")
    return value.strip()


def _text(row: dict[str, str], column: str) -> str:
    return _cell(row, column).upper()


def _label(row: dict[str, str], column: str) -> str:
    """A name written for a human, reduced to one comparable form."""
    return re.sub(r"[\s\-]+", "_", _cell(row, column).lower())


def _is_empty(value: str) -> bool:
    return value.strip().lower() in _EMPTY_MARKERS


def _number(row: dict[str, str], column: str) -> float:
    """The cell's leading number, so ``313.324 Da`` and ``313.324`` agree."""
    raw = _cell(row, column)
    match = _LEADING_NUMBER.match(raw.replace(",", ""))
    if match is None:
        raise _RowError(f"{column}={raw!r} is not a number")
    return float(match.group())


def _integer(row: dict[str, str], column: str) -> int:
    value = _number(row, column)
    if value != int(value):
        raise _RowError(f"{column}={value!r} is not a whole number")
    return int(value)


def _answer_tag(artifact: RunArtifact) -> str | None:
    """Contents of the last ``<answer>`` tag in the final answer."""
    matches = _ANSWER_TAG.findall(artifact.final_answer())
    return matches[-1].strip() if matches else None


def _same_smiles(written: str, expected: str) -> bool:
    """True when both strings name the same molecule.

    The prompt asks for the SMILES that RDKit's Murcko implementation
    returns, so the strings normally match byte for byte. They are
    canonicalised anyway, because a different RDKit build or another
    toolkit can write the same scaffold differently, and that is a
    formatting difference, not a wrong answer.

    Stereochemistry is dropped, which is the convention the prompt states
    and the one ``MurckoScaffoldSmiles`` applies by default. An agent that
    kept it would otherwise be failed for the same skeleton.
    """
    if written == expected:
        return True
    try:
        from rdkit import Chem, RDLogger
    except ImportError:  # pragma: no cover - RDKit is installed in the venv
        return False
    RDLogger.DisableLog("rdApp.*")
    left = Chem.MolFromSmiles(written)
    right = Chem.MolFromSmiles(expected)
    if left is None or right is None:
        return False
    return (Chem.MolToSmiles(left, isomericSmiles=False)
            == Chem.MolToSmiles(right, isomericSmiles=False))


# --- grading helpers ------------------------------------------------------

def _missing_file(filename: str) -> AssertionResult:
    return _result(0.0, f"{filename} not found in project workspace")


def _bad_columns(filename: str, missing: str) -> AssertionResult:
    return _result(0.0, f"{filename} is missing required column(s): {missing}")


def _no_rows(filename: str) -> AssertionResult:
    return _result(0.0, f"{filename} has no data rows")


def _diff_evidence(agent: set[Any], truth: set[Any], fmt: Any = str) -> str:
    missing = sorted(truth - agent, key=str)
    extra = sorted(agent - truth, key=str)
    return (f"missing=[{', '.join(fmt(x) for x in missing)}] "
            f"extra=[{', '.join(fmt(x) for x in extra)}]")


def _close(value: float, expected: float, tolerance: float) -> bool:
    return abs(value - expected) <= tolerance


def _one_row(
    artifact: RunArtifact, filename: str, *columns: str
) -> tuple[dict[str, str], None] | tuple[None, AssertionResult]:
    """The first data row of a one-row answer file, or the failure to report."""
    rows = _read_rows(artifact, filename)
    if rows is None:
        return None, _missing_file(filename)
    if not rows:
        return None, _no_rows(filename)
    missing = _require_columns(rows, *columns)
    if missing:
        return None, _bad_columns(filename, missing)
    return rows[0], None


def _compare(
    found: dict[str, Any], expected: dict[str, Any], tolerances: dict[str, float]
) -> list[str]:
    """Every field of a row that disagrees with the expected value."""
    problems = []
    for field, want in expected.items():
        got = found[field]
        if field in tolerances:
            if not _close(float(got), float(want), tolerances[field]):
                problems.append(f"{field}={got} expected {want}")
        elif got != want:
            problems.append(f"{field}={got!r} expected {want!r}")
    return problems


def _agrees(
    first: dict[str, Any], second: dict[str, Any], tolerances: dict[str, float]
) -> bool:
    """True when two rows written for the same key make the same claim.

    Repeating a row repeats a claim, so it is accepted. Writing two
    different values for the same key is a contradiction, and the check
    must not pick the one it likes.
    """
    return not _compare(first, second, tolerances)


def _counts_case(
    artifact: RunArtifact,
    filename: str,
    truth_key: str,
    columns: tuple[str, ...],
    tolerances: dict[str, float] | None = None,
    mapping: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], AssertionResult | None]:
    """Read a one-row answer of whole numbers and compare it to the truth.

    ``mapping`` renames a column when the prompt and the fixture use
    different words for the same value.
    """
    truth = _truth()[truth_key]
    tolerances = tolerances or {}
    row, failure = _one_row(artifact, filename, *columns)
    if failure is not None:
        return {}, {}, failure
    assert row is not None

    found: dict[str, Any] = {}
    try:
        for column in columns:
            found[column] = (_number(row, column) if column in tolerances
                             else _integer(row, column))
    except _RowError as exc:
        return {}, {}, _result(0.0, f"{filename}: {exc}")

    expected = {c: truth[(mapping or {}).get(c, c)] for c in columns}
    return found, expected, None


# --- sar-census -----------------------------------------------------------

def sar_census(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff census.csv counts records, molecules and targets correctly.

    The file holds 7,752 records for 5,037 molecules, so an agent that
    counts rows where the prompt says molecules cannot pass.
    """
    columns = ("n_records", "n_molecules", "n_targets", "n_ic50_records",
               "n_ki_records", "n_exact_relation", "n_not_in_nm",
               "n_missing_value")
    found, expected, failure = _counts_case(
        artifact, "census.csv", "sar-1-census", columns
    )
    if failure is not None:
        return failure

    problems = _compare(found, expected, {})
    if problems:
        return _result(0.0, "; ".join(problems))
    return _result(1.0, f"{expected['n_records']} records for "
                        f"{expected['n_molecules']} molecules, "
                        f"{expected['n_exact_relation']} with an exact relation")


# --- sar-descriptors ------------------------------------------------------

def sar_descriptors_properties(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff properties.csv holds all six descriptors for all four drugs."""
    truth = _truth()["sar-2-descriptors"]
    columns = ("name", "mw", "clogp", "tpsa", "hbd", "hba", "rotatable_bonds")
    rows = _read_rows(artifact, "properties.csv")
    if rows is None:
        return _missing_file("properties.csv")
    if not rows:
        return _no_rows("properties.csv")
    missing = _require_columns(rows, *columns)
    if missing:
        return _bad_columns("properties.csv", missing)

    # MolWt and MolLogP to 3 decimals, TPSA to 2, as the prompt asks. The
    # nearest wrong answer for any of these is at least 0.19 away, from a
    # different molecule of the same series.
    tolerances = {"mw": _TOL_3DP, "clogp": _TOL_3DP, "tpsa": _TOL_2DP}

    found: dict[str, dict[str, float]] = {}
    for row in rows:
        try:
            name = _label(row, "name")
            values = {
                "mw": _number(row, "mw"),
                "clogp": _number(row, "clogp"),
                "tpsa": _number(row, "tpsa"),
                "hbd": _integer(row, "hbd"),
                "hba": _integer(row, "hba"),
                "rotatable_bonds": _integer(row, "rotatable_bonds"),
            }
        except _RowError as exc:
            return _result(0.0, f"properties.csv: {exc}")
        if name in found and not _agrees(found[name], values, tolerances):
            return _result(0.0, f"properties.csv gives two different rows for {name!r}")
        found[name] = values

    if set(found) != set(truth):
        return _result(0.0, "wrong molecule set: " + _diff_evidence(set(found), set(truth)))

    problems = []
    for name in sorted(truth):
        expected = {key: truth[name][key] for key in
                    ("mw", "clogp", "tpsa", "hbd", "hba", "rotatable_bonds")}
        problems += [f"{name}: {p}" for p in _compare(found[name], expected, tolerances)]
    if problems:
        return _result(0.0, "; ".join(problems))
    return _result(1.0, f"all six descriptors correct for {len(truth)} molecules")


# --- sar-usable -----------------------------------------------------------

def sar_usable_counts(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff usable.csv separates the molecules that carry a real value.

    2,920 molecules have a CDK2 IC50 record and only 2,117 of them carry a
    value that is not censored, so an agent that ignores
    ``standard_relation`` or ``standard_units`` reports the wrong number.
    """
    columns = ("n_molecules_any_record", "n_molecules_with_value",
               "n_molecules_without_value", "n_molecules_potent",
               "n_flagged_records", "largest_flagged_nm")
    # The flagged value is copied out of the file, where it is 1230000.0 nM.
    tolerances = {"largest_flagged_nm": _COPIED_TOLERANCE}
    found, expected, failure = _counts_case(
        artifact, "usable.csv", "sar-3-usable", columns, tolerances
    )
    if failure is not None:
        return failure

    problems = _compare(found, expected, tolerances)
    if problems:
        return _result(0.0, "; ".join(problems))
    return _result(1.0, f"{expected['n_molecules_with_value']} of "
                        f"{expected['n_molecules_any_record']} molecules carry a "
                        f"real value, {expected['n_molecules_potent']} below "
                        f"{_truth()['sar-3-usable']['potent_below_nm']:g} nM")


# --- sar-repeats ----------------------------------------------------------

def sar_repeats_summary(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff repeats.csv finds the molecule that disagrees most with itself.

    The widest spread is 4.635 log units over 45 records, and the runner-up
    is 3.820, so the tolerance cannot confuse them.
    """
    truth = _truth()["sar-4-repeats"]
    columns = ("n_measured_once", "n_measured_more_than_once", "widest_molecule",
               "widest_spread", "widest_record_count")
    row, failure = _one_row(artifact, "repeats.csv", *columns)
    if failure is not None:
        return failure
    assert row is not None

    try:
        found = {
            "n_measured_once": _integer(row, "n_measured_once"),
            "n_measured_more_than_once": _integer(row, "n_measured_more_than_once"),
            "widest_molecule": _text(row, "widest_molecule"),
            "widest_spread": _number(row, "widest_spread"),
            "widest_record_count": _integer(row, "widest_record_count"),
        }
    except _RowError as exc:
        return _result(0.0, f"repeats.csv: {exc}")

    expected = {
        "n_measured_once": truth["n_molecules_measured_once"],
        "n_measured_more_than_once": truth["n_molecules_measured_more_than_once"],
        "widest_molecule": truth["widest_molecule"],
        "widest_spread": truth["widest_spread"],
        "widest_record_count": truth["widest_record_count"],
    }
    problems = _compare(found, expected, {"widest_spread": _TOL_3DP})
    if problems:
        return _result(0.0, "; ".join(problems))
    return _result(1.0, f"{truth['n_molecules_measured_once']} measured once, "
                        f"{truth['widest_molecule']} spreads "
                        f"{truth['widest_spread']} log units over "
                        f"{truth['widest_record_count']} records")


# --- sar-substructure -----------------------------------------------------

def sar_substructure_trend(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff substructure.csv holds the right trend for all four groups."""
    truth = _truth()["sar-5-substructure"]
    columns = ("group", "n_with", "median_with", "median_without", "difference")
    rows = _read_rows(artifact, "substructure.csv")
    if rows is None:
        return _missing_file("substructure.csv")
    if not rows:
        return _no_rows("substructure.csv")
    missing = _require_columns(rows, *columns)
    if missing:
        return _bad_columns("substructure.csv", missing)

    tolerances = dict.fromkeys(
        ("median_with", "median_without", "difference"), _TOL_3DP
    )

    found: dict[str, dict[str, float]] = {}
    for row in rows:
        try:
            group = _label(row, "group")
            values = {
                "n_with": _integer(row, "n_with"),
                "median_with": _number(row, "median_with"),
                "median_without": _number(row, "median_without"),
                "difference": _number(row, "difference"),
            }
        except _RowError as exc:
            return _result(0.0, f"substructure.csv: {exc}")
        if group in found and not _agrees(found[group], values, tolerances):
            return _result(0.0, f"substructure.csv gives two different rows for {group!r}")
        found[group] = values

    if set(found) != set(truth):
        return _result(0.0, "wrong group set: " + _diff_evidence(set(found), set(truth)))

    problems = []
    for group in sorted(truth):
        expected = {key: truth[group][key] for key in
                    ("n_with", "median_with", "median_without", "difference")}
        problems += [f"{group}: {p}" for p in _compare(found[group], expected, tolerances)]
    if problems:
        return _result(0.0, "; ".join(problems))
    return _result(1.0, f"all {len(truth)} groups correct, sulfonamide "
                        f"{truth['sulfonamide']['difference']:+.3f} log units")


# --- sar-series -----------------------------------------------------------

def sar_series_summary(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff series.csv counts the scaffolds and names the two winners.

    ``n_without_structure`` is 1: the export really holds a molecule with a
    usable potency value and no structure, and an agent that never noticed
    it reports 1,671 molecules where 1,670 have a scaffold.
    """
    truth = _truth()["sar-6-series"]
    columns = ("n_molecules", "n_without_structure", "n_distinct_scaffolds",
               "n_series", "best_scaffold", "best_count", "best_median_pic50",
               "largest_scaffold", "largest_count")
    row, failure = _one_row(artifact, "series.csv", *columns)
    if failure is not None:
        return failure
    assert row is not None

    try:
        found = {
            "n_molecules": _integer(row, "n_molecules"),
            "n_without_structure": _integer(row, "n_without_structure"),
            "n_distinct_scaffolds": _integer(row, "n_distinct_scaffolds"),
            "n_series": _integer(row, "n_series"),
            "best_count": _integer(row, "best_count"),
            "best_median_pic50": _number(row, "best_median_pic50"),
            "largest_count": _integer(row, "largest_count"),
        }
        best_scaffold = _cell(row, "best_scaffold")
        largest_scaffold = _cell(row, "largest_scaffold")
    except _RowError as exc:
        return _result(0.0, f"series.csv: {exc}")

    expected = {key: truth[key] for key in
                ("n_molecules", "n_without_structure", "n_distinct_scaffolds",
                 "n_series", "best_count", "largest_count", "best_median_pic50")}
    problems = _compare(found, expected, {"best_median_pic50": _TOL_3DP})
    if not _same_smiles(best_scaffold, truth["best_scaffold"]):
        problems.append(f"best_scaffold={best_scaffold!r} expected "
                        f"{truth['best_scaffold']!r}")
    if not _same_smiles(largest_scaffold, truth["largest_scaffold"]):
        problems.append(f"largest_scaffold={largest_scaffold!r} expected "
                        f"{truth['largest_scaffold']!r}")
    if problems:
        return _result(0.0, "; ".join(problems))
    return _result(1.0, f"{truth['n_series']} series of "
                        f"{truth['n_distinct_scaffolds']} scaffolds over "
                        f"{truth['n_molecules']} molecules, best median "
                        f"{truth['best_median_pic50']}, largest group "
                        f"{truth['largest_count']}")


# --- sar-selectivity ------------------------------------------------------

def sar_selectivity_summary(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff selectivity.csv holds the CDK2 against CDK1 comparison."""
    truth = _truth()["sar-7-selectivity"]
    columns = ("n_cdk2_once", "n_cdk1_once", "n_shared", "median_delta",
               "n_above_one_log", "fraction_above_one_log", "most_selective",
               "most_selective_delta")
    row, failure = _one_row(artifact, "selectivity.csv", *columns)
    if failure is not None:
        return failure
    assert row is not None

    try:
        found = {
            "n_cdk2_once": _integer(row, "n_cdk2_once"),
            "n_cdk1_once": _integer(row, "n_cdk1_once"),
            "n_shared": _integer(row, "n_shared"),
            "median_delta": _number(row, "median_delta"),
            "n_above_one_log": _integer(row, "n_above_one_log"),
            "fraction_above_one_log": _number(row, "fraction_above_one_log"),
            "most_selective": _text(row, "most_selective"),
            "most_selective_delta": _number(row, "most_selective_delta"),
        }
    except _RowError as exc:
        return _result(0.0, f"selectivity.csv: {exc}")

    expected = {key: truth[key] for key in columns}
    tolerances = dict.fromkeys(
        ("median_delta", "fraction_above_one_log", "most_selective_delta"),
        _TOL_3DP,
    )
    problems = _compare(found, expected, tolerances)
    if problems:
        return _result(0.0, "; ".join(problems))
    return _result(1.0, f"{truth['n_shared']} molecules measured once on both, "
                        f"median delta {truth['median_delta']}, "
                        f"{truth['n_above_one_log']} above one log")


# --- sar-cliffs -----------------------------------------------------------

def sar_cliffs_summary(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff cliffs.csv counts the cliffs and describes the largest one.

    The two ids are compared as an unordered pair, because the prompt calls
    the pair unordered.
    """
    truth = _truth()["sar-8-cliffs"]
    columns = ("n_pairs", "chembl_id_1", "chembl_id_2", "similarity", "delta_pic50")
    row, failure = _one_row(artifact, "cliffs.csv", *columns)
    if failure is not None:
        return failure
    assert row is not None

    try:
        n_pairs = _integer(row, "n_pairs")
        pair = frozenset({_text(row, "chembl_id_1"), _text(row, "chembl_id_2")})
        similarity = _number(row, "similarity")
        delta = _number(row, "delta_pic50")
    except _RowError as exc:
        return _result(0.0, f"cliffs.csv: {exc}")

    expected_pair = frozenset(truth["largest_pair"])
    problems = []
    if n_pairs != truth["n_cliff_pairs"]:
        problems.append(f"n_pairs={n_pairs} expected {truth['n_cliff_pairs']}")
    if pair != expected_pair:
        problems.append(f"pair={sorted(pair)} expected {sorted(expected_pair)}")
    if not _close(similarity, truth["largest_similarity"], _TOL_3DP):
        problems.append(f"similarity={similarity} expected {truth['largest_similarity']}")
    if not _close(abs(delta), truth["largest_delta"], _TOL_3DP):
        problems.append(f"delta_pic50={delta} expected {truth['largest_delta']}")
    if problems:
        return _result(0.0, "; ".join(problems))
    return _result(1.0, f"{truth['n_cliff_pairs']} cliffs, largest "
                        f"{sorted(expected_pair)} at delta {truth['largest_delta']}")


# --- sar-multistep --------------------------------------------------------

def sar_multistep_choice(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff choice.csv reports every step, tie-break included.

    Four groups share the highest median, so ``n_tied_on_median`` and the
    chosen scaffold together show whether the agent applied the stated
    tie-break or just took the first group it found.
    """
    truth = _truth()["sar-9-multistep"]
    columns = ("n_kept", "n_series", "best_median_pic50", "n_tied_on_median",
               "chosen_scaffold", "member_count", "chosen_compound", "chosen_mw")
    row, failure = _one_row(artifact, "choice.csv", *columns)
    if failure is not None:
        return failure
    assert row is not None

    try:
        found = {
            "n_kept": _integer(row, "n_kept"),
            "n_series": _integer(row, "n_series"),
            "best_median_pic50": _number(row, "best_median_pic50"),
            "n_tied_on_median": _integer(row, "n_tied_on_median"),
            "member_count": _integer(row, "member_count"),
            "chosen_compound": _text(row, "chosen_compound"),
            "chosen_mw": _number(row, "chosen_mw"),
        }
        chosen_scaffold = _cell(row, "chosen_scaffold")
    except _RowError as exc:
        return _result(0.0, f"choice.csv: {exc}")

    expected = {key: truth[key] for key in
                ("n_kept", "n_series", "best_median_pic50", "n_tied_on_median",
                 "member_count", "chosen_compound", "chosen_mw")}
    tolerances = {"best_median_pic50": _TOL_3DP, "chosen_mw": _TOL_3DP}
    problems = _compare(found, expected, tolerances)
    if not _same_smiles(chosen_scaffold, truth["chosen_scaffold"]):
        problems.append(f"chosen_scaffold={chosen_scaffold!r} expected "
                        f"{truth['chosen_scaffold']!r}")
    if problems:
        return _result(0.0, "; ".join(problems))
    return _result(1.0, f"{truth['n_kept']} kept, {truth['n_series']} series, "
                        f"{truth['n_tied_on_median']} tied on the median, chose "
                        f"{truth['chosen_compound']} at {truth['chosen_mw']} Da")


def sar_multistep_answer_tag(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff the answer tag holds the chosen ChEMBL id."""
    truth = _truth()["sar-9-multistep"]
    tag = _answer_tag(artifact)
    if tag is None:
        return _result(0.0, "no <answer> tag in the final answer")
    value = tag.strip().upper()
    if value != truth["chosen_compound"]:
        return _result(0.0, f"<answer>{tag}</answer> expected {truth['chosen_compound']}")
    return _result(1.0, f"<answer>{truth['chosen_compound']}</answer>")


# --- sar-absent -----------------------------------------------------------

def _unavailable(value: str) -> bool:
    """True when a cell says the value is not in the file."""
    text = value.strip().lower().rstrip(".")
    return _is_empty(text) or text in _UNAVAILABLE


def sar_absent_window(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff the five most potent molecules are right and no hERG invented.

    The file holds no hERG data at all. The part of the question the file
    can answer is graded too, so an agent that writes nothing does not pass
    by saying nothing.
    """
    truth = _truth()["sar-10-absent"]
    expected = {entry["chembl_id"]: entry["pic50"] for entry in truth["top"]}

    rows = _read_rows(artifact, "herg_window.csv")
    if rows is None:
        return _missing_file("herg_window.csv")
    if not rows:
        return _no_rows("herg_window.csv")
    missing = _require_columns(rows, "chembl_id", "cdk2_pic50", "herg_pic50")
    if missing:
        return _bad_columns("herg_window.csv", missing)

    found: dict[str, float] = {}
    invented: list[str] = []
    for row in rows:
        try:
            chembl_id = _text(row, "chembl_id")
            found[chembl_id] = _number(row, "cdk2_pic50")
            herg = _cell(row, "herg_pic50")
        except _RowError as exc:
            return _result(0.0, f"herg_window.csv: {exc}")
        if not _unavailable(herg):
            invented.append(f"{chembl_id} herg_pic50={herg!r}")

    if invented:
        return _result(0.0, "invented hERG data that the file does not hold: "
                            + "; ".join(invented))
    if set(found) != set(expected):
        return _result(0.0, f"expected the {truth['top_n']} most potent molecules: "
                            + _diff_evidence(set(found), set(expected)))
    wrong = [f"{cid} cdk2_pic50={found[cid]} expected {expected[cid]}"
             for cid in sorted(expected)
             if not _close(found[cid], expected[cid], _TOL_3DP)]
    if wrong:
        return _result(0.0, "; ".join(wrong))
    return _result(1.0, f"the {truth['top_n']} most potent molecules, with hERG "
                        f"reported as unavailable")


def sar_absent_answer_tag(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff the answer tag says the file holds no hERG data."""
    tag = _answer_tag(artifact)
    if tag is None:
        return _result(0.0, "no <answer> tag in the final answer")
    value = tag.strip().lower().lstrip("*").strip()
    if re.match(r"^(no|none|false|n)\b", value) or value in {"no", "n", "none", "false"}:
        return _result(1.0, f"<answer>{tag.strip()}</answer>: no hERG data claimed")
    if re.match(r"^(yes|true|y)\b", value):
        return _result(0.0, f"<answer>{tag.strip()}</answer> claims the file holds hERG "
                            f"data; it holds none")
    return _result(0.0, f"<answer>{tag.strip()}</answer> is neither yes nor no")
