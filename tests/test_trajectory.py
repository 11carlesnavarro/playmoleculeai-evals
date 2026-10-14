"""agent.db -> agent/trajectory.json, with the sidecar's screenshots in their steps."""

import base64
import json
import sqlite3
from datetime import UTC, datetime

from pmai_evals import trajectory

PNG = "data:image/png;base64," + base64.b64encode(b"png").decode()
SCHEMA = """
CREATE TABLE chats (id INTEGER, is_subagent BOOLEAN);
CREATE TABLE messages (id INTEGER, chat_id INTEGER, response_id TEXT, created_at TEXT, item_data TEXT);
CREATE TABLE usage_records (response_id TEXT, usage TEXT, cost_usd FLOAT);
INSERT INTO chats VALUES (1, 0), (2, 1);
"""


def agent_db(path):
    call = {"type": "function_call", "name": "pmview_python", "call_id": "c1",
            "arguments": json.dumps({"code": "Molecule('1crn').view()"})}
    output = {"type": "function_call_output", "call_id": "c1", "output": [
        {"type": "input_text", "text": "Code executed successfully."},
        {"type": "input_image", "image_url": PNG}]}
    rows = [  # (chat, response, created_at in UTC, item)
        (1, "r1", "08:51:48", {"type": "message", "role": "user", "content": [{"text": "Load 1CRN"}]}),
        (1, "r1", "08:51:48", {"type": "system_reminder", "content": "<cwd>/app</cwd>"}),
        (1, "r1", "08:51:48", {"type": "reasoning", "summary": [{"text": "Use the viewer."}]}),
        (1, "r1", "08:51:48", call),
        (1, "r1", "08:51:48", output),
        (2, "s1", "08:51:50", {"type": "message", "role": "assistant", "content": [{"text": "sub"}]}),
        (1, "r2", "08:51:52", {"type": "message", "role": "assistant", "content": [{"text": "Done."}]}),
    ]
    usage = {"input_tokens": 10, "output_tokens": 2, "input_tokens_details": {"cached_tokens": 4}}
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany("INSERT INTO messages VALUES (?, ?, ?, ?, ?)",
                    [(n, c, r, f"2026-10-08 {t}", json.dumps(i)) for n, (c, r, t, i) in enumerate(rows)])
    con.executemany("INSERT INTO usage_records VALUES (?, ?, ?)",
                    [("r1", json.dumps(usage), 0.01), ("r2", "{}", 0.02)])
    con.commit()
    con.close()


def test_write(tmp_path):
    (tmp_path / "agent/home").mkdir(parents=True)
    agent_db(tmp_path / "agent/home/agent.db")
    viewer = tmp_path / trajectory.VIEWER
    (viewer / "steps").mkdir(parents=True)
    (viewer / "steps/000.jpg").write_bytes(b"jpg")
    back = datetime(2026, 10, 8, 8, 51, 47, tzinfo=UTC).timestamp()  # before agent.db saved r1
    events = [{"t": back, "event": "pmai_result", "shot": "steps/000.jpg"},
              {"t": back + 9, "event": "pmai_result", "shot": "steps/001.jpg"}]  # no file: no picture
    (viewer / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))

    out = json.loads(trajectory.write(tmp_path / "agent", "pmai", None, "gpt-6-luna").read_text())

    user, call, done = out["steps"]  # no system reminder, no subagent
    assert (user["source"], user["message"]) == ("user", "Load 1CRN")
    assert call["reasoning_content"] == "Use the viewer."
    assert call["tool_calls"] == [{"tool_call_id": "c1", "function_name": "pmview_python",
                                   "arguments": {"code": "Molecule('1crn').view()"}}]
    parts = call["observation"]["results"][0]["content"]
    images = [p["source"]["path"] for p in parts if p["type"] == "image"]
    assert images == ["images/c1-1.png", "images/viewer-000.jpg"]  # pmai's own picture, then the sidecar's
    assert (tmp_path / "agent/images/c1-1.png").read_bytes() == b"png"
    assert call["metrics"] == {"prompt_tokens": 10, "completion_tokens": 2, "cached_tokens": 4,
                               "cost_usd": 0.01}
    assert (done["message"], "observation" in done) == ("Done.", False)
    assert out["final_metrics"]["total_cost_usd"] == 0.03
    assert out["agent"] == {"name": "pmai", "version": "unknown", "model_name": "gpt-6-luna"}
