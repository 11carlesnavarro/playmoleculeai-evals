"""JSON / file I/O helpers shared across the harness.

All JSON files use UTF-8, 2-space indent, sorted keys, and a trailing
newline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_json(path: Path, payload: Any) -> None:
    """Write ``payload`` as canonical JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    path.write_text(text + "\n", encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_json_or(path: Path, default: Any) -> Any:
    """Like :func:`read_json` but returns ``default`` for missing files."""
    return read_json(path) if path.exists() else default


def parse_json_lenient(value: Any) -> Any:
    """Coerce a value that may be JSON, already-parsed, or unparseable.

    Returns ``None`` if the value can't be coerced; never raises.
    """
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None
