"""Programmatic checks for the md-simulation eval set.

Shared helpers below; per-case sections (separated by banner comments)
are added one at a time as cases land. Vocabulary matches the on-disk
layout of ``systembuilder`` builds (``build_<N>/structure.pdb``,
``ff*_leaprc.<kind>.<name>``, ``systemBuilder.csv``) and ``simplerun``
runs (``equilibration/``, ``production/``, ``output.xtc``, ``log.txt``).
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from pmai_evals.grading.assertions import PYTHON_CHECK_TYPE
from pmai_evals.runner.artifacts import RunArtifact
from pmai_evals.schemas import AssertionResult


# --- constants -----------------------------------------------------------

_FF_FILE_RE = re.compile(r"^ff(\d+)_leaprc\.(?P<rest>.+)$")
_LIG_FF_DIR_NAMES = ("GAFF", "GAFF2", "CGenFF")
_MD_TRAJ_NAME = "output.xtc"
_MD_LOG_NAME = "log.txt"
_TRACEBACK_MARKERS = ("Traceback", "particle coordinate is nan", "Particle position is NaN")

# Residue-name sets used to classify what the built system actually contains.
# Systembuilder sources every available leaprc unconditionally in tleap.in,
# so the only reliable "is X really in the system" signal is the residue
# composition of structure.pdb (or the row in systemBuilder.csv).
_STANDARD_AA = frozenset({
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
    "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
    # Protonation / disulfide variants
    "HID", "HIE", "HIP", "ASH", "GLH", "CYX", "CYM", "LYN",
    # N- and C-terminal caps
    "ACE", "NME", "NHE", "NMA",
})
_NUCLEIC = frozenset({
    "DA", "DT", "DG", "DC", "DU",
    "A", "T", "G", "C", "U",
    "RA", "RU", "RG", "RC", "RT",
})
_WATER = frozenset({"WAT", "HOH", "TIP3", "TIP", "T3P", "SPC", "TP4", "TIP4"})
_IONS = frozenset({
    "NA", "NA+", "SOD", "CL", "CL-", "CLA", "K", "K+", "POT",
    "MG", "MG2", "ZN", "ZN2", "CA", "CA2", "FE", "CU", "LI",
})
_LIPIDS = frozenset({
    "POPC", "POPE", "POPS", "POPG", "POPI", "POPA",
    "DOPC", "DOPE", "DOPS", "DPPC", "DLPC", "DMPC", "DSPC",
    "CHL", "CHL1", "CHOL", "SDPC", "DAPC", "SAPI", "TIP4PEW",
})
_BUILD_NON_LIGAND = _STANDARD_AA | _NUCLEIC | _WATER | _IONS


# --- result helpers ------------------------------------------------------

def _result(score: float | bool, evidence: str) -> AssertionResult:
    return AssertionResult(
        assertion_type=PYTHON_CHECK_TYPE,
        score=float(score),
        evidence=evidence,
        config={},
    )


# --- build-dir discovery -------------------------------------------------

def _find_build_dirs(artifact: RunArtifact) -> list[Path]:
    """Every ``systembuilder*/build_<N>/`` dir inside ``project_files/``."""
    root = artifact.project_files_dir
    if not root.is_dir():
        return []
    builds: list[Path] = []
    for path in root.rglob("build_*"):
        if path.is_dir() and (path / "structure.pdb").is_file():
            builds.append(path)
    return sorted(builds)


def _latest_build_dir(artifact: RunArtifact) -> Path | None:
    """The highest-N ``build_<N>/`` directory, or ``None`` if no build exists."""
    builds = _find_build_dirs(artifact)
    return builds[-1] if builds else None


# --- force-field marker parsing ------------------------------------------

def _ff_markers(build_dir: Path) -> dict[str, str]:
    """Map ``leaprc`` kind to chosen force-field name.

    Two filename forms appear in ``build_<N>/``:

    * ``ff*_leaprc.<kind>.<name>`` → ``out[kind] = name``
      (e.g. ``protein.ff14SB``, ``water.tip3p``, ``RNA.OL3``).
    * ``ff*_leaprc.<single>`` → ``out[single] = single``
      (e.g. ``lipid21``, ``gaff2``).

    Keys are lowercased; values keep original casing.
    """
    out: dict[str, str] = {}
    for child in build_dir.iterdir():
        match = _FF_FILE_RE.match(child.name)
        if match is None:
            continue
        rest = match.group("rest")
        if "." in rest:
            kind, _, name = rest.partition(".")
            out[kind.lower()] = name
        else:
            out[rest.lower()] = rest
    return out


def _has_protein_ff(build_dir: Path, name: str) -> bool:
    """The sourced protein leaprc matches ``name`` (ff14SB / ff19SB / ...).

    Protein is always loaded as the solute, so the sourced protein
    leaprc is the FF that was actually applied.
    """
    return _ff_markers(build_dir).get("protein", "").lower() == name.lower()


def _has_water_model(build_dir: Path, name: str) -> bool:
    """The sourced water leaprc matches ``name`` (tip3p / tip4pew / ...).

    Water is always added by systembuilder, so the sourced water leaprc
    is the model that was actually applied.
    """
    return _ff_markers(build_dir).get("water", "").lower() == name.lower()


# NOTE: do NOT add helpers that infer lipid / ligand / RNA / DNA presence
# from leaprc-file presence. ``tleap.in`` unconditionally ``source``s every
# available leaprc, so those files always appear in ``build_<N>/`` even
# when the corresponding residue type is not in the system. For those
# signals, use ``_built_system_has_lipid``, ``_built_system_has_ligand``
# (residue-composition based) or read ``systemBuilder.csv`` directly.


# --- built-system loading ------------------------------------------------

def _load_built_pdb(artifact: RunArtifact) -> Any:
    """``moleculekit.Molecule`` from the latest ``build_<N>/structure.pdb``.

    Returns ``None`` if no build exists. Raises if the PDB exists but
    cannot be parsed.
    """
    build_dir = _latest_build_dir(artifact)
    if build_dir is None:
        return None
    from moleculekit.molecule import Molecule  # type: ignore[import-not-found]

    return Molecule(str(build_dir / "structure.pdb"))


def _padding_min_A(mol: Any, selection: str = "protein and noh") -> float | None:
    """Minimum padding (Å) between ``selection`` and the system bounding box.

    Computes ``(system_extent - solute_extent) / face`` on each axis and
    returns the smallest of the six face distances. Robust to whatever
    origin convention systembuilder chose, since it works in solute
    coordinates only.

    Returns ``None`` if the selection is empty or the molecule has no
    coordinates.
    """
    import numpy as np

    if mol is None:
        return None
    coords = getattr(mol, "coords", None)
    if coords is None:
        return None
    if coords.ndim == 3:
        coords = coords[:, :, 0]
    sel = mol.atomselect(selection)
    if not np.any(sel):
        return None
    pcoords = coords[sel]
    pmin = pcoords.min(axis=0)
    pmax = pcoords.max(axis=0)
    smin = coords.min(axis=0)
    smax = coords.max(axis=0)
    pad_low = (pmin - smin).min()
    pad_high = (smax - pmax).min()
    return float(min(pad_low, pad_high))


# --- systembuilder summary CSV -------------------------------------------

def _systembuilder_csv_row(artifact: RunArtifact) -> dict[str, str] | None:
    """First data row of ``systembuilder*/systemBuilder.csv``, or ``None``.

    Columns observed in practice:
    ``Build #, FF, # Atoms, # Waters, # Cations, # Anions, # Lipids,
    celldimension, membrane, lig2_displacement_vector``.
    """
    root = artifact.project_files_dir
    if not root.is_dir():
        return None
    for csv_path in sorted(root.rglob("systemBuilder.csv")):
        with csv_path.open(encoding="utf-8", errors="ignore", newline="") as f:
            rows = list(csv.DictReader(f))
        if rows:
            return {k: (v or "").strip() for k, v in rows[0].items() if k}
    return None


def _csv_int(row: dict[str, str] | None, key: str) -> int | None:
    """Parse an int from a CSV row safely; ``None`` if absent or invalid."""
    if row is None:
        return None
    raw = row.get(key, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


# --- built-system content (residue-composition based) --------------------

def _built_system_residues(artifact: RunArtifact) -> set[str] | None:
    """Unique residue names in the latest build's ``structure.pdb``.

    Returns ``None`` if no build exists or the file can't be parsed.
    """
    build_dir = _latest_build_dir(artifact)
    if build_dir is None:
        return None
    pdb = build_dir / "structure.pdb"
    if not pdb.is_file():
        return None
    residues: set[str] = set()
    with pdb.open(encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith(("ATOM  ", "HETATM")):
                resname = line[17:20].strip().upper()
                if resname:
                    residues.add(resname)
    return residues


def _built_system_has_lipid(artifact: RunArtifact) -> bool:
    """Did the built system end up containing any lipid?

    Trusts ``systemBuilder.csv['# Lipids']`` when available; falls back
    to a residue-name scan of ``structure.pdb`` against ``_LIPIDS``.
    """
    n_lipids = _csv_int(_systembuilder_csv_row(artifact), "# Lipids")
    if n_lipids is not None:
        return n_lipids > 0
    residues = _built_system_residues(artifact)
    return bool(residues and (residues & _LIPIDS))


def _built_system_has_ligand(artifact: RunArtifact) -> bool:
    """Any non-standard residue in ``structure.pdb`` beyond protein, water,
    ions, nucleic acid, and lipids.
    """
    residues = _built_system_residues(artifact)
    if not residues:
        return False
    return bool(residues - _BUILD_NON_LIGAND - _LIPIDS)


# --- simplerun output discovery ------------------------------------------

def _simplerun_runs(artifact: RunArtifact) -> list[Path]:
    """Directories containing ``output.xtc`` AND ``log.txt`` (any depth).

    Catches ``equilibration/``, ``production/``, ``prod_<N>/`` etc.
    """
    root = artifact.project_files_dir
    if not root.is_dir():
        return []
    out: list[Path] = []
    for traj in root.rglob(_MD_TRAJ_NAME):
        run_dir = traj.parent
        if (run_dir / _MD_LOG_NAME).is_file():
            out.append(run_dir)
    return sorted(out)


def _equilibration_dir(artifact: RunArtifact) -> Path | None:
    for run_dir in _simplerun_runs(artifact):
        if run_dir.name == "equilibration":
            return run_dir
    return None


def _production_dirs(artifact: RunArtifact) -> list[Path]:
    return [r for r in _simplerun_runs(artifact) if r.name.startswith(("production", "prod_"))]


# --- MD survivability signals --------------------------------------------

def _traj_frame_count(xtc_path: Path) -> int:
    """Frames in an XTC trajectory; ``0`` if missing or unreadable."""
    if not xtc_path.is_file() or xtc_path.stat().st_size == 0:
        return 0
    try:
        from moleculekit.molecule import Molecule  # type: ignore[import-not-found]

        mol = Molecule(str(xtc_path))
        coords = getattr(mol, "coords", None)
        if coords is None:
            return 0
        return int(coords.shape[2]) if coords.ndim == 3 else 0
    except Exception:
        return 0


def _log_has_traceback(log_path: Path) -> bool:
    if not log_path.is_file():
        return False
    try:
        text = log_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in _TRACEBACK_MARKERS)


def _md_started_cleanly(run_dir: Path) -> tuple[bool, str]:
    """Composite: trajectory has frames AND log shows no traceback."""
    frames = _traj_frame_count(run_dir / _MD_TRAJ_NAME)
    traceback = _log_has_traceback(run_dir / _MD_LOG_NAME)
    if traceback:
        return False, f"{run_dir.name}: traceback found in log.txt"
    if frames <= 0:
        return False, f"{run_dir.name}: no frames in {_MD_TRAJ_NAME}"
    return True, f"{run_dir.name}: {frames} frames, no traceback"


# --- parameterize / proteinprepare ---------------------------------------

def _parameterize_ff(artifact: RunArtifact) -> str | None:
    """Ligand-FF directory under ``parameterize*/parameters/<FF>/``, or ``None``."""
    root = artifact.project_files_dir
    if not root.is_dir():
        return None
    for params in root.rglob("parameters"):
        if not params.is_dir():
            continue
        for child in params.iterdir():
            if child.is_dir() and child.name in _LIG_FF_DIR_NAMES:
                return child.name
    return None


def _proteinprepare_output(artifact: RunArtifact) -> Path | None:
    """The prepared protein PDB from ``proteinprepare*/``, or ``None``."""
    root = artifact.project_files_dir
    if not root.is_dir():
        return None
    for path in root.rglob("proteinprepare*"):
        if not path.is_dir():
            continue
        for pdb in path.rglob("*.pdb"):
            return pdb
    return None


# --- per-case sections (added one at a time as cases land) ---------------


# ===== ms-0712 ==========================================================
# Apo Ubiquitin (1UBQ) in TIP3P, 10 Å padding, auto-neutralisation, no
# ligand, 0.1 ns equilibration + 1 ns production. We grade what the
# agent built and whether equilibration MD survived past the first few
# integrator steps before the runner cap fires.

_MS0712_MIN_PADDING_A = 9.5  # 10 Å requested, 0.5 Å slack for box conventions


def ms0712_apo_1ubq_build_and_md(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """Composite: built system matches the prompt + equilibration MD started."""
    build_dir = _latest_build_dir(artifact)
    if build_dir is None:
        return _result(0.0, "no systembuilder build_<N>/structure.pdb in project")

    failures: list[str] = []

    markers = _ff_markers(build_dir)
    if markers.get("water", "").lower() != "tip3p":
        failures.append(f"water != tip3p (got {markers.get('water', '?')!r})")
    if _built_system_has_lipid(artifact):
        failures.append("unexpected lipid in built system (apo prompt, no membrane)")
    if _built_system_has_ligand(artifact):
        residues = _built_system_residues(artifact) or set()
        extra = sorted(residues - _BUILD_NON_LIGAND - _LIPIDS)
        failures.append(f"unexpected non-standard residues (apo prompt): {extra[:6]}")

    pad: float | None = None
    try:
        mol = _load_built_pdb(artifact)
        pad = _padding_min_A(mol)
    except Exception as exc:  # noqa: BLE001
        failures.append(f"structure.pdb load failed: {type(exc).__name__}: {exc}")

    if pad is not None and pad < _MS0712_MIN_PADDING_A:
        failures.append(f"padding {pad:.2f} Å < {_MS0712_MIN_PADDING_A:.1f} Å")

    equil = _equilibration_dir(artifact)
    if equil is None:
        failures.append("no equilibration/output.xtc found")
    else:
        ok, why = _md_started_cleanly(equil)
        if not ok:
            failures.append(why)

    if failures:
        return _result(0.0, "; ".join(failures))

    pad_str = f"{pad:.2f}" if pad is not None else "?"
    return _result(
        1.0,
        f"build OK (water=tip3p, padding={pad_str} Å, apo); equilibration MD started",
    )
