import json
import sqlite3

from pmai_evals import trial


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
