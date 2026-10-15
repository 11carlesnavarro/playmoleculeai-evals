import ast
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

from helpers import fake_viewer, make_db
from pmai_evals import reward, trial
from pmai_evals.reward import InfraError


def test_stdlib_only():
    """trial.py and reward.py run in the grader venv and on the host: the stdlib only."""
    for module in (trial, reward):
        tree = ast.parse(Path(module.__file__).read_text())
        names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        outside = {x.split(".")[0] for x in names} - sys.stdlib_module_names - {"pmai_evals"}
        assert not outside, f"{module.__name__} imports {outside}"


def test_trial(tmp_path, monkeypatch):
    make_db(tmp_path / "agent.db")
    monkeypatch.setattr(trial, "DB", tmp_path / "agent.db")
    assert trial.tag() == "1.40"  # main chat only, not the subagent
    assert [c["name"] for c in trial.tool_calls()] == ["pmview_python"]
    assert len(trial.tool_errors()) == 1
    assert trial.usage() == {"input_tokens": 10, "cached_tokens": 4, "output_tokens": 2, "cost_usd": 0.03}


def read_only(folder, *files):
    """Copy files into a folder that the test user cannot write: the host view of a trial."""
    folder.mkdir()
    for f in files:
        shutil.copy(f, folder)
        (folder / f.name).chmod(0o444)
    folder.chmod(0o555)
    return folder / "agent.db"


def test_read_only_folder(tmp_path):
    db = tmp_path / "agent.db"
    make_db(db)
    sqlite3.connect(db).execute("PRAGMA journal_mode=WAL").fetchall()  # as pmai: the mode stays in the file
    keeper = sqlite3.connect(db)  # while it reads, a new row stays in agent.db-wal, as with a killed agent
    keeper.execute("SELECT 1 FROM chats").fetchall()
    clean = read_only(tmp_path / "clean", db)  # pmai exited: no -wal, no -shm
    with sqlite3.connect(db) as w:
        w.execute("INSERT INTO usage_records VALUES ('r3', '{}', 0.5)")
    killed = read_only(tmp_path / "killed", db, *tmp_path.glob("agent.db-*"))
    keeper.close()
    try:
        assert trial._readable(clean) != clean  # a copy: the test user cannot write the folder
        assert trial.usage(clean)["cost_usd"] == 0.03
        assert trial.usage(killed)["cost_usd"] == 0.53
    finally:
        for d in (clean.parent, killed.parent):
            d.chmod(0o755)


def test_viewer(tmp_path, monkeypatch):
    monkeypatch.setattr(trial, "FINAL_VIEW", tmp_path / "viewer" / "final-view.png")
    routes = {"/python": (200, b'{"stdout": "2\\n", "stderr": ""}'), "/screenshot": (200, b"PNG")}
    with fake_viewer(routes) as url:
        monkeypatch.setattr(trial, "VIEWER", url)
        assert trial.viewer_python("print(1 + 1)")["stdout"] == "2\n"
        assert routes["posted"] == "print(1 + 1)"
        assert trial.final_image().read_bytes() == b"PNG"
        routes["/screenshot"] = (200, b"later")
        assert trial.final_image().read_bytes() == b"PNG"  # kept: a regrade sees the same image
        routes["/screenshot"] = (503, b"page crashed")
        with pytest.raises(InfraError, match="503 page crashed"):
            trial.viewer_screenshot()
        routes["/python"] = (502, b"pmview_run_python: Pyodide crashed")  # PMView broke its API: a fail
        with pytest.raises(RuntimeError, match="502 pmview_run_python: Pyodide crashed"):
            trial.viewer_python("1")
    monkeypatch.setattr(trial, "VIEWER", None)
    with pytest.raises(InfraError, match="the task needs"):
        trial.viewer_screenshot()
    monkeypatch.setattr(trial, "VIEWER", url)  # the server is gone
    with pytest.raises(InfraError, match=r"viewer /screenshot: .*Connection refused"):
        trial.viewer_screenshot()
