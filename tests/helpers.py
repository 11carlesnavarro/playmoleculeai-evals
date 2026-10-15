"""Helpers that more than one test file uses."""

import base64
import json
import sqlite3
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PNG = "data:image/png;base64," + base64.b64encode(b"png").decode()


def make_db(path):
    """A small agent.db with the columns that trial.py and trajectory.py read: a turn with one tool call
    that failed and returned an image, a subagent, and the answer 1.40."""
    call = {"type": "function_call", "name": "pmview_python", "call_id": "c1",
            "arguments": json.dumps({"code": "Molecule('1crn').view()"})}
    output = {"type": "function_call_output", "call_id": "c1", "output": [
        {"type": "input_text", "text": "Code executed successfully."},
        {"type": "input_image", "image_url": PNG}]}
    answer = {"type": "message", "role": "assistant", "content": [{"text": "Done. <answer>1.40</answer>"}]}
    rows = [  # (chat, response, created_at in UTC, item, status)
        (1, "r1", "08:51:48", {"type": "message", "role": "user", "content": [{"text": "Load 1CRN"}]}, None),
        (1, "r1", "08:51:48", {"type": "system_reminder", "content": "<cwd>/app</cwd>"}, None),
        (1, "r1", "08:51:48", {"type": "reasoning", "summary": [{"text": "Use the viewer."}]}, None),
        (1, "r1", "08:51:48", call, None),
        (1, "r1", "08:51:48", output, "error"),
        (2, "s1", "08:51:50", {"type": "message", "role": "assistant", "content": [{"text": "sub"}]}, None),
        (1, "r2", "08:51:52", answer, None),
    ]
    usage = {"input_tokens": 10, "output_tokens": 2, "input_tokens_details": {"cached_tokens": 4}}
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE chats (id INTEGER, is_subagent BOOLEAN);
        CREATE TABLE messages (id INTEGER, chat_id INTEGER, response_id TEXT, created_at TEXT, item_data TEXT,
                               status TEXT);
        CREATE TABLE usage_records (response_id TEXT, usage TEXT, cost_usd FLOAT);
        INSERT INTO chats VALUES (1, 0), (2, 1);
    """)
    con.executemany("INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)",
                    [(n, c, r, f"2026-10-08 {t}", json.dumps(i), s)
                     for n, (c, r, t, i, s) in enumerate(rows)])
    con.executemany("INSERT INTO usage_records VALUES (?, ?, ?)",
                    [("r1", json.dumps(usage), 0.01), ("r2", "{}", 0.02)])
    con.commit()
    con.close()


@contextmanager
def fake_viewer(routes: dict):
    """The sidecar's control API: path -> (status, body). The last POST body is routes["posted"]."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, body = routes.get(self.path, (404, b"no route"))
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
