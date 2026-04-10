"""Programmatic assertions over a single :class:`RunArtifact`.

Each function is pure: ``(artifact, config) -> AssertionResult``. No
network, no disk writes, no LLM calls. ``evidence`` is mandatory whether
the result is pass or fail (spec §4.5).

Adding a new assertion type is one function + one ``ASSERTION_REGISTRY``
entry + one unit test. No other touchpoints.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import Any

from pmai_evals.errors import AssertionConfigError
from pmai_evals.runner.artifacts import RunArtifact
from pmai_evals.schemas import AssertionResult

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


def _walk(state: Any, parent_key: str = "") -> Iterator[tuple[str, Any]]:
    """Recursively yield (key, value) pairs from a viewer-state tree.

    Lists yield each item under the parent key so leaf strings inside a
    list (e.g. ``residues: ["HEM", "ALA"]``) are visible to assertions.
    """
    if isinstance(state, dict):
        for key, value in state.items():
            yield str(key), value
            yield from _walk(value, str(key))
    elif isinstance(state, list):
        for item in state:
            if isinstance(item, (dict, list)):
                yield from _walk(item, parent_key)
            else:
                yield parent_key, item


def _strings_under_key(state: Any, key_substr: str) -> list[str]:
    """All string values whose key (or parent key, for list members) contains
    ``key_substr``. Case-insensitive on both sides."""
    needle = key_substr.lower()
    return [
        str(value).lower()
        for key, value in _walk(state)
        if needle in str(key).lower() and isinstance(value, str)
    ]


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

def _all_string_leaves(state: Any) -> list[str]:
    return [str(value) for _, value in _walk(state) if isinstance(value, str)]


def check_viewer_has_molecule(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    identifier = _need(config, "identifier")
    state = artifact.viewer_state()
    if not state:
        return _result(
            "viewer_has_molecule",
            passed=False,
            evidence="viewer_state.json is empty or missing",
            config=config,
        )
    leaves = _all_string_leaves(state)
    needle = identifier.lower()
    if any(needle in leaf.lower() for leaf in leaves):
        return _result(
            "viewer_has_molecule",
            passed=True,
            evidence=f"identifier {identifier!r} present in systems_tree",
            config=config,
        )
    return _result(
        "viewer_has_molecule",
        passed=False,
        evidence=f"identifier {identifier!r} not present in systems_tree ({len(leaves)} leaves)",
        config=config,
    )


def _check_viewer_key_value(
    *,
    assertion_type: str,
    artifact: RunArtifact,
    config: dict[str, Any],
    key_substr: str,
    expected: str,
    label: str,
) -> AssertionResult:
    observed = _strings_under_key(artifact.viewer_state(), key_substr)
    needle = expected.lower()
    if any(needle in value for value in observed):
        return _result(
            assertion_type,
            passed=True,
            evidence=f"matched {label} {expected!r}",
            config=config,
        )
    return _result(
        assertion_type,
        passed=False,
        evidence=f"no {label} matched {expected!r}; observed: {observed[:5]}",
        config=config,
    )


def check_viewer_representation_is(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    return _check_viewer_key_value(
        assertion_type="viewer_representation_is",
        artifact=artifact,
        config=config,
        key_substr="representation",
        expected=_need(config, "representation"),
        label="representation",
    )


def check_viewer_color_scheme_is(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    return _check_viewer_key_value(
        assertion_type="viewer_color_scheme_is",
        artifact=artifact,
        config=config,
        key_substr="color",
        expected=_need(config, "scheme"),
        label="color scheme",
    )


def check_viewer_has_residue(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    name = _need(config, "name")
    needle = name.upper()
    found = any(needle in leaf.upper() for leaf in _all_string_leaves(artifact.viewer_state()))
    return _result(
        "viewer_has_residue",
        passed=found,
        evidence=(
            f"residue {name!r} present in viewer state"
            if found
            else f"residue {name!r} not present in viewer state"
        ),
        config=config,
    )


def check_viewer_system_count(artifact: RunArtifact, config: dict[str, Any]) -> AssertionResult:
    expected = int(_need(config, "value"))
    op = config.get("op", "==")
    state = artifact.viewer_state()
    systems = state.get("systems") if isinstance(state, dict) else None
    count = len(systems) if isinstance(systems, list) else 0
    return _result(
        "viewer_system_count",
        passed=_compare(count, op, expected),
        evidence=f"{count} systems loaded (expected {op} {expected})",
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
    "viewer_representation_is": check_viewer_representation_is,
    "viewer_color_scheme_is": check_viewer_color_scheme_is,
    "viewer_has_residue": check_viewer_has_residue,
    "viewer_system_count": check_viewer_system_count,
    "file_exists": check_file_exists,
    "file_content_matches": check_file_content_matches,
}


def run_assertions(
    artifact: RunArtifact,
    specs: list[dict[str, Any]],
) -> list[AssertionResult]:
    """Apply each spec to ``artifact`` and collect results."""
    results: list[AssertionResult] = []
    for spec in specs:
        assertion_type = spec.get("type")
        if not isinstance(assertion_type, str):
            raise AssertionConfigError(f"assertion missing 'type': {spec}")
        impl = ASSERTION_REGISTRY.get(assertion_type)
        if impl is None:
            raise AssertionConfigError(f"unknown assertion type: {assertion_type}")
        results.append(impl(artifact, spec))
    return results
