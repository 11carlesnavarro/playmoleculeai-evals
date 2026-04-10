"""Read/write artifacts for one (case × model × seed) cell.

Layout (spec §4.4):

    runs/<run_id>/<case_id>/<model>/seed-<N>/
        trace.json
        final_answer.md
        viewer_state.json
        screenshot.png
        dom_snapshot.html        (optional)
        metrics.json
        grade.json               (written by grade stage; absent until then)
        status                   (one-line plain text)

Write-once. The runner never overwrites a completed cell — re-runs go to a
fresh ``run_id``.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from pmai_evals._io import read_json, read_json_or, write_json
from pmai_evals.schemas import CaseGrade, CaseStatus
from pmai_evals.trace.schemas import Trace


@dataclass
class _CellPaths:
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
    def screenshot_path(self) -> Path:
        return self.cell_dir / "screenshot.png"

    @property
    def dom_snapshot_path(self) -> Path:
        return self.cell_dir / "dom_snapshot.html"

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


# --- writer ---------------------------------------------------------------

@dataclass
class RunArtifactWriter(_CellPaths):
    """Writer for one cell. Constructed by the executor per case/model/seed."""

    def ensure_dir(self) -> None:
        self.cell_dir.mkdir(parents=True, exist_ok=True)

    def write_trace(self, trace: Trace) -> None:
        write_json(self.trace_path, trace.to_dict())

    def write_final_answer(self, text: str) -> None:
        self.cell_dir.mkdir(parents=True, exist_ok=True)
        self.final_answer_path.write_text(text.rstrip("\n") + "\n", encoding="utf-8")

    def write_viewer_state(self, state: dict[str, Any]) -> None:
        write_json(self.viewer_state_path, state)

    def write_metrics(self, metrics: dict[str, Any]) -> None:
        write_json(self.metrics_path, metrics)

    def write_status(self, status: CaseStatus | str) -> None:
        self.cell_dir.mkdir(parents=True, exist_ok=True)
        self.status_path.write_text(str(status) + "\n", encoding="utf-8")

    def write_error(self, message: str) -> None:
        self.cell_dir.mkdir(parents=True, exist_ok=True)
        self.error_path.write_text(message + "\n", encoding="utf-8")

    def attach_screenshot(self, src: Path) -> None:
        self.cell_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, self.screenshot_path)

    def write_grade(self, grade: CaseGrade) -> None:
        write_json(self.grade_path, grade.model_dump(mode="json"))


# --- reader ---------------------------------------------------------------

@dataclass
class RunArtifact(_CellPaths):
    """Read-only view over one cell on disk. Passed to assertions and judges.

    Per-cell loaders are memoized: a single ``RunArtifact`` instance reads
    each artifact at most once. Assertions and the judge both call into
    ``trace()`` / ``final_answer()`` / ``viewer_state()`` repeatedly, so
    memoization saves significant JSON decoding on every grade pass.
    """

    @cached_property
    def _trace(self) -> dict[str, Any]:
        return read_json_or(self.trace_path, {})

    @cached_property
    def _viewer_state(self) -> dict[str, Any]:
        return read_json_or(self.viewer_state_path, {})

    @cached_property
    def _metrics(self) -> dict[str, Any]:
        return read_json_or(self.metrics_path, {})

    @cached_property
    def _final_answer(self) -> str:
        if not self.final_answer_path.exists():
            return ""
        return self.final_answer_path.read_text(encoding="utf-8")

    def trace(self) -> dict[str, Any]:
        return self._trace

    def viewer_state(self) -> dict[str, Any]:
        return self._viewer_state

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


# --- discovery ------------------------------------------------------------

def _cell_from_dir(run_dir: Path, cell_dir: Path) -> _CellPaths | None:
    seed_part = cell_dir.name
    model = cell_dir.parent.name
    case_id = cell_dir.parent.parent.name
    try:
        seed = int(seed_part.split("-", 1)[1])
    except (IndexError, ValueError):
        return None
    return _CellPaths(run_dir=run_dir, case_id=case_id, model=model, seed=seed)


def iter_cell_paths(run_dir: Path) -> Iterator[_CellPaths]:
    """Yield one ``_CellPaths`` per cell directory under ``run_dir``.

    A cell is identified by its ``status`` file — what the runner writes
    last, the canonical "cell exists" marker. Use this for run-stage
    discovery.
    """
    for status_file in run_dir.glob("*/*/seed-*/status"):
        cell = _cell_from_dir(run_dir, status_file.parent)
        if cell is not None:
            yield cell


def iter_grade_files(run_dir: Path) -> Iterator[tuple[_CellPaths, dict[str, Any]]]:
    """Yield ``(cell, grade.json)`` pairs by globbing grade files directly.

    Independent of the status-file convention so grading-only tests and
    re-grading flows do not need to fake runner state.
    """
    for grade_file in run_dir.glob("*/*/seed-*/grade.json"):
        cell = _cell_from_dir(run_dir, grade_file.parent)
        if cell is not None:
            yield cell, read_json(grade_file)
