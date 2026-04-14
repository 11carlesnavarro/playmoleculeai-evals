"""Programmatic assertions over a single :class:`RunArtifact`.

Each function is pure: ``(artifact, config) -> AssertionResult``. No
network, no disk writes, no LLM calls. ``evidence`` is mandatory whether
the result is pass or fail (spec §4.5).

Adding a new assertion type is one function + one ``ASSERTION_REGISTRY``
entry + one unit test. No other touchpoints.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from types import ModuleType
from typing import Any

from pmai_evals.errors import AssertionConfigError
from pmai_evals.runner.artifacts import RunArtifact
from pmai_evals.schemas import AssertionResult

logger = logging.getLogger(__name__)

Assertion = Callable[[RunArtifact, dict[str, Any]], AssertionResult]

# Comparison operators accepted by ``op:`` fields in cases.yaml. Anything
# outside this set is a config error caught at assertion time.
VALID_COMPARE_OPS: frozenset[str] = frozenset({"==", ">=", "<=", ">", "<"})


# --- helpers ---------------------------------------------------------------

def _need(config: dict[str, Any], key: str) -> Any:
    if key not in config:
        raise AssertionConfigError(f"missing required assertion field: '{key}'")
    return config[key]


def _result(
    assertion_type: str,
    *,
    passed: bool,
    evidence: str,
    config: dict[str, Any],
) -> AssertionResult:
    return AssertionResult(
        assertion_type=assertion_type,
        passed=passed,
        evidence=evidence,
        config=config,
    )


def _compare(observed: float, op: str, target: float) -> bool:
    """Apply a YAML-declared comparison operator to two numbers."""
    if op not in VALID_COMPARE_OPS:
        raise AssertionConfigError(f"unknown op {op!r}; expected one of {sorted(VALID_COMPARE_OPS)}")
    if op == "==":
        return observed == target
    if op == ">=":
        return observed >= target
    if op == "<=":
        return observed <= target
    if op == ">":
        return observed > target
    return observed < target  # "<"


def _final_answer(artifact: RunArtifact) -> str:
    text = artifact.final_answer()
    if text:
        return text
    return str(artifact.trace().get("final_answer") or "")


def _tool_calls(artifact: RunArtifact) -> list[dict[str, Any]]:
    raw = artifact.trace().get("tool_calls") or []
    return list(raw) if isinstance(raw, list) else []


# --- text-on-output assertions --------------------------------------------

def check_output_contains(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    needle = _need(config, "value")
    if not isinstance(needle, str):
        raise AssertionConfigError("output_contains: 'value' must be a string")
    case_sensitive = bool(config.get("case_sensitive", False))
    haystack = _final_answer(artifact)
    found = (needle in haystack) if case_sensitive else (needle.lower() in haystack.lower())
    if found:
        offset = haystack.lower().find(needle.lower()) if not case_sensitive else haystack.find(needle)
        return _result(
            "output_contains",
            passed=True,
            evidence=f"final answer contained '{needle}' at offset {offset}",
            config=config,
        )
    return _result(
        "output_contains",
        passed=False,
        evidence=f"final answer (len={len(haystack)}) did not contain '{needle}'",
        config=config,
    )


def check_output_matches_regex(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    pattern = _need(config, "pattern")
    flags = re.IGNORECASE if config.get("ignore_case", False) else 0
    haystack = _final_answer(artifact)
    match = re.search(pattern, haystack, flags)
    if match:
        return _result(
            "output_matches_regex",
            passed=True,
            evidence=f"matched '{match.group(0)}' at offset {match.start()}",
            config=config,
        )
    return _result(
        "output_matches_regex",
        passed=False,
        evidence=f"pattern {pattern!r} not found in final answer (len={len(haystack)})",
        config=config,
    )


def check_output_numeric_close(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    target = float(_need(config, "value"))
    tolerance = float(config.get("tolerance", 0.1))
    pattern = config.get("pattern", r"-?\d+(?:\.\d+)?")
    haystack = _final_answer(artifact)
    matches = [float(m) for m in re.findall(pattern, haystack)]
    close = [v for v in matches if abs(v - target) <= tolerance]
    if close:
        return _result(
            "output_numeric_close",
            passed=True,
            evidence=f"found value {close[0]} within ±{tolerance} of {target}",
            config=config,
        )
    sample = matches[:5] if matches else []
    return _result(
        "output_numeric_close",
        passed=False,
        evidence=f"no number within ±{tolerance} of {target}; sampled {sample}",
        config=config,
    )


# --- tool-call assertions --------------------------------------------------

def check_tool_called(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    name = _need(config, "name")
    calls = _tool_calls(artifact)
    matches = [c for c in calls if c.get("name") == name]
    if matches:
        return _result(
            "tool_called",
            passed=True,
            evidence=f"{name} called {len(matches)} time(s); first at turn {matches[0].get('turn_index')}",
            config=config,
        )
    seen = sorted({c.get("name", "?") for c in calls})
    return _result(
        "tool_called",
        passed=False,
        evidence=f"{name} not called; observed: {seen}",
        config=config,
    )


def check_tool_called_with(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    name = _need(config, "name")
    expected_args: dict[str, Any] = config.get("arguments") or {}
    calls = [c for c in _tool_calls(artifact) if c.get("name") == name]
    if not calls:
        return _result(
            "tool_called_with",
            passed=False,
            evidence=f"{name} was not called at all",
            config=config,
        )
    for call in calls:
        args = call.get("arguments") or {}
        if all(args.get(k) == v for k, v in expected_args.items()):
            return _result(
                "tool_called_with",
                passed=True,
                evidence=f"{name} called with matching args at turn {call.get('turn_index')}",
                config=config,
            )
    sample = [c.get("arguments") for c in calls[:3]]
    return _result(
        "tool_called_with",
        passed=False,
        evidence=f"no {name} call matched {expected_args}; sampled args: {sample}",
        config=config,
    )


def check_tool_call_count(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    name = config.get("name")
    op = config.get("op", "==")
    target = int(_need(config, "value"))
    calls = _tool_calls(artifact)
    count = len([c for c in calls if name is None or c.get("name") == name])
    label = name or "any tool"
    return _result(
        "tool_call_count",
        passed=_compare(count, op, target),
        evidence=f"{label} called {count} times (expected {op} {target})",
        config=config,
    )


def check_tool_call_order(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    expected = list(_need(config, "order"))
    calls = [c for c in _tool_calls(artifact) if c.get("name") in expected]
    seen = [c.get("name") for c in calls]
    # Check that ``expected`` is a subsequence of ``seen``.
    i = 0
    for name in seen:
        if i < len(expected) and name == expected[i]:
            i += 1
    if i == len(expected):
        return _result(
            "tool_call_order",
            passed=True,
            evidence=f"observed order {seen} contains expected subsequence {expected}",
            config=config,
        )
    return _result(
        "tool_call_order",
        passed=False,
        evidence=f"observed order {seen} did not satisfy {expected}",
        config=config,
    )


def check_no_tool_error(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    calls = _tool_calls(artifact)
    errors = [c for c in calls if c.get("is_error") or c.get("error")]
    if not errors:
        return _result(
            "no_tool_error",
            passed=True,
            evidence=f"all {len(calls)} tool calls succeeded",
            config=config,
        )
    sample = [(c.get("name"), c.get("error") or "is_error") for c in errors[:3]]
    return _result(
        "no_tool_error",
        passed=False,
        evidence=f"{len(errors)}/{len(calls)} tool calls errored; sample: {sample}",
        config=config,
    )


# --- viewer-state assertions ----------------------------------------------

def check_viewer_has_molecule(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    import json

    identifier = _need(config, "identifier")
    state = artifact.viewer_state()
    if not state:
        return _result(
            "viewer_has_molecule",
            passed=False,
            evidence="viewer_state.json is empty or missing",
            config=config,
        )
    found = identifier.lower() in json.dumps(state).lower()
    return _result(
        "viewer_has_molecule",
        passed=found,
        evidence=(
            f"identifier {identifier!r} present in systems_tree"
            if found
            else f"identifier {identifier!r} not present in systems_tree"
        ),
        config=config,
    )


def check_viewer_system_count(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    expected = int(_need(config, "value"))
    op = config.get("op", "==")
    state = artifact.viewer_state()
    # The Pyodide systems_tree is a top-level list; the older shape was a
    # dict with a "systems" key. Accept both.
    if isinstance(state, list):
        count = len(state)
    elif isinstance(state, dict):
        systems = state.get("systems")
        count = len(systems) if isinstance(systems, list) else 0
    else:
        count = 0
    return _result(
        "viewer_system_count",
        passed=_compare(count, op, expected),
        evidence=f"{count} systems loaded (expected {op} {expected})",
        config=config,
    )


# --- structural (system-level) helpers ------------------------------------

_RESID_RE = re.compile(r"\bresid\s+([\d\s]+?)(?=\s+(?:and|or|not)\b|$)")


def find_system(state: Any, name: str) -> dict[str, Any] | None:
    """Return the top-level system whose ``name`` matches case-insensitively."""
    if not isinstance(state, list):
        return None
    needle = name.lower()
    for entry in state:
        if isinstance(entry, dict) and str(entry.get("name", "")).lower() == needle:
            return entry
    return None


def normalize_color(value: Any) -> int | None:
    """Coerce ``#RRGGBB`` / integer / ``None`` into an int, or ``None``."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip().lstrip("#")
        if not text:
            return None
        try:
            return int(text, 16)
        except ValueError as exc:
            raise AssertionConfigError(f"invalid color {value!r}") from exc
    raise AssertionConfigError(f"color must be hex string or int, got {type(value).__name__}")


