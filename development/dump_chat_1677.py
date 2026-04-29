"""Dump chat 1677 (open db) to JSONL."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB = "file:/fast_shared/users/carles/data/playmoleculeAIdata/data/databases/open/agent.db?mode=ro"
CHAT_ID = 1677
OUT = Path(__file__).parent / "chat_1677.jsonl"

conn = sqlite3.connect(DB, uri=True)
conn.row_factory = sqlite3.Row
chat = conn.execute(
    "SELECT id, chat_uid, user_id, project, parent_id, summary, "
    "instructions, created_at, deleted_at FROM chats WHERE id = ?",
    (CHAT_ID,),
).fetchone()
rows = conn.execute(
    "SELECT id, message_uid, chat_id, parent_id, response_id, item_index, "
    "item_data, model, usage, status, created_at, start_time, "
    "first_token_time, end_time, latency_ms, ttft_ms, tool_latency, rating "
    "FROM messages WHERE chat_id = ? ORDER BY id",
    (CHAT_ID,),
).fetchall()

with OUT.open("w") as f:
    f.write(json.dumps({"_chat": dict(chat)}, default=str) + "\n")
    for r in rows:
        d = dict(r)
        d["item_data"] = json.loads(d["item_data"])
        if d.get("usage"):
            d["usage"] = json.loads(d["usage"])
        f.write(json.dumps(d, default=str) + "\n")
print(f"wrote {len(rows)} messages to {OUT}")
