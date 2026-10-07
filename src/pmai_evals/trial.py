"""What a test can ask about a finished trial. Stdlib only: it runs in the grader venv and on the host."""

import json
import os
import re
import shutil
import sqlite3
import tempfile
import urllib.error
import urllib.request
from functools import cache
from pathlib import Path

from pmai_evals.reward import InfraError

LOGS = Path(os.environ.get("TRIAL_LOGS", "/logs/agent"))  # set it to grade a hand run on the host
DB = LOGS / "home" / "agent.db"
_work = LOGS / "work_dir"
WORK = Path(_work.read_text().strip()) if _work.exists() else Path("/app")
VIEWER = os.environ.get("VIEWER_URL")  # viewer tasks only: viewer/compose.yaml sets it


@cache
def _readable(db: Path) -> Path:
    """agent.db is in WAL mode, so a reader must create agent.db-shm next to it. On the host, the files
    from the container can belong to nobody (NFS root squash): then read a copy."""
    if os.access(db.parent, os.W_OK):
        return db
    tmp = Path(tempfile.mkdtemp(prefix="trial-db-"))
    for f in (db, db.with_name(db.name + "-wal")):  # the WAL holds what a killed agent did not checkpoint
        if f.exists():
            shutil.copy(f, tmp)
    return tmp / db.name


def q(sql: str, *args, db: Path | None = None) -> list[tuple]:
    con = sqlite3.connect(f"file:{_readable(db or DB)}?mode=ro", uri=True)
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


def _viewer(path: str, data: bytes | None = None) -> bytes:
    """The viewer sidecar's control API (viewer/server.py). A sidecar that cannot answer is an infra
    error: the trial gets no reward, not a 0."""
    if not VIEWER:
        raise InfraError("no viewer: the job must add viewer/compose.yaml")
    try:
        with urllib.request.urlopen(VIEWER + path, data, timeout=300) as r:
            return r.read()
    except urllib.error.HTTPError as e:  # 502: the PMView tool failed. Else the sidecar cannot answer
        error = RuntimeError if e.code == 502 else InfraError
        raise error(f"viewer {path}: {e.code} {e.read().decode(errors='replace')}") from None
    except OSError as e:
        raise InfraError(f"viewer {path}: {e}") from e


def viewer_python(code: str) -> dict:
    """Run code in PMView, as the agent's pmview_run_python: {stdout, stderr, result}.
    pmv, Molecule and np are already imported there."""
    return json.loads(_viewer("/python", code.encode()))


def _pmv(value: str, before: str = ""):
    out = viewer_python(f"import json\n{before}\nprint(json.dumps({value}, default=str))")
    try:
        return json.loads(out["stdout"])
    except (KeyError, ValueError):
        raise RuntimeError(f"viewer python: {out.get('stderr') or out.get('error')}") from None


def viewer_state() -> dict:  # {"systems", "tables", "plots", "files"}
    return _pmv("pmv.get_viewer_state()")


def viewer_selection() -> dict:
    # TypeError: no selection yet
    return _pmv("dict(s or {})", "try:\n    s = pmv.get_viewer_selection()\nexcept TypeError:\n    s = None")


def viewer_system(uuid: str) -> str:
    """A system in the viewer, as PDB text."""
    return _pmv("open('/tmp/eval.pdb').read()", f"pmv.get_system({uuid!r}).write('/tmp/eval.pdb')")


def viewer_screenshot() -> bytes:  # PNG
    return _viewer("/screenshot")
