"""Programmatic checks for the retrieval-and-selection eval set.

One function per case-assertion. Every expected value is read from
``fixtures/ground_truth.json``, which
``development/build_retrieval_fixtures.py`` rebuilds from UniProt, RCSB,
SIFTS and AlphaFold DB. Grading therefore needs no network and cannot
drift when a database changes.

Grading contract, applied by every check here:

* A missing file, a missing required column or an unparseable data row
  fails. Silently dropping a bad row would let a broken answer pass.
* Formatting never decides the verdict. Headers, identifiers and residue
  codes are normalised, numbers may carry units, and a residue may be
  written in one-letter or three-letter form.
* Where the prompt asks for an exact set, the check compares sets. Where
  the prompt names specific rows, the check requires those rows and
  ignores anything extra, because a superset that contains the right
  answers is still a right answer.
* Numeric tolerances only absorb the rounding the prompt asks for. They
  are always far tighter than the gap between the right answer and any
  plausible wrong one.
"""

from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from pmai_evals.legacy import PYTHON_CHECK_TYPE
from pmai_evals.legacy import RunArtifact
from pmai_evals.legacy import AssertionResult

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Values an agent may write when it means "there is nothing here".
_EMPTY_MARKERS = {"", "none", "n/a", "na", "null", "-", "--"}

_THREE_TO_ONE = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "SEC": "U", "PYL": "O",
}