def _representation_matches(
    rep: dict[str, Any],
    *,
    style: str | None,
    color_int: int | None,
    selection_contains: str | None,
) -> bool:
    if style is not None and style.lower() not in str(rep.get("type", "")).lower():
        return False
    if color_int is not None and int(rep.get("color_value", -1)) != color_int:
        return False
    if selection_contains is not None:
        sel = str(rep.get("selection", ""))
        if selection_contains.lower() not in sel.lower():
            return False
    return True


def extract_resids(selection: str) -> set[int]:
    """Return the set of residue numbers in a pmview selection expression.

    Matches ``resid 1 2 3`` / ``resid 16 17 19`` — the token list ends at
    the next boolean keyword (``and`` / ``or`` / ``not``) or end of string.
    Multiple ``resid`` clauses are unioned.
    """
    out: set[int] = set()
    for match in _RESID_RE.finditer(selection):
        for token in match.group(1).split():
            try:
                out.add(int(token))
            except ValueError:
                continue
    return out


# --- structural (system-level) assertions ---------------------------------

def check_system_has_representation(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    system_name = _need(config, "system")
    style = config.get("style")
    color_int = normalize_color(config.get("color"))
    selection_contains = config.get("selection_contains")

    system = find_system(artifact.viewer_state(), system_name)
    if system is None:
        return _result(
            "system_has_representation",
            passed=False,
            evidence=f"system {system_name!r} not present in viewer state",
            config=config,
        )
    reps = system.get("representations") or []
    for rep in reps:
        if _representation_matches(
            rep,
            style=style,
            color_int=color_int,
            selection_contains=selection_contains,
        ):
            return _result(
                "system_has_representation",
                passed=True,
                evidence=(
                    f"{system_name} has representation "
                    f"type={rep.get('type')!r} color={rep.get('color_value')}"
                ),
                config=config,
            )
    summary = [
        {"type": r.get("type"), "color": r.get("color_value")} for r in reps
    ]
    return _result(
        "system_has_representation",
        passed=False,
        evidence=(
            f"no representation matched style={style!r} color={color_int}; "
            f"saw {summary}"
        ),
        config=config,
    )


def check_system_representation_residues(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    system_name = _need(config, "system")
    style = config.get("style")
    color_int = normalize_color(config.get("color"))
    min_count = int(config.get("min_count", 0))
    must_include = {int(x) for x in (config.get("must_include") or [])}

    system = find_system(artifact.viewer_state(), system_name)
    if system is None:
        return _result(
            "system_representation_residues",
            passed=False,
            evidence=f"system {system_name!r} not present in viewer state",
            config=config,
        )
    matching = [
        r for r in (system.get("representations") or [])
        if _representation_matches(
            r, style=style, color_int=color_int, selection_contains=None
        )
    ]
    if not matching:
        return _result(
            "system_representation_residues",
            passed=False,
            evidence=f"no representation on {system_name!r} matched style={style!r}",
            config=config,
        )
    observed: set[int] = set()
    for rep in matching:
        observed |= extract_resids(str(rep.get("selection", "")))
    missing = must_include - observed
    if len(observed) < min_count:
        return _result(
            "system_representation_residues",
            passed=False,
            evidence=(
                f"{len(observed)} residues in selection "
                f"(expected >= {min_count})"
            ),
            config=config,
        )
    if missing:
        return _result(
            "system_representation_residues",
            passed=False,
            evidence=f"missing required residues: {sorted(missing)[:10]}",
            config=config,
        )
    return _result(
        "system_representation_residues",
        passed=True,
        evidence=f"{len(observed)} residues in selection; all required present",
        config=config,
    )


def check_systems_coaligned(
    artifact: RunArtifact, config: dict[str, Any]
) -> AssertionResult:
    """Pass if two exported systems sit in the same coordinate frame.

    Heuristic: compute the centroid of each system's selection and
    check the distance. An untransformed pair of RCSB structures usually
    lands tens of angstroms apart; an aligned pair lands within a few.
    Fast, pairing-free, and robust to differing residue numbering.
    """
    ref_name = _need(config, "reference")
    mob_name = _need(config, "mobile")
    selection = config.get("selection", "protein and name CA")
    max_distance_a = float(config.get("max_distance_a", 5.0))

    if not artifact.system_files():
        return _result(
            "systems_coaligned",
            passed=False,
            evidence="no exported systems available (systems/ missing)",
            config=config,
        )
    try:
        ref = artifact.load_system(ref_name)
        mob = artifact.load_system(mob_name)
    except KeyError as exc:
        return _result(
            "systems_coaligned",
            passed=False,
            evidence=str(exc),
            config=config,
        )

    import numpy as np

    try:
        ref_coords = ref.get("coords", sel=selection)
        mob_coords = mob.get("coords", sel=selection)
    except Exception as exc:
        return _result(
            "systems_coaligned",
            passed=False,
            evidence=f"moleculekit selection {selection!r} failed: {exc}",
            config=config,
        )
    if ref_coords.size == 0 or mob_coords.size == 0:
        return _result(
            "systems_coaligned",
            passed=False,
            evidence=f"empty selection {selection!r} on one system",
            config=config,
        )
    # Molecule.get('coords', ...) may return (N, 3, nframes). Take frame 0.
    if ref_coords.ndim == 3:
        ref_coords = ref_coords[..., 0]
    if mob_coords.ndim == 3:
        mob_coords = mob_coords[..., 0]
    ref_centroid = ref_coords.mean(axis=0)
    mob_centroid = mob_coords.mean(axis=0)
    distance = float(np.linalg.norm(ref_centroid - mob_centroid))
    passed = distance <= max_distance_a
    return _result(
        "systems_coaligned",
        passed=passed,
        evidence=(
            f"centroid distance {distance:.2f} Å "
            f"(threshold {max_distance_a:.2f} Å, selection={selection!r})"
        ),
        config=config,
    )


# --- file assertions -------------------------------------------------------

def check_file_exists(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    name = _need(config, "name")
    path = artifact.cell_dir / name
    return _result(
        "file_exists",
        passed=path.exists(),
        evidence=f"{path} {'exists' if path.exists() else 'is missing'}",
        config=config,
    )


def check_file_content_matches(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    name = _need(config, "name")
    pattern = _need(config, "pattern")
    path = artifact.cell_dir / name
    if not path.exists():
        return _result(
            "file_content_matches",
            passed=False,
            evidence=f"{path} is missing",
            config=config,
        )
    content = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(pattern, content)
    if match:
        return _result(
            "file_content_matches",
            passed=True,
            evidence=f"{path} matched {pattern!r} at offset {match.start()}",
            config=config,
        )
    return _result(
        "file_content_matches",
        passed=False,
        evidence=f"{path} did not match {pattern!r}",
        config=config,
    )


# --- registry --------------------------------------------------------------

ASSERTION_REGISTRY: dict[str, Assertion] = {
    "output_contains": check_output_contains,
    "output_matches_regex": check_output_matches_regex,
    "output_numeric_close": check_output_numeric_close,
    "tool_called": check_tool_called,
    "tool_called_with": check_tool_called_with,
    "tool_call_count": check_tool_call_count,
    "tool_call_order": check_tool_call_order,
    "no_tool_error": check_no_tool_error,
    "viewer_has_molecule": check_viewer_has_molecule,
    "viewer_system_count": check_viewer_system_count,
    "system_has_representation": check_system_has_representation,
    "system_representation_residues": check_system_representation_residues,
    "systems_coaligned": check_systems_coaligned,
    "file_exists": check_file_exists,
    "file_content_matches": check_file_content_matches,
}

# ``python_check`` is handled separately in ``run_assertions`` because it
# needs the eval-set's ``checks_module`` — something the built-in
# ``Assertion`` signature does not carry.
PYTHON_CHECK_TYPE = "python_check"

VALID_ASSERTION_TYPES: frozenset[str] = frozenset(
    (*ASSERTION_REGISTRY.keys(), PYTHON_CHECK_TYPE)
)


def _run_python_check(
    artifact: RunArtifact,
    config: dict[str, Any],
    checks_module: ModuleType | None,
) -> AssertionResult:
    func_name = _need(config, "function")
    if checks_module is None:
        raise AssertionConfigError(
            f"python_check {func_name!r}: eval set has no checks.py"
        )
    func = getattr(checks_module, func_name, None)
    if not callable(func):
        available = sorted(
            n for n in dir(checks_module)
            if callable(getattr(checks_module, n)) and not n.startswith("_")
        )
        raise AssertionConfigError(
            f"python_check: {func_name!r} not in checks.py; available: {available}"
        )
    merged = {**config.get("kwargs", {}), "function": func_name}
    try:
        result = func(artifact, merged)
    except Exception as exc:
        logger.exception("python_check %s crashed", func_name)
        return _result(
            PYTHON_CHECK_TYPE,
            passed=False,
            evidence=f"{func_name} raised {type(exc).__name__}: {exc}",
            config=config,
        )
    if not isinstance(result, AssertionResult):
        raise AssertionConfigError(
            f"python_check {func_name!r} must return AssertionResult, "
            f"got {type(result).__name__}"
        )
    return result


def run_assertions(
    artifact: RunArtifact,
    specs: list[dict[str, Any]],
    *,
    checks_module: ModuleType | None = None,
) -> list[AssertionResult]:
    """Apply each spec to ``artifact`` and collect results."""
    results: list[AssertionResult] = []
    for spec in specs:
        assertion_type = spec.get("type")
        if not isinstance(assertion_type, str):
            raise AssertionConfigError(f"assertion missing 'type': {spec}")
        if assertion_type == PYTHON_CHECK_TYPE:
            results.append(_run_python_check(artifact, spec, checks_module))
            continue
        impl = ASSERTION_REGISTRY.get(assertion_type)
        if impl is None:
            raise AssertionConfigError(f"unknown assertion type: {assertion_type}")
        results.append(impl(artifact, spec))
    return results
