"""What a test can ask about a finished trial. Stdlib only: it runs in the grader venv and on the host."""

import json
import os
import re
import sqlite3
import urllib.request
from pathlib import Path

LOGS = Path(os.environ.get("TRIAL_LOGS", "/logs/agent"))  # set it to grade a hand run on the host
DB = LOGS / "home" / "agent.db"
_work = LOGS / "work_dir"
WORK = Path(_work.read_text().strip()) if _work.exists() else Path("/app")
VIEWER = "http://viewer:9000"


def q(sql: str, *args, db: Path | None = None) -> list[tuple]:
    con = sqlite3.connect(f"file:{db or DB}?mode=ro", uri=True)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def items(main_only: bool = True) -> list[dict]:
    where = "WHERE NOT c.is_subagent" if main_only else ""
    rows = q(f"SELECT m.item_data FROM messages m JOIN chats c ON c.id = m.chat_id {where} ORDER BY m.id")
    return [json.loads(r[0]) for r in rows]


def answer() -> str:
    said = [i for i in items() if i.get("role") == "assistant"]
    return "".join(p.get("text", "") for p in said[-1]["content"]) if said else ""


def tag(name: str = "answer") -> str | None:  # <answer>1.40</answer>
    m = re.search(rf"<{name}>(.*?)</{name}>", answer(), re.S)
    return m.group(1).strip() if m else None


def tool_calls(name: str | None = None) -> list[dict]:
    return [i for i in items(False) if i.get("type") == "function_call" and name in (None, i["name"])]


def tool_errors() -> list[tuple]:
    return q(
        "SELECT item_data FROM messages WHERE status = 'error' "
        "AND json_extract(item_data, '$.type') = 'function_call_output'"
    )


def read_skill(name: str) -> bool:
    return any(f"skills/{name}/SKILL.md" in c["arguments"] for c in tool_calls())


def usage(db: Path | None = None) -> dict:
    rows = q("SELECT usage, cost_usd FROM usage_records", db=db)
    u = [json.loads(r[0] or "{}") for r in rows]
    return {
        "input_tokens": sum(x.get("input_tokens", 0) for x in u),
        "cached_tokens": sum((x.get("input_tokens_details") or {}).get("cached_tokens", 0) for x in u),
        "output_tokens": sum(x.get("output_tokens", 0) for x in u),
        "cost_usd": sum(r[1] or 0 for r in rows),
    }


def cost_usd() -> float:
    return usage()["cost_usd"]


def viewer_get(path: str) -> bytes:  # viewer tasks only (phase 5)
    with urllib.request.urlopen(VIEWER + path, timeout=300) as r:
        return r.read()


def viewer_state():
    return json.loads(viewer_get("/state"))


def viewer_selection():
    return json.loads(viewer_get("/selection"))
