import json
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pmai_evals import trial
from pmai_evals.reward import InfraError


def make_db(path):
    """A small agent.db with only the columns that trial.py reads."""
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE chats (id INTEGER PRIMARY KEY, is_subagent BOOLEAN);
        CREATE TABLE messages (id INTEGER PRIMARY KEY, chat_id INTEGER, item_data TEXT, status TEXT);
        CREATE TABLE usage_records (usage TEXT, cost_usd REAL);
        INSERT INTO chats VALUES (1, 0), (2, 1);
    """)
    rows = [
        (1, {"type": "function_call", "name": "run_bash", "call_id": "a", "arguments": "{}"}, None),
        (1, {"type": "function_call_output", "call_id": "a", "output": []}, "error"),
        (2, {"type": "message", "role": "assistant", "content": [{"text": "sub"}]}, None),
        (1, {"type": "message", "role": "assistant", "content": [{"text": "x <answer>1.40</answer>"}]}, None),
    ]
    con.executemany(
        "INSERT INTO messages (chat_id, item_data, status) VALUES (?, ?, ?)",
        [(c, json.dumps(i), s) for c, i, s in rows],
    )
    con.execute(
        "INSERT INTO usage_records VALUES (?, ?)",
        (
            json.dumps(
                {"input_tokens": 10, "input_tokens_details": {"cached_tokens": 4}, "output_tokens": 3}
            ),
            0.25,
        ),
    )
    con.commit()
    con.close()


def test_trial(tmp_path, monkeypatch):
    make_db(tmp_path / "agent.db")
    monkeypatch.setattr(trial, "DB", tmp_path / "agent.db")
    assert trial.tag() == "1.40"  # main chat only, not the subagent
    assert [c["name"] for c in trial.tool_calls()] == ["run_bash"]
    assert len(trial.tool_errors()) == 1
    assert trial.usage() == {"input_tokens": 10, "cached_tokens": 4, "output_tokens": 3, "cost_usd": 0.25}


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
        w.execute("INSERT INTO usage_records VALUES ('{}', 0.5)")
    killed = read_only(tmp_path / "killed", db, *tmp_path.glob("agent.db-*"))
    keeper.close()
    try:
        assert trial.usage(clean)["cost_usd"] == 0.25
        assert trial.usage(killed)["cost_usd"] == 0.75
    finally:
        for d in (clean.parent, killed.parent):
            d.chmod(0o755)


@contextmanager
def fake_viewer(routes: dict):
    """The sidecar's control API: path -> (status, body). The last POST body is routes["posted"]."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, body = routes[self.path]
            self.send_response(status)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            routes["posted"] = self.rfile.read(int(self.headers["Content-Length"])).decode()
            self.do_GET()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True).start()  # 0.01: fast shutdown
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


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
    with pytest.raises(InfraError, match="Connection refused"):
        trial.viewer_screenshot()
