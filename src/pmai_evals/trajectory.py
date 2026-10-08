"""agent.db -> agent/trajectory.json (Harbor's ATIF), so `make view` shows each step of the turn.

agent.py writes it after the turn. For trials that are already done:
    uv run python -m pmai_evals.trajectory results/<job>/<trial> ...
Viewer tasks: each step also shows the viewer page after each of its viewer commands (the sidecar's
screenshots). Only the main chat: a subagent's steps are in agent.db.
"""

import base64
import json
import shutil
import sys
from datetime import UTC, datetime
from itertools import groupby
from pathlib import Path

from harbor.models.trajectories import (
    Agent,
    ContentPart,
    FinalMetrics,
    ImageSource,
    Metrics,
    Observation,
    ObservationResult,
    Step,
    ToolCall,
    Trajectory,
)

from pmai_evals import trial

VIEWER = "artifacts/logs/artifacts/viewer"  # the sidecar's evidence, in the trial folder


def write(agent_dir: Path, name: str, version: str | None, model: str | None) -> Path:
    """agent_dir: the trial's agent/ folder (Harbor's logs_dir for the agent)."""
    db = agent_dir / "home" / "agent.db"
    images = agent_dir / "images"  # ATIF images are files, relative to agent/
    images.mkdir(exist_ok=True)
    rows = trial.q(
        "SELECT m.response_id, m.created_at, m.item_data FROM messages m JOIN chats c ON c.id = m.chat_id "
        "WHERE NOT c.is_subagent ORDER BY m.id",
        db=db,
    )
    usage = {r: (json.loads(u or "{}"), cost) for r, u, cost in
             trial.q("SELECT response_id, usage, cost_usd FROM usage_records", db=db)}
    shots, steps, since = _viewer_shots(agent_dir.parent), [], 0.0
    for response_id, group in groupby(rows, key=lambda r: r[0]):
        group = list(group)
        items, created = [json.loads(r[2]) for r in group], group[-1][1]
        when = datetime.fromisoformat(created).replace(tzinfo=UTC)
        for item in items:
            if item.get("type") == "message" and item.get("role") == "user":
                steps.append(Step(step_id=len(steps) + 1, timestamp=when.isoformat(), source="user",
                                  message=_text(item.get("content"))))
        calls = [i for i in items if i.get("type") == "function_call"]
        results = [ObservationResult(source_call_id=i["call_id"], content=_content(i.get("output"), images,
                                                                                    i["call_id"]))
                   for i in items if i.get("type") == "function_call_output"]
        # the viewer after each command: the sidecar saw the result before pmai saved this response
        mine = [s for s in shots if since < s[0] <= when.timestamp()]
        since = when.timestamp()
        if mine:
            pages = [ContentPart(type="text", text="The viewer page after the command (sidecar):")]
            for _, shot in mine:
                shutil.copy(shot, images / f"viewer-{shot.name}")
                pages.append(_image(f"viewer-{shot.name}"))
            ids = {c["call_id"] for c in calls if c["name"].startswith("pmview")}
            viewer = [r for r in results if r.source_call_id in ids]
            if viewer and isinstance(viewer[-1].content, list):
                viewer[-1].content += pages
            else:
                results.append(ObservationResult(content=pages))
        reasoning = "\n\n".join(s.get("text", "") for i in items if i.get("type") == "reasoning"
                                for s in i.get("summary") or [])
        said = "".join(_text(i.get("content")) for i in items
                       if i.get("type") == "message" and i.get("role") == "assistant")
        if not (calls or reasoning or said):
            continue
        u, cost = usage.get(response_id, ({}, None))
        steps.append(Step(
            step_id=len(steps) + 1, timestamp=when.isoformat(), source="agent", model_name=model,
            message=said, reasoning_content=reasoning or None,
            tool_calls=[ToolCall(tool_call_id=c["call_id"], function_name=c["name"],
                                 arguments=json.loads(c.get("arguments") or "{}")) for c in calls] or None,
            observation=Observation(results=results) if results else None,
            metrics=Metrics(prompt_tokens=u.get("input_tokens"), completion_tokens=u.get("output_tokens"),
                            cached_tokens=(u.get("input_tokens_details") or {}).get("cached_tokens"),
                            cost_usd=cost),
        ))
    total = trial.usage(db)
    trajectory = Trajectory(
        agent=Agent(name=name, version=version or "unknown", model_name=model),
        steps=steps,
        final_metrics=FinalMetrics(total_prompt_tokens=total["input_tokens"],
                                   total_completion_tokens=total["output_tokens"],
                                   total_cached_tokens=total["cached_tokens"],
                                   total_cost_usd=total["cost_usd"], total_steps=len(steps)),
    )
    out = agent_dir / "trajectory.json"
    out.write_text(json.dumps(trajectory.to_json_dict(), indent=2))
    return out


def _viewer_shots(trial_dir: Path) -> list[tuple[float, Path]]:
    """(time pmai's command result came back, the page screenshot after it), from the sidecar's events."""
    events = trial_dir / VIEWER / "events.jsonl"
    if not events.exists():
        return []
    shots = [(e["t"], events.parent / e["shot"]) for e in map(json.loads, events.read_text().splitlines())
             if e["event"] == "pmai_result"]
    return [(t, shot) for t, shot in shots if shot.exists()]


def _text(content) -> str:
    return content if isinstance(content, str) else "".join(p.get("text", "") for p in content or [])


def _content(output, images: Path, call_id: str) -> str | list[ContentPart]:
    """A tool output: its text, and each image as a file."""
    if isinstance(output, str) or output is None:
        return output or ""
    parts = []
    for n, part in enumerate(output):
        url = part.get("image_url") or ""
        if part.get("type") == "input_image" and url.startswith("data:"):
            head, data = url.split(",", 1)  # data:image/png;base64,...
            file = f"{call_id}-{n}.{head.split(';')[0].split('/')[1]}"
            (images / file).write_bytes(base64.b64decode(data))
            parts.append(_image(file))
        else:
            parts.append(ContentPart(type="text", text=part.get("text", "")))
    return parts


def _image(file: str) -> ContentPart:
    kind = {"jpg": "jpeg"}.get(ext := file.rsplit(".", 1)[-1], ext)
    return ContentPart(type="image", source=ImageSource(media_type=f"image/{kind}", path=f"images/{file}"))


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        trial_dir = Path(arg)
        info = json.loads((trial_dir / "result.json").read_text())["agent_info"]
        model = (info.get("model_info") or {}).get("name")
        print(write(trial_dir / "agent", info["name"], info.get("version"), model))
