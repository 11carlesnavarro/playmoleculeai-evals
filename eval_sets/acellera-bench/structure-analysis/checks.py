"""Programmatic checks for the structure-analysis eval set.

One function per case-assertion, grouped by case id. Expected values
and tolerances are baked into the function. Re-derive any hardcoded
constants with the matching ``development/test_case_<id>.py`` script
if source data changes.
"""

from __future__ import annotations

import csv
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from pmai_evals.grading.assertions import PYTHON_CHECK_TYPE
from pmai_evals.runner.artifacts import RunArtifact
from pmai_evals.schemas import AssertionResult

_T = TypeVar("_T")


def _result(score: float | bool, evidence: str) -> AssertionResult:
    return AssertionResult(
        assertion_type=PYTHON_CHECK_TYPE,
        score=float(score),
        evidence=evidence,
        config={},
    )


def _read_rows(
    artifact: RunArtifact, filename: str
) -> list[dict[str, str]] | None:
    """Every data row of an agent CSV as a dict, or None if the file is absent."""
    csv_path = artifact.project_files_dir / filename
    if not csv_path.is_file():
        return None
    with csv_path.open(encoding="utf-8", errors="ignore", newline="") as f:
        return list(csv.DictReader(f))


def _collect(
    rows: list[dict[str, str]], mapper: Callable[[dict[str, str]], _T | None]
) -> list[_T]:
    """Map every row, dropping the ones ``mapper`` rejects (None or bad field)."""
    out: list[_T] = []
    for row in rows:
        try:
            value = mapper(row)
        except (KeyError, ValueError):
            continue
        if value is not None:
            out.append(value)
    return out


def _read_csv_first_row(
    artifact: RunArtifact, filename: str
) -> dict[str, str] | None:
    """First data row of ``filename`` as a stripped dict, or None."""
    rows = _read_rows(artifact, filename)
    if not rows:
        return None
    return {k: (v or "").strip() for k, v in rows[0].items() if k}


def _read_metrics_row(artifact: RunArtifact) -> dict[str, str] | None:
    return _read_csv_first_row(artifact, "metrics.csv")


def _read_residue_set(
    artifact: RunArtifact, filename: str
) -> set[tuple[str, int]] | None:
    """Read a (chain, resid) set from an agent CSV, or None if absent."""
    rows = _read_rows(artifact, filename)
    if rows is None:
        return None
    return set(_collect(
        rows, lambda r: (r["chain"].strip().upper(), int(r["resid"].strip()))
    ))


def _read_center(row: dict[str, str]) -> tuple[float, float, float] | None:
    try:
        return (
            float(row["center_x"]),
            float(row["center_y"]),
            float(row["center_z"]),
        )
    except (KeyError, ValueError):
        return None


def _dist3(p: Sequence[float], q: Sequence[float]) -> float:
    return sum((a - b) ** 2 for a, b in zip(p, q, strict=True)) ** 0.5


def _fmt_diff(
    missing: set[Any],
    extra: set[Any],
    fmt: Callable[[Any], str] = lambda e: f"{e[0]}{e[1]}",
) -> str:
    miss_str = ", ".join(fmt(e) for e in sorted(missing))
    extra_str = ", ".join(fmt(e) for e in sorted(extra))
    return f"missing=[{miss_str}] extra=[{extra_str}]"


def _grade_exact_set(
    agent: set[Any],
    truth: set[Any],
    fmt: Callable[[Any], str] = lambda e: f"{e[0]}{e[1]}",
) -> tuple[bool, str]:
    """Pass iff agent == truth; evidence lists the symmetric difference."""
    missing = truth - agent
    extra = agent - truth
    return not missing and not extra, _fmt_diff(missing, extra, fmt)


# ---- sa-1187: 1AQ1 ligand pocket heavy-atom contact counts ----------------

# resid -> count of heavy-atom pairs (residue heavy atom, ligand heavy atom)
# at distance <= 5 A in 1AQ1.
_SA1187_TRUTH: dict[int, int] = {
    10: 41, 11: 13, 12: 5, 13: 6, 18: 30, 31: 9, 33: 11, 64: 3,
    80: 16, 81: 10, 82: 22, 83: 19, 84: 8, 85: 12, 86: 19,
    131: 19, 132: 6, 133: 1, 134: 38, 144: 3, 145: 21,
}