_NUMBER = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
# A CSV cell must lead with its number. That accepts a trailing unit such as
# "0.90 Å" or "65.33 %" but rejects prose like "about 520", where the number
# would otherwise be lifted out of a sentence that claims something else.
_LEADING_NUMBER = re.compile(r"^[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_ANSWER_TAG = re.compile(r"<answer>(.*?)</answer>", re.IGNORECASE | re.DOTALL)


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

    Header cells are stripped and lower-cased so ``PDB_ID``, ``pdb_id``
    and `` PDB Id `` all address the same column. ``utf-8-sig`` drops the
    byte-order mark that spreadsheet exports put in front of the first
    header. Fully blank rows are dropped: writers add them and they carry
    no claim.
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


def _is_empty(value: str) -> bool:
    return value.strip().lower() in _EMPTY_MARKERS


def _number(row: dict[str, str], column: str) -> float:
    """The cell's leading number, so ``0.90 Å`` and ``0.9`` both read as 0.9."""
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


def _residue(row: dict[str, str], column: str) -> str:
    """One-letter residue code, accepting a three-letter code as well."""
    raw = _text(row, column)
    if len(raw) == 1 and raw.isalpha():
        return raw
    if raw in _THREE_TO_ONE:
        return _THREE_TO_ONE[raw]
    raise _RowError(f"{column}={raw!r} is not an amino acid code")


def _answer_tag(artifact: RunArtifact) -> str | None:
    """Contents of the last ``<answer>`` tag in the final answer."""
    matches = _ANSWER_TAG.findall(artifact.final_answer())
    return matches[-1].strip() if matches else None


def _answer_number(artifact: RunArtifact) -> float | None:
    tag = _answer_tag(artifact)
    if tag is None:
        return None
    match = _NUMBER.search(tag.replace(",", ""))
    return float(match.group()) if match else None


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


def _grade_exact_set(agent: set[Any], truth: set[Any], fmt: Any = str) -> AssertionResult:
    if agent == truth:
        return _result(1.0, f"exact match on {len(truth)} item(s)")
    return _result(0.0, _diff_evidence(agent, truth, fmt))


def _close(value: float, expected: float, tolerance: float) -> bool:
    return abs(value - expected) <= tolerance


# --- rs-uniprot -----------------------------------------------------------

def rs_uniprot_target(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff target.csv carries the MAOB accession, length and residue 397."""
    truth = _truth()["rs-uniprot"]
    rows = _read_rows(artifact, "target.csv")
    if rows is None:
        return _missing_file("target.csv")
    if not rows:
        return _no_rows("target.csv")
    missing = _require_columns(
        rows, "gene", "accession", "entry_name", "sequence_length", "residue_397"
    )
    if missing:
        return _bad_columns("target.csv", missing)

    row = rows[0]
    try:
        found = {
            "gene": _text(row, "gene"),
            "accession": _text(row, "accession"),
            "entry_name": _text(row, "entry_name"),
            "sequence_length": _integer(row, "sequence_length"),
            "residue_397": _residue(row, "residue_397"),
        }
    except _RowError as exc:
        return _result(0.0, f"target.csv: {exc}")

    expected = {
        "gene": truth["gene"],
        "accession": truth["accession"],
        "entry_name": truth["entry_name"],
        "sequence_length": truth["sequence_length"],
        "residue_397": truth["residue_397"],
    }
    wrong = [f"{k}={found[k]!r} expected {expected[k]!r}"
             for k in expected if found[k] != expected[k]]
    if wrong:
        return _result(0.0, "; ".join(wrong))
    return _result(1.0, f"{expected['accession']} {expected['entry_name']} "
                        f"len={expected['sequence_length']} r397={expected['residue_397']}")


# --- rs-ligands -----------------------------------------------------------

def rs_ligands_roles(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff ligands.csv lists both 2V5Z components with the right roles."""
    truth = _truth()["rs-ligands"]
    weights = {c["comp_id"]: c["formula_weight"] for c in truth["components"]}
    roles = truth["roles"]

    rows = _read_rows(artifact, "ligands.csv")
    if rows is None:
        return _missing_file("ligands.csv")
    if not rows:
        return _no_rows("ligands.csv")
    missing = _require_columns(rows, "het_code", "formula_weight", "role")
    if missing:
        return _bad_columns("ligands.csv", missing)

    found: dict[str, tuple[float, str]] = {}
    for row in rows:
        try:
            code = _text(row, "het_code")
            found[code] = (_number(row, "formula_weight"), _cell(row, "role").lower())
        except _RowError as exc:
            return _result(0.0, f"ligands.csv: {exc}")

    if set(found) != set(roles):
        return _result(0.0, "wrong component set: " + _diff_evidence(set(found), set(roles)))

    problems = []
    for code, (weight, role) in sorted(found.items()):
        if role != roles[code]:
            problems.append(f"{code} role={role!r} expected {roles[code]!r}")
        if not _close(weight, weights[code], 0.5):
            problems.append(f"{code} formula_weight={weight} expected {weights[code]}")
    if problems:
        return _result(0.0, "; ".join(problems))
    return _result(1.0, "FAD=cofactor and SAG=inhibitor with correct formula weights")


# --- rs-search ------------------------------------------------------------

def rs_search_structures(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff structures.csv is exactly the closed sub-ångström CA2 set."""
    truth = _truth()["rs-search"]
    expected_res = {e["pdb_id"]: e["resolution"] for e in truth["entries"]}

    rows = _read_rows(artifact, "structures.csv")
    if rows is None:
        return _missing_file("structures.csv")
    if not rows:
        return _no_rows("structures.csv")
    missing = _require_columns(rows, "pdb_id", "resolution")
    if missing:
        return _bad_columns("structures.csv", missing)

    found: dict[str, float] = {}
    for row in rows:
        try:
            found[_text(row, "pdb_id")] = _number(row, "resolution")
        except _RowError as exc:
            return _result(0.0, f"structures.csv: {exc}")

    if set(found) != set(expected_res):
        return _result(0.0, f"expected {len(expected_res)} entries, got {len(found)}: "
                            + _diff_evidence(set(found), set(expected_res)))

    wrong = [f"{pid} resolution={found[pid]} expected {expected_res[pid]}"
             for pid in sorted(expected_res)
             if not _close(found[pid], expected_res[pid], 0.005)]
    if wrong:
        return _result(0.0, "; ".join(wrong))
    return _result(1.0, f"all {len(expected_res)} entries with correct resolutions")


# --- rs-select ------------------------------------------------------------

def rs_select_choice(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff choice.csv names the tie-broken best entry and the set size."""
    truth = _truth()["rs-select"]
    rows = _read_rows(artifact, "choice.csv")
    if rows is None:
        return _missing_file("choice.csv")
    if not rows:
        return _no_rows("choice.csv")
    missing = _require_columns(rows, "pdb_id", "resolution", "n_candidates")
    if missing:
        return _bad_columns("choice.csv", missing)

    row = rows[0]
    try:
        pdb_id = _text(row, "pdb_id")
        resolution = _number(row, "resolution")
        n_candidates = _integer(row, "n_candidates")
    except _RowError as exc:
        return _result(0.0, f"choice.csv: {exc}")

    problems = []
    if pdb_id != truth["selected"]:
        reason = ("did not apply the alphabetical tie-break"
                  if pdb_id in truth["tied_at_best"] else "not the lowest resolution")
        problems.append(f"pdb_id={pdb_id} expected {truth['selected']} ({reason})")
    if not _close(resolution, truth["best_resolution"], 0.005):
        problems.append(f"resolution={resolution} expected {truth['best_resolution']}")
    if n_candidates != len(truth["candidates"]):
        problems.append(f"n_candidates={n_candidates} expected {len(truth['candidates'])}")
    if problems:
        return _result(0.0, "; ".join(problems))
    return _result(1.0, f"{truth['selected']} at {truth['best_resolution']} Å "
                        f"from {len(truth['candidates'])} candidates")


def rs_select_answer_tag(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff the answer tag holds the selected PDB id."""
    truth = _truth()["rs-select"]
    tag = _answer_tag(artifact)
    if tag is None:
        return _result(0.0, "no <answer> tag in the final answer")
    value = tag.strip().upper()
    if value != truth["selected"]:
        return _result(0.0, f"<answer>{tag}</answer> expected {truth['selected']}")
    return _result(1.0, f"<answer>{truth['selected']}</answer>")


# --- rs-numbering ---------------------------------------------------------

def rs_numbering_mapping(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff every probed 1TTR residue maps to the right UniProt position.

    Rows beyond the five the prompt names are ignored: listing the whole
    chain is a superset of the requested answer, not a wrong answer. A
    second, contradictory row for a probed residue does fail.
    """
    truth = _truth()["rs-numbering"]
    probes = {int(k): v for k, v in truth["probes"].items()}

    rows = _read_rows(artifact, "mapping.csv")
    if rows is None:
        return _missing_file("mapping.csv")
    if not rows:
        return _no_rows("mapping.csv")
    missing = _require_columns(rows, "auth_resid", "uniprot_resid", "residue")
    if missing:
        return _bad_columns("mapping.csv", missing)

    found: dict[int, tuple[int, str]] = {}
    for row in rows:
        try:
            auth = _integer(row, "auth_resid")
            if auth not in probes:
                continue
            entry = (_integer(row, "uniprot_resid"), _residue(row, "residue"))
        except _RowError as exc:
            return _result(0.0, f"mapping.csv: {exc}")
        if auth in found and found[auth] != entry:
            return _result(0.0, f"mapping.csv gives two different answers for auth_resid {auth}")
        found[auth] = entry

    absent = sorted(set(probes) - set(found))
    if absent:
        return _result(0.0, f"mapping.csv has no row for auth_resid {absent}")

    problems = []
    for auth in sorted(probes):
        want = (probes[auth]["uniprot_resid"], probes[auth]["residue"])
        if found[auth] != want:
            problems.append(f"auth {auth} -> {found[auth]} expected {want}")
    if problems:
        return _result(0.0, "; ".join(problems))
    return _result(1.0, f"all {len(probes)} probes mapped with offset +{truth['offset']}")


def rs_numbering_answer_tag(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff the answer tag gives the mutation in UniProt numbering."""
    truth = _truth()["rs-numbering"]
    expected = truth["differences"][0]
    value = _answer_number(artifact)
    if value is None:
        return _result(0.0, "no number in an <answer> tag in the final answer")
    if int(value) != expected["uniprot_resid"]:
        hint = (" (that is the PDB numbering, not UniProt)"
                if int(value) == expected["auth_resid"] else "")
        return _result(0.0, f"<answer>{value:g}</answer> expected "
                            f"{expected['uniprot_resid']}{hint}")
    return _result(1.0, f"mutation at UniProt position {expected['uniprot_resid']}")


# --- rs-identity ----------------------------------------------------------

def rs_identity_metrics(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff the CDK2/CDK1 global alignment metrics are reproduced."""
    truth = _truth()["rs-identity"]
    rows = _read_rows(artifact, "identity.csv")
    if rows is None:
        return _missing_file("identity.csv")
    if not rows:
        return _no_rows("identity.csv")
    missing = _require_columns(rows, "alignment_length", "identical_positions", "percent_identity")
    if missing:
        return _bad_columns("identity.csv", missing)

    row = rows[0]
    try:
        length = _integer(row, "alignment_length")
        identical = _integer(row, "identical_positions")
        percent = _number(row, "percent_identity")
    except _RowError as exc:
        return _result(0.0, f"identity.csv: {exc}")

    problems = []
    if length != truth["alignment_length"]:
        problems.append(f"alignment_length={length} expected {truth['alignment_length']}")
    if identical != truth["identical_positions"]:
        problems.append(f"identical_positions={identical} expected {truth['identical_positions']}")
    # Wide enough for an answer rounded to one decimal, far tighter than the
    # 0.66 point gap to the commonest wrong answer, dividing by the shorter
    # sequence instead of by the alignment length.
    if not _close(percent, truth["percent_identity"], 0.05):
        problems.append(f"percent_identity={percent} expected "
                        f"{truth['percent_identity']:.2f}")
    if problems:
        return _result(0.0, "; ".join(problems))
    return _result(1.0, f"{identical}/{length} identical = {percent}%")


# --- rs-alphafold ---------------------------------------------------------

def rs_alphafold_metrics(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff the pLDDT summary of the pinned AlphaFold model is right."""
    truth = _truth()["rs-alphafold"]
    rows = _read_rows(artifact, "metrics.csv")
    if rows is None:
        return _missing_file("metrics.csv")
    if not rows:
        return _no_rows("metrics.csv")
    missing = _require_columns(rows, "n_residues", "mean_plddt", "n_below_70")
    if missing:
        return _bad_columns("metrics.csv", missing)

    row = rows[0]
    try:
        n_residues = _integer(row, "n_residues")
        mean_plddt = _number(row, "mean_plddt")
        n_below = _integer(row, "n_below_70")
    except _RowError as exc:
        return _result(0.0, f"metrics.csv: {exc}")

    problems = []
    if n_residues != truth["n_residues"]:
        problems.append(f"n_residues={n_residues} expected {truth['n_residues']}")
    if not _close(mean_plddt, truth["mean_plddt"], 0.01):
        problems.append(f"mean_plddt={mean_plddt} expected {truth['mean_plddt']:.2f}")
    if n_below != truth["n_below_70"]:
        problems.append(f"n_below_70={n_below} expected {truth['n_below_70']}")
    if problems:
        return _result(0.0, "; ".join(problems))
    return _result(1.0, f"{n_residues} residues, mean pLDDT {mean_plddt}, "
                        f"{n_below} below 70")


# --- rs-chimera -----------------------------------------------------------

def _segment_set(segments: list[dict[str, Any]]) -> set[tuple[Any, ...]]:
    return {
        (s["accession"], s["auth_start"], s["auth_end"], s["uniprot_start"], s["uniprot_end"])
        for s in segments
    }


def rs_chimera_composition(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff composition.csv lists every 3PBL segment, fusion included.

    Two answers are accepted, because both are true: the construct span
    from SEQRES, and the span that has coordinates. They differ only in
    the receptor's first segment, whose first 30 residues were not
    modelled. What is not accepted is the sequential index SIFTS returns
    alongside the author numbering, since that is not a residue number in
    the entry.
    """
    truth = _truth()["rs-chimera"]
    variants = {
        "construct (SEQRES)": _segment_set(truth["segments"]),
        "modelled residues": _segment_set(truth["observed_segments"]),
    }

    rows = _read_rows(artifact, "composition.csv")
    if rows is None:
        return _missing_file("composition.csv")
    if not rows:
        return _no_rows("composition.csv")
    missing = _require_columns(
        rows, "accession", "auth_start", "auth_end", "uniprot_start", "uniprot_end"
    )
    if missing:
        return _bad_columns("composition.csv", missing)

    found = set()
    for row in rows:
        try:
            found.add((
                _text(row, "accession"),
                _integer(row, "auth_start"),
                _integer(row, "auth_end"),
                _integer(row, "uniprot_start"),
                _integer(row, "uniprot_end"),
            ))
        except _RowError as exc:
            return _result(0.0, f"composition.csv: {exc}")

    for label, expected in variants.items():
        if found == expected:
            return _result(1.0, f"all {len(expected)} segments correct on the "
                                f"{label} reading, fusion "
                                f"{truth['fusion_accession']} at "
                                f"{truth['fusion_auth_range'][0]}-"
                                f"{truth['fusion_auth_range'][1]}")

    def fmt(segment: tuple[Any, ...]) -> str:
        return f"{segment[0]}:{segment[1]}-{segment[2]}=>{segment[3]}-{segment[4]}"

    note = ""
    if not any(s[0] == truth["fusion_accession"] for s in found):
        note = f"; missed the {truth['fusion_accession']} fusion partner entirely"
    label, nearest = min(variants.items(), key=lambda kv: len(found ^ kv[1]))
    return _result(0.0, f"nearest reading is {label}: "
                        + _diff_evidence(found, nearest, fmt) + note)


def rs_chimera_mutations(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff mutations.csv is exactly the construct-versus-canonical diff."""
    truth = _truth()["rs-chimera"]
    expected = {
        (m["accession"], m["uniprot_resid"], m["wild_type"], m["mutant"])
        for m in truth["mutations"]
    }

    rows = _read_rows(artifact, "mutations.csv")
    if rows is None:
        return _missing_file("mutations.csv")
    if not rows:
        return _no_rows("mutations.csv")
    missing = _require_columns(rows, "accession", "uniprot_resid", "wild_type", "mutant")
    if missing:
        return _bad_columns("mutations.csv", missing)

    found = set()
    for row in rows:
        try:
            found.add((
                _text(row, "accession"),
                _integer(row, "uniprot_resid"),
                _residue(row, "wild_type"),
                _residue(row, "mutant"),
            ))
        except _RowError as exc:
            return _result(0.0, f"mutations.csv: {exc}")

    def fmt(mutation: tuple[Any, ...]) -> str:
        return f"{mutation[0]}:{mutation[2]}{mutation[1]}{mutation[3]}"

    return _grade_exact_set(found, expected, fmt)


# --- rs-classify ----------------------------------------------------------

def rs_classify_calls(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff every listed entry gets exactly its drug-like ligand set.

    ``none`` and a real HET code for the same entry contradict each
    other, so that combination fails rather than being read as either.
    """
    truth = _truth()["rs-classify"]
    expected = {pid: set(codes) for pid, codes in truth["calls"].items()}

    rows = _read_rows(artifact, "ligand_calls.csv")
    if rows is None:
        return _missing_file("ligand_calls.csv")
    if not rows:
        return _no_rows("ligand_calls.csv")
    missing = _require_columns(rows, "pdb_id", "het_code")
    if missing:
        return _bad_columns("ligand_calls.csv", missing)

    found: dict[str, set[str]] = {}
    declared_none: set[str] = set()
    for row in rows:
        try:
            pdb_id = _text(row, "pdb_id")
            code = _cell(row, "het_code")
        except _RowError as exc:
            return _result(0.0, f"ligand_calls.csv: {exc}")
        if pdb_id not in expected:
            continue
        bucket = found.setdefault(pdb_id, set())
        if _is_empty(code):
            declared_none.add(pdb_id)
        else:
            bucket.add(code.upper())

    contradictory = sorted(pid for pid in declared_none if found.get(pid))
    if contradictory:
        return _result(0.0, "ligand_calls.csv says both 'none' and a HET code for "
                            + ", ".join(contradictory))

    absent = sorted(set(expected) - set(found))
    if absent:
        return _result(0.0, f"ligand_calls.csv has no row for {absent}")

    problems = [
        f"{pid}: {sorted(found[pid]) or ['none']} expected {sorted(expected[pid]) or ['none']}"
        for pid in sorted(expected) if found[pid] != expected[pid]
    ]
    if problems:
        return _result(0.0, "; ".join(problems))
    return _result(1.0, f"all {len(expected)} entries classified correctly")


# --- rs-absent ------------------------------------------------------------

def rs_absent_result(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff the agent reports no structure and offers a real alternative.

    Naming any PDB id for a receptor that has none is the failure this
    case exists to catch, so it is reported separately from a wrong count.
    """
    truth = _truth()["rs-absent"]
    rows = _read_rows(artifact, "result.csv")
    if rows is None:
        return _missing_file("result.csv")
    if not rows:
        return _no_rows("result.csv")
    missing = _require_columns(rows, "n_structures", "best_pdb_id", "alternative")
    if missing:
        return _bad_columns("result.csv", missing)

    row = rows[0]
    try:
        n_structures = _integer(row, "n_structures")
    except _RowError as exc:
        return _result(0.0, f"result.csv: {exc}")
    best = _cell(row, "best_pdb_id")
    alternative = _cell(row, "alternative")

    problems = []
    if n_structures != truth["pdb_entry_count"]:
        problems.append(f"n_structures={n_structures} expected {truth['pdb_entry_count']}")
    if not _is_empty(best):
        problems.append(f"invented a structure: best_pdb_id={best!r}")
    if _is_empty(alternative):
        problems.append("no alternative model offered")
    elif "alphafold" not in alternative.lower() and truth["accession"] not in alternative.upper():
        problems.append(f"alternative={alternative!r} does not name an AlphaFold model")
    if problems:
        return _result(0.0, "; ".join(problems))
    return _result(1.0, f"reported 0 structures for {truth['gene']} and offered "
                        f"{alternative!r}")


def rs_absent_answer_tag(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    """Pass iff the answer tag reports zero matching PDB entries."""
    truth = _truth()["rs-absent"]
    value = _answer_number(artifact)
    if value is None:
        return _result(0.0, "no number in an <answer> tag in the final answer")
    if int(value) != truth["pdb_entry_count"]:
        return _result(0.0, f"<answer>{value:g}</answer> expected "
                            f"{truth['pdb_entry_count']}")
    return _result(1.0, f"<answer>{truth['pdb_entry_count']}</answer>")
