"""agent.db -> agent/trajectory.json, with the sidecar's screenshots in their steps."""

import json
from datetime import UTC, datetime

from helpers import make_db
from pmai_evals import trajectory


def test_write(tmp_path):
    (tmp_path / "agent/home").mkdir(parents=True)
    make_db(tmp_path / "agent/home/agent.db")
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
    assert (done["message"], "observation" in done) == ("Done. <answer>1.40</answer>", False)
    assert out["final_metrics"]["total_cost_usd"] == 0.03
    assert out["agent"] == {"name": "pmai", "version": "unknown", "model_name": "gpt-6-luna"}