def sa1187_contact_counts(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """Pass iff contacts.csv reproduces the per-residue contact dict exactly."""
    rows = _read_rows(artifact, "contacts.csv")
    if rows is None:
        return _result(0.0, "contacts.csv not found in project workspace")

    agent: dict[int, int] = dict(_collect(
        rows, lambda r: (int(r["resid"].strip()), int(r["contacts"].strip()))
    ))

    if agent == _SA1187_TRUTH:
        return _result(1.0, f"{len(agent)} residues, exact match")
    diffs = [
        r for r in agent.keys() | _SA1187_TRUTH.keys()
        if agent.get(r) != _SA1187_TRUTH.get(r)
    ]
    sample = ", ".join(
        f"{r}:{agent.get(r)}!={_SA1187_TRUTH.get(r)}" for r in sorted(diffs)[:6]
    )
    return _result(
        0.0,
        f"agent={len(agent)} truth={len(_SA1187_TRUTH)} mismatched={len(diffs)} ({sample})",
    )


# ---- sa-1858: 7VH8 Nirmatrelvir-Mpro hydrogen bonds ----------------------

# The seven protein-ligand H-bonds listed in Zhao et al., "Crystal
# structure of SARS-CoV-2 main protease in complex with protease
# inhibitor PF-07321332", Protein & Cell 13:689 (2022), the deposition
# paper for 7VH8. Six anchor the S1 pocket; Q192/NE2 contacts the
# trifluoromethyl group. Keys are (chain, resid, protein_atom).
_SA1858_HBONDS: set[tuple[str, int, str]] = {
    ("A", 143, "N"),
    ("A", 145, "N"),
    ("A", 163, "NE2"),
    ("A", 164, "O"),
    ("A", 166, "O"),
    ("A", 166, "OE1"),
    ("A", 192, "NE2"),
}


def sa1858_hbond_list(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """Pass iff hbonds.csv is exactly the canonical H-bond set."""
    rows = _read_rows(artifact, "hbonds.csv")
    if rows is None:
        return _result(0.0, "hbonds.csv not found in project workspace")
    agent = set(_collect(rows, lambda r: (
        r["chain"].strip().upper(),
        int(r["resid"].strip()),
        r["protein_atom"].strip().upper(),
    )))
    return _result(*_grade_exact_set(
        agent, _SA1858_HBONDS, lambda e: f"{e[0]}{e[1]}/{e[2]}"
    ))


# ---- sa-0265: 6FSK tyrosine + heme-pocket per-residue SASA ---------------

# moleculekit MetricSasa (Shrake-Rupley) on the holoenzyme (protein +
# HEM cofactor; waters and heteroatoms dropped), probeRadius=1.4 A,
# numSpherePoints=960, mode='residue'. Keys are (chain, resid); values
# are SASA in A^2. Pocket = protein residues with any atom within 5.0 A
# of any HEM atom in the deposited structure.
_SA0265_TYR_SASA: dict[tuple[str, int], float] = {
    ("A", 28): 2.89,
    ("A", 194): 6.65,
    ("A", 249): 27.01,
    ("A", 339): 15.15,
    ("A", 390): 0.85,
    ("A", 474): 0.33,
    ("B", 28): 1.38,
    ("B", 194): 6.10,
    ("B", 249): 24.74,
    ("B", 339): 9.52,
    ("B", 390): 0.60,
    ("B", 474): 0.22,
}
_SA0265_POCKET_SASA: dict[tuple[str, int], float] = {
    ("A", 190): 2.60,  ("A", 192): 5.96,  ("A", 194): 6.65,  ("A", 195): 37.55,
    ("A", 196): 33.76, ("A", 197): 42.34, ("A", 198): 33.53, ("A", 199): 4.03,
    ("A", 250): 6.16,  ("A", 252): 1.34,  ("A", 285): 4.28,  ("A", 287): 1.89,
    ("A", 313): 15.04, ("A", 334): 0.38,  ("A", 335): 0.99,  ("A", 338): 3.68,
    ("A", 339): 15.15, ("A", 341): 8.12,  ("A", 357): 18.74, ("A", 358): 5.46,
    ("A", 360): 20.51, ("A", 385): 5.53,  ("A", 387): 4.91,  ("A", 398): 2.30,
    ("A", 401): 0.13,  ("A", 402): 3.93,  ("A", 435): 7.62,  ("A", 436): 10.85,
    ("A", 467): 13.06,
    ("B", 190): 2.84,  ("B", 192): 7.41,  ("B", 194): 6.10,  ("B", 195): 37.68,
    ("B", 196): 36.41, ("B", 197): 44.40, ("B", 198): 32.90, ("B", 199): 3.41,
    ("B", 200): 36.38, ("B", 250): 6.04,  ("B", 252): 1.56,  ("B", 285): 4.15,
    ("B", 287): 2.52,  ("B", 313): 11.01, ("B", 334): 0.25,  ("B", 335): 0.99,
    ("B", 338): 4.24,  ("B", 339): 9.52,  ("B", 341): 5.09,  ("B", 357): 18.17,
    ("B", 358): 5.95,  ("B", 360): 19.76, ("B", 385): 5.79,  ("B", 387): 4.40,
    ("B", 398): 2.16,  ("B", 401): 0.13,  ("B", 402): 3.91,  ("B", 435): 8.07,
    ("B", 436): 9.93,  ("B", 467): 12.75,
}
_SA0265_SASA_TOL = 3.0  # A^2


def _grade_sasa_csv(
    artifact: RunArtifact,
    filename: str,
    truth: dict[tuple[str, int], float],
) -> AssertionResult:
    """Compare an agent SASA CSV (chain,resid,sasa_A2) against a truth dict."""
    rows = _read_rows(artifact, filename)
    if rows is None:
        return _result(0.0, f"{filename} not found in project workspace")
    agent: dict[tuple[str, int], float] = dict(_collect(rows, lambda r: (
        (r["chain"].strip().upper(), int(r["resid"].strip())),
        float(r["sasa_A2"].strip()),
    )))

    missing = truth.keys() - agent.keys()
    extra = agent.keys() - truth.keys()
    off = [
        (k, agent[k], truth[k])
        for k in truth.keys() & agent.keys()
        if abs(agent[k] - truth[k]) > _SA0265_SASA_TOL
    ]
    off_str = ", ".join(
        f"{c}{r}:{a:.2f}vs{t:.2f}" for (c, r), a, t in sorted(off)[:6]
    )
    return _result(
        not missing and not extra and not off,
        f"{_fmt_diff(missing, extra)} off=[{off_str}]",
    )


def sa0265_tyr_sasa(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """Pass iff tyr_sasa.csv matches the truth within +-3 A^2 per residue."""
    return _grade_sasa_csv(artifact, "tyr_sasa.csv", _SA0265_TYR_SASA)


def sa0265_pocket_sasa(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """Pass iff pocket_sasa.csv matches the truth within +-3 A^2 per residue."""
    return _grade_sasa_csv(artifact, "pocket_sasa.csv", _SA0265_POCKET_SASA)


# ---- sa-0673: 1IEP Abl kinase + imatinib pocket & IFP --------------------

# Chain A protein residues with any heavy atom within 5.0 A of any STI
# heavy atom in 1IEP. Derived from coordinates by
# ``development/test_case_sa-0673.py``. 1IEP is a homodimer; Nagar et
# al. report distances from chain A only, so the case is restricted to
# chain A.
_SA0673_POCKET: set[tuple[str, int]] = {
    ("A", 248), ("A", 253), ("A", 256), ("A", 269), ("A", 270),
    ("A", 271), ("A", 286), ("A", 289), ("A", 290), ("A", 293),
    ("A", 299), ("A", 313), ("A", 314), ("A", 315), ("A", 316),
    ("A", 317), ("A", 318), ("A", 321), ("A", 322), ("A", 359),
    ("A", 360), ("A", 361), ("A", 362), ("A", 370), ("A", 379),
    ("A", 380), ("A", 381), ("A", 382),
}

# Literature-canonical IFP for imatinib (STI) in 1IEP chain A, from
# Nagar B, Bornmann WG, Pellicena P, Schindler T, Veach DR, Miller WT,
# Clarkson B, Kuriyan J, "Crystal structures of the kinase domain of
# c-Abl in complex with the small molecule inhibitors PD173955 and
# imatinib (STI-571)", Cancer Res 62(15):4236 (2002), Fig. 3B (left
# panel, AblK:STI-571). Hbond distances read from the figure; vdW
# residues are every contact circled in the 2D diagram (paper text:
# "residues making van der Waals interactions ... are circled"). Water-
# mediated interactions are excluded per the figure legend.
_SA0673_HBONDS: set[tuple[str, int]] = {
    ("A", 286),  # Glu286 side-chain COO-, 3.00 A
    ("A", 290),  # Met290 backbone C=O, 2.90 A
    ("A", 315),  # Thr315 side-chain OH, 2.85 A
    ("A", 318),  # Met318 backbone NH, 2.90 A
    ("A", 360),  # Ile360 backbone, 2.67 A
    ("A", 361),  # His361 backbone, 3.19 A
    ("A", 381),  # Asp381 to central amide NH
}
_SA0673_HYDROPHOBIC: set[tuple[str, int]] = {
    ("A", 248), ("A", 253), ("A", 256), ("A", 269), ("A", 271),
    ("A", 286), ("A", 289), ("A", 290), ("A", 299), ("A", 313),
    ("A", 315), ("A", 317), ("A", 318), ("A", 321), ("A", 360),
    ("A", 361), ("A", 362), ("A", 370), ("A", 380), ("A", 381),
    ("A", 382),
}


def _read_interactions(
    artifact: RunArtifact, kind: str
) -> tuple[set[tuple[str, int]], str | None]:
    """Return the agent's (chain, resid) set for one interaction type."""
    rows = _read_rows(artifact, "interactions.csv")
    if rows is None:
        return set(), "interactions.csv not found in project workspace"
    agent = set(_collect(
        rows,
        lambda r: (r["chain"].strip().upper(), int(r["resid"].strip()))
        if r["type"].strip().lower() == kind
        else None,
    ))
    return agent, None


def _score_ifp(
    agent: set[tuple[str, int]], truth: set[tuple[str, int]]
) -> tuple[float, str]:
    """Fractional credit on missing, hard zero on any extras."""
    missing = truth - agent
    extra = agent - truth
    correct = len(truth & agent)
    score = 0.0 if extra else correct / len(truth)
    return score, f"{correct}/{len(truth)} correct, {_fmt_diff(missing, extra)}"


def sa0673_pocket_residues(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """1.0 iff pocket.csv is exactly the chain A 5 A pocket residue set."""
    agent = _read_residue_set(artifact, "pocket.csv")
    if agent is None:
        return _result(0.0, "pocket.csv not found in project workspace")
    return _result(*_grade_exact_set(agent, _SA0673_POCKET))


def sa0673_hbonds(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """Fraction of the 7 paper H-bonds reported, 0 if any extras."""
    agent, err = _read_interactions(artifact, "hbond")
    if err:
        return _result(0.0, err)
    return _result(*_score_ifp(agent, _SA0673_HBONDS))


def sa0673_hydrophobic(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """Fraction of the 21 paper vdW residues reported, 0 if any extras."""
    agent, err = _read_interactions(artifact, "hydrophobic")
    if err:
        return _result(0.0, err)
    return _result(*_score_ifp(agent, _SA0673_HYDROPHOBIC))


# ---- sa-0701: 3ERT ER-alpha LBD + 4-hydroxytamoxifen pocket -------------

# Chain A protein residues with any heavy atom within 5.0 A of any OHT
# heavy atom in 3ERT, plus three pinned scalar descriptors. All four
# quantities are deterministic; re-derive with
# ``development/test_case_sa-0701.py`` if source data changes.
_SA0701_POCKET: set[tuple[str, int]] = {
    ("A", 343), ("A", 346), ("A", 347), ("A", 349), ("A", 350),
    ("A", 351), ("A", 353), ("A", 383), ("A", 384), ("A", 387),
    ("A", 388), ("A", 391), ("A", 394), ("A", 404), ("A", 419),
    ("A", 420), ("A", 421), ("A", 424), ("A", 428), ("A", 521),
    ("A", 524), ("A", 525),
}
_SA0701_CENTER: tuple[float, float, float] = (31.575, -1.590, 25.599)
_SA0701_RES_HYDROPHOBIC_FRACTION = 0.5909     # Kyte-Doolittle index > 0
_SA0701_FRAC_TOL = 0.02
_SA0701_NET_CHARGES = {-2, -1}                # His neutral or His-+1
_SA0701_CLOSEST: tuple[str, int] = ("A", 353)
_SA0701_CLOSEST_DIST = 2.421                  # A
_SA0701_CENTER_TOL = 0.25                     # A, Euclidean
_SA0701_CLOSEST_DIST_TOL = 0.25               # A


def sa0701_pocket_residues(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """1.0 iff pocket.csv is exactly the chain A 5 A OHT pocket set."""
    agent = _read_residue_set(artifact, "pocket.csv")
    if agent is None:
        return _result(0.0, "pocket.csv not found in project workspace")
    return _result(*_grade_exact_set(agent, _SA0701_POCKET))


def sa0701_center(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """1.0 iff the reported OHT centroid is within tolerance."""
    row = _read_metrics_row(artifact)
    if row is None:
        return _result(0.0, "metrics.csv not found or empty")
    c = _read_center(row)
    if c is None:
        return _result(0.0, f"center_x/y/z unreadable in metrics.csv: {row}")
    d = _dist3(c, _SA0701_CENTER)
    return _result(
        d <= _SA0701_CENTER_TOL,
        f"center={c} truth={_SA0701_CENTER} dist={d:.3f} A",
    )


def sa0701_res_hydrophobic_fraction(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """1.0 iff res_hydrophobic_fraction (Kyte-Doolittle > 0) matches."""
    row = _read_metrics_row(artifact)
    if row is None:
        return _result(0.0, "metrics.csv not found or empty")
    try:
        v = float(row["res_hydrophobic_fraction"])
    except (KeyError, ValueError):
        return _result(0.0, f"res_hydrophobic_fraction unreadable: {row}")
    diff = abs(v - _SA0701_RES_HYDROPHOBIC_FRACTION)
    return _result(
        diff <= _SA0701_FRAC_TOL,
        f"agent={v} truth={_SA0701_RES_HYDROPHOBIC_FRACTION} d={diff:.4f}",
    )


def sa0701_net_formal_charge(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """1.0 iff net_formal_charge is the His-neutral or His-+1 value."""
    row = _read_metrics_row(artifact)
    if row is None:
        return _result(0.0, "metrics.csv not found or empty")
    try:
        v = round(float(row["net_formal_charge"]))
    except (KeyError, ValueError):
        return _result(0.0, f"net_formal_charge unreadable: {row}")
    return _result(
        v in _SA0701_NET_CHARGES,
        f"agent={v} accepted={sorted(_SA0701_NET_CHARGES)}",
    )


def sa0701_closest_contact(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """1.0 iff the closest pocket residue and its distance both match."""
    row = _read_metrics_row(artifact)
    if row is None:
        return _result(0.0, "metrics.csv not found or empty")
    try:
        resid = int(row["closest_resid"])
        dist = float(row["closest_dist_A"])
    except (KeyError, ValueError):
        return _result(0.0, f"closest_resid/closest_dist_A unreadable: {row}")
    res_ok = resid == _SA0701_CLOSEST[1]
    dist_ok = abs(dist - _SA0701_CLOSEST_DIST) <= _SA0701_CLOSEST_DIST_TOL
    return _result(
        res_ok and dist_ok,
        f"resid={resid} (truth {_SA0701_CLOSEST[1]}) "
        f"dist={dist:.3f} (truth {_SA0701_CLOSEST_DIST})",
    )


# ---- sa-0192: ER-alpha LBD H12 angular difference (1ERE vs 3ERT) --------

# Angle between the H12 (residues 538-546, pinned in the prompt)
# principal axes of 1ERE chain A (agonist) and 3ERT chain A
# (antagonist) after superposing the two chains on their common Cα.
# Derived by ``development/test_case_sa-0192.py``. The supplement is
# accepted because "angle between axes" has a directional reading
# ambiguity; +-10 deg absorbs the helix-axis method (PCA vs endpoint,
# ~3 deg) while rejecting any wrong H12 range.
_SA0192_ANGLE_DEG = 112.23
_SA0192_ANGLE_SUPP_DEG = 67.77
_SA0192_ANGLE_TOL = 10.0


def sa0192_h12_angle(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """1.0 iff angle_deg is within tol of the H12 angle or its supplement."""
    row = _read_csv_first_row(artifact, "h12.csv")
    if row is None:
        return _result(0.0, "h12.csv not found or empty")
    try:
        v = float(row["angle_deg"])
    except (KeyError, ValueError):
        return _result(0.0, f"angle_deg unreadable in h12.csv: {row}")
    d = min(
        abs(v - _SA0192_ANGLE_DEG),
        abs(v - _SA0192_ANGLE_SUPP_DEG),
    )
    return _result(
        d <= _SA0192_ANGLE_TOL,
        f"agent={v:.2f} truth={_SA0192_ANGLE_DEG}|{_SA0192_ANGLE_SUPP_DEG} "
        f"nearest_d={d:.2f} tol={_SA0192_ANGLE_TOL}",
    )


# ---- sa-0071: characterise DeepSite's top predicted pocket (7Y5K) -------

# The DeepSite job is preloaded as a frozen fixture; the agent must
# interpret it. Truth is the highest-scoring output.csv pocket and its
# environment in 7Y5K_prepared.pdb (the structure DeepSite ran on).
# Pinned definitions: host_chain = chain with most atoms within 6 A of
# the center; interface = a different protein chain within 8 A; pocket
# residues = protein residues within 8 A. Re-derive with
# ``development/test_case_sa-0071.py``.
_SA0071_CENTER: tuple[float, float, float] = (23.430, 37.410, -25.290)
_SA0071_HOST_CHAIN = "E"
_SA0071_INTERFACE = True
_SA0071_CENTER_TOL = 1.0      # A, Euclidean
_SA0071_MARKER_TOL = 2.0      # A, Euclidean
_SA0071_RES8: set[tuple[str, int]] = {
    ("A", 482), ("A", 484), ("E", 48), ("E", 49), ("E", 131), ("E", 132),
    ("E", 134), ("E", 184), ("E", 185), ("E", 187), ("E", 234), ("E", 237),
    ("E", 280), ("E", 281), ("E", 283), ("E", 324), ("E", 325), ("E", 327),
    ("E", 381), ("E", 382), ("E", 384),
}
_TRUE = {"yes", "true", "1", "y", "t"}


def sa0071_center(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """1.0 iff pocket.csv center matches DeepSite's top predicted center."""
    row = _read_csv_first_row(artifact, "pocket.csv")
    if row is None:
        return _result(0.0, "pocket.csv not found or empty")
    c = _read_center(row)
    if c is None:
        return _result(0.0, f"center_x/y/z unreadable: {row}")
    d = _dist3(c, _SA0071_CENTER)
    return _result(
        d <= _SA0071_CENTER_TOL,
        f"center={c} truth={_SA0071_CENTER} dist={d:.3f}",
    )


def sa0071_host_chain(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """1.0 iff host_chain is the chain with most atoms within 6 A."""
    row = _read_csv_first_row(artifact, "pocket.csv")
    if row is None:
        return _result(0.0, "pocket.csv not found or empty")
    v = (row.get("host_chain") or "").strip().upper()
    return _result(
        v == _SA0071_HOST_CHAIN,
        f"host_chain={v!r} truth={_SA0071_HOST_CHAIN!r}",
    )


def sa0071_interface(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """1.0 iff the interface flag matches (a 2nd protein chain <8 A)."""
    row = _read_csv_first_row(artifact, "pocket.csv")
    if row is None:
        return _result(0.0, "pocket.csv not found or empty")
    raw = (row.get("interface") or "").strip().lower()
    v = raw in _TRUE
    return _result(
        v == _SA0071_INTERFACE,
        f"interface={raw!r}->{v} truth={_SA0071_INTERFACE}",
    )


def sa0071_pocket_residues(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """1.0 iff pocket_residues.csv equals the 8 A protein residue set."""
    agent = _read_residue_set(artifact, "pocket_residues.csv")
    if agent is None:
        return _result(0.0, "pocket_residues.csv not found")
    return _result(*_grade_exact_set(agent, _SA0071_RES8))


def sa0071_marker(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """1.0 iff marker.pdb has an atom at the predicted pocket center."""
    pdb = artifact.project_files_dir / "marker.pdb"
    if not pdb.is_file():
        return _result(0.0, "marker.pdb not found in project workspace")
    best = None
    with pdb.open(encoding="utf-8", errors="ignore") as f:
        for ln in f:
            if ln[:6] not in ("ATOM  ", "HETATM"):
                continue
            try:
                p = (float(ln[30:38]), float(ln[38:46]), float(ln[46:54]))
            except ValueError:
                continue
            d = _dist3(p, _SA0071_CENTER)
            best = d if best is None else min(best, d)
    if best is None:
        return _result(0.0, "marker.pdb has no parseable atoms")
    return _result(
        best <= _SA0071_MARKER_TOL,
        f"nearest marker atom {best:.3f} A from center",
    )


# ---- sa-0364: NDM-1 binuclear zinc centre (3SPU) ------------------------

# The two inequivalent zincs of the metallo-beta-lactamase active site
# (chain A): a 3-His site and an Asp/Cys/His + water site, ~3.8 A apart,
# with no single atom bridging both within 2.6 A. The per-metal
# atom-level coordination is measurable, not recallable. Solvent
# coordinating atoms are matched by element, not residue number (water
# numbering is not a fair failure axis). The two spheres are graded up
# to swapping; no Zn1/Zn2 convention is imposed. Re-derive with
# ``development/test_case_sa-0364.py``.
_SA0364_WATERS = {"HOH", "WAT", "DOD", "H2O", "SOL"}
_SA0364_GROUP_A: frozenset[tuple[object, str]] = frozenset(
    {(120, "NE2"), (122, "ND1"), (189, "NE2")}
)
_SA0364_GROUP_B: frozenset[tuple[object, str]] = frozenset(
    {(124, "OD1"), (208, "SG"), (250, "NE2"), ("WATER", "O")}
)
_SA0364_TRUTH = {_SA0364_GROUP_A, _SA0364_GROUP_B}
_SA0364_ZNZN_DIST = 3.836
_SA0364_ZNZN_TOL = 0.30
_SA0364_NO_BRIDGE = {"none", "na", "n/a", "-", "", "no", "false"}


def _sa0364_token(resname: str, resid: str, atom: str) -> tuple[object, str]:
    a = atom.strip().upper()
    if resname.strip().upper() in _SA0364_WATERS:
        return ("WATER", a)
    return (int(resid.strip()), a)


def sa0364_coordination(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """1.0 iff the two zinc coordination spheres match, up to swapping."""
    rows = _read_rows(artifact, "coordination.csv")
    if rows is None:
        return _result(0.0, "coordination.csv not found in project workspace")
    groups: dict[str, set[tuple[object, str]]] = {}
    for key, tok in _collect(rows, lambda r: (
        (r["zinc"] or "").strip().lower(),
        _sa0364_token(r["resname"], r["resid"], r["atom"]),
    )):
        groups.setdefault(key, set()).add(tok)
    if len(groups) != 2:
        return _result(
            0.0, f"expected 2 zinc groups, got {sorted(groups)}"
        )
    agent = {frozenset(g) for g in groups.values()}

    def _fmt(g: frozenset[tuple[object, str]]) -> str:
        body = ", ".join(
            f"{r}.{a}"
            for r, a in sorted(g, key=lambda t: (str(t[0]), str(t[1])))
        )
        return "{" + body + "}"

    agent_str = " | ".join(sorted(_fmt(g) for g in agent))
    truth_str = " | ".join(sorted(_fmt(g) for g in _SA0364_TRUTH))
    return _result(agent == _SA0364_TRUTH, f"agent={agent_str} truth={truth_str}")


def sa0364_metrics(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """1.0 iff Zn-Zn distance matches and no atom is claimed to bridge."""
    row = _read_metrics_row(artifact)
    if row is None:
        return _result(0.0, "metrics.csv not found or empty")
    try:
        d = float(row["zn_zn_dist_A"])
    except (KeyError, ValueError):
        return _result(0.0, f"zn_zn_dist_A unreadable: {row}")
    rn = (row.get("bridge_resname") or "").strip().lower()
    at = (row.get("bridge_atom") or "").strip().lower()
    dist_ok = abs(d - _SA0364_ZNZN_DIST) <= _SA0364_ZNZN_TOL
    bridge_ok = rn in _SA0364_NO_BRIDGE and at in _SA0364_NO_BRIDGE
    return _result(
        dist_ok and bridge_ok,
        f"zn_zn={d:.3f} (truth {_SA0364_ZNZN_DIST}) "
        f"bridge=({rn!r},{at!r}) want=none",
    )


# ---- sa-1168: covalent inhibitor linkage in KRAS(G12C) (6OIM) ----------

# The single protein<->ligand bond (Cys12 SG to the acrylamide warhead
# carbon of sotorasib, ~1.8 A) plus the 4 A pocket. The bonded residue
# is recallable from the literature, but the exact ligand atom, bond
# length, and pocket set require structural computation. Re-derive with
# ``development/test_case_sa-1168.py``.
_SA1168_COVALENT = ("A", 12, "CYS", "SG", "C25")
_SA1168_BOND_LEN = 1.805
_SA1168_BOND_TOL = 0.25
_SA1168_POCKET: set[tuple[str, int]] = {
    ("A", 9), ("A", 10), ("A", 12), ("A", 16), ("A", 34), ("A", 58),
    ("A", 59), ("A", 60), ("A", 61), ("A", 62), ("A", 63), ("A", 68),
    ("A", 72), ("A", 95), ("A", 96), ("A", 99), ("A", 103),
}


def sa1168_covalent(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """1.0 iff covalent.csv names the right residue, atoms and bond length."""
    row = _read_csv_first_row(artifact, "covalent.csv")
    if row is None:
        return _result(0.0, "covalent.csv not found or empty")
    try:
        chain = row["chain"].strip().upper()
        resid = int(row["resid"])
        resname = row["resname"].strip().upper()
        patom = row["protein_atom"].strip().upper()
        latom = row["ligand_atom"].strip().upper()
        blen = float(row["bond_length_A"])
    except (KeyError, ValueError):
        return _result(0.0, f"covalent.csv unreadable: {row}")
    tc, tr, trn, tpa, tla = _SA1168_COVALENT
    ok = (
        chain == tc
        and resid == tr
        and resname == trn
        and patom == tpa
        and latom == tla
        and abs(blen - _SA1168_BOND_LEN) <= _SA1168_BOND_TOL
    )
    return _result(
        ok,
        f"agent=({chain},{resid},{resname},{patom},{latom},{blen:.3f}) "
        f"truth=({tc},{tr},{trn},{tpa},{tla},{_SA1168_BOND_LEN})",
    )


def sa1168_pocket(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """1.0 iff pocket.csv is exactly the 4 A inhibitor pocket set."""
    agent = _read_residue_set(artifact, "pocket.csv")
    if agent is None:
        return _result(0.0, "pocket.csv not found in project workspace")
    return _result(*_grade_exact_set(agent, _SA1168_POCKET))


# ---- sa-0517: engineered mutations in the 2VT4 construct ---------------

# The deliberately introduced point mutations of the thermostabilised
# turkey beta-1 adrenergic receptor crystallisation construct (2VT4),
# taken from the deposition's SEQADV "ENGINEERED MUTATION" records vs
# UniProt P07700 (UniProt numbering). Eight in total: the six famous
# "m23" thermostabilising mutations plus the two cysteine removals
# (C116L, C358A). Recalling only the abstract's six, or diffing only
# the modelled CA atoms (A282L is disordered and invisible there),
# fails. Re-derive with ``development/test_case_sa-0517.py``.
_SA0517_MUTATIONS: set[tuple[int, str, str]] = {
    (68, "R", "S"), (90, "M", "V"), (116, "C", "L"), (227, "Y", "A"),
    (282, "A", "L"), (327, "F", "A"), (338, "F", "M"), (358, "C", "A"),
}


def sa0517_mutations(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """1.0 iff mutations.csv is exactly the engineered-mutation set."""
    rows = _read_rows(artifact, "mutations.csv")
    if rows is None:
        return _result(0.0, "mutations.csv not found in project workspace")
    agent = set(_collect(rows, lambda r: (
        int(r["resid"].strip()),
        r["wildtype"].strip().upper(),
        r["mutant"].strip().upper(),
    )))
    return _result(*_grade_exact_set(
        agent, _SA0517_MUTATIONS, lambda e: f"{e[1]}{e[0]}{e[2]}"
    ))
