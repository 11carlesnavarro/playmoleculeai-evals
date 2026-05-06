"""Read/write artifacts for one (case × model × seed) cell.

Layout:

    runs/<run_id>/<case_id>/<model>/seed-<N>/
        trace.json
        final_answer.md
        viewer_state.json
        viewer_selection.json
        screenshot.png
        metrics.json
        grade.json    (written by grade stage; absent until then)
        status        (one-line plain text)

Write-once. The runner never overwrites a completed cell, re-runs go to a
fresh ``run_id``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

from pmai_evals._io import read_json, read_json_or, write_json
from pmai_evals.schemas import CaseGrade, CaseStatus
from pmai_evals.trace.schemas import Trace


@dataclass
class CellPaths:
    """Address of one (case × model × seed) cell on disk.

    All path properties live here so :class:`RunArtifact` (read) and
    :class:`RunArtifactWriter` (write) cannot drift out of sync.
    """

    run_dir: Path
    case_id: str
    model: str
    seed: int

    @property
    def cell_dir(self) -> Path:
        return self.run_dir / self.case_id / self.model / f"seed-{self.seed}"

    @property
    def trace_path(self) -> Path:
        return self.cell_dir / "trace.json"

    @property
    def final_answer_path(self) -> Path:
        return self.cell_dir / "final_answer.md"

    @property
    def viewer_state_path(self) -> Path:
        return self.cell_dir / "viewer_state.json"

    @property
    def viewer_selection_path(self) -> Path:
        return self.cell_dir / "viewer_selection.json"

    @property
    def screenshot_path(self) -> Path:
        return self.cell_dir / "screenshot.png"

    @property
    def metrics_path(self) -> Path:
        return self.cell_dir / "metrics.json"

    @property
    def grade_path(self) -> Path:
        return self.cell_dir / "grade.json"

    @property
    def status_path(self) -> Path:
        return self.cell_dir / "status"

    @property
    def error_path(self) -> Path:
        return self.cell_dir / "error.txt"

    @property
    def systems_dir(self) -> Path:
        return self.cell_dir / "systems"


# --- writer ---------------------------------------------------------------

@dataclass
class RunArtifactWriter(CellPaths):
    """Writer for one cell. Constructed by the executor per case/model/seed."""

    def ensure_dir(self) -> None:
        self.cell_dir.mkdir(parents=True, exist_ok=True)
        # A stale grade.json from a previous run of this cell would make the
        # grader's "already graded, skip" guard fire against new artifacts.
        self.grade_path.unlink(missing_ok=True)

    def write_trace(self, trace: Trace) -> None:
        write_json(self.trace_path, trace.to_dict())

    def write_final_answer(self, text: str) -> None:
        self.cell_dir.mkdir(parents=True, exist_ok=True)
        self.final_answer_path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")

    def write_viewer_state(self, state: Any) -> None:
        write_json(self.viewer_state_path, state)

    def write_viewer_selection(self, selection: Any) -> None:
        write_json(self.viewer_selection_path, selection)

    def write_metrics(self, metrics: dict[str, Any]) -> None:
        write_json(self.metrics_path, metrics)

    def write_status(self, status: CaseStatus | str) -> None:
        self.cell_dir.mkdir(parents=True, exist_ok=True)
        self.status_path.write_text(str(status) + "\n", encoding="utf-8")

    def write_error(self, message: str) -> None:
        self.cell_dir.mkdir(parents=True, exist_ok=True)
        self.error_path.write_text(message + "\n", encoding="utf-8")

    def write_grade(self, grade: CaseGrade) -> None:
        write_json(self.grade_path, grade.model_dump(mode="json"))


# --- reader ---------------------------------------------------------------

@dataclass
class RunArtifact(CellPaths):
    """Read-only view over one cell on disk. Passed to assertions and judges.

    Per-cell loaders are memoized so each artifact is read at most once
    per :class:`RunArtifact` instance.
    """

    _loaded_systems: dict[str, Any] = field(
        default_factory=dict, init=False, repr=False
    )

    @cached_property
    def _trace(self) -> dict[str, Any]:
        return read_json_or(self.trace_path, {})

    @cached_property
    def _viewer_state(self) -> Any:
        return read_json_or(self.viewer_state_path, {})

    @cached_property
    def _viewer_selection(self) -> Any:
        return read_json_or(self.viewer_selection_path, {})

    @cached_property
    def _metrics(self) -> dict[str, Any]:
        return read_json_or(self.metrics_path, {})

    @cached_property
    def _final_answer(self) -> str:
        return (
            self.final_answer_path.read_text(encoding="utf-8")
            if self.final_answer_path.exists() else ""
        )

    def trace(self) -> dict[str, Any]:
        return self._trace

    def viewer_state(self) -> Any:
        return self._viewer_state

    def viewer_selection(self) -> Any:
        return self._viewer_selection

    def metrics(self) -> dict[str, Any]:
        return self._metrics

    def final_answer(self) -> str:
        return self._final_answer

    def status(self) -> str:
        if not self.status_path.exists():
            return "unknown"
        return self.status_path.read_text(encoding="utf-8").strip()

    def screenshot_bytes(self) -> bytes | None:
        if not self.screenshot_path.exists():
            return None
        return self.screenshot_path.read_bytes()

    # ---- systems (exported viewer state) -------------------------------

    @cached_property
    def _systems_export_dir(self) -> Path | None:
        """Path to the extracted ``pmv_*`` directory inside ``systems/``."""
        if not self.systems_dir.is_dir():
            return None
        for child in sorted(self.systems_dir.iterdir()):
            if child.is_dir() and child.name.startswith("pmv_"):
                return child
        return None

    @cached_property
    def _system_files(self) -> list[tuple[str, Path]]:
        from pmai_evals.browser.viewer_loader import strip_export_prefix

        root = self._systems_export_dir
        if root is None:
            return []
        return [
            (strip_export_prefix(path.stem), path)
            for path in sorted(root.rglob("*"))
            if path.is_file() and path.name != "config.pmv"
        ]

    def system_files(self) -> list[tuple[str, Path]]:
        """``(logical_name, path)`` per exported structure; [] if none."""
        return self._system_files

    def load_system(self, name: str) -> Any:
        """Moleculekit ``Molecule`` for the named system. Raises ``KeyError``."""
        key = name.lower()
        cache = self._loaded_systems
        if key in cache:
            return cache[key]
        for logical, path in self._system_files:
            if logical.lower() == key:
                from moleculekit.molecule import Molecule  # type: ignore[import-not-found]

                mol = Molecule(str(path))
                cache[key] = mol
                return mol
        available = [n for n, _ in self._system_files]
        raise KeyError(f"system {name!r} not in export; available: {available}")


# --- discovery ------------------------------------------------------------

def _cell_from_dir(run_dir: Path, cell_dir: Path) -> CellPaths | None:
    try:
        seed = int(cell_dir.name.split("-", 1)[1])
    except (IndexError, ValueError):
        return None
    return CellPaths(
        run_dir=run_dir,
        case_id=cell_dir.parent.parent.name,
        model=cell_dir.parent.name,
        seed=seed,
    )


def iter_cell_paths(run_dir: Path) -> Iterator[CellPaths]:
    """Yield one ``CellPaths`` per cell directory under ``run_dir``.

    A cell is identified by its ``status`` file (what the runner writes last).
    """
    for status_file in run_dir.glob("*/*/seed-*/status"):
        cell = _cell_from_dir(run_dir, status_file.parent)
        if cell is not None:
            yield cell


def iter_grade_files(run_dir: Path) -> Iterator[tuple[CellPaths, dict[str, Any]]]:
    """Yield ``(cell, grade.json)`` pairs by globbing grade files directly."""
    for grade_file in run_dir.glob("*/*/seed-*/grade.json"):
        cell = _cell_from_dir(run_dir, grade_file.parent)
        if cell is not None:
            yield cell, read_json(grade_file)
