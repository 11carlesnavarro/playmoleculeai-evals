"""Follow a running job: what each trial's agent does, and each new viewer image. Ctrl-C to stop.

    make watch                                    the newest job in results/
    uv run python scripts/watch.py results/<job>  another job
"""

import contextlib
import json
import sys
import time
from pathlib import Path

from pmai_evals.trial import HOST_ARTIFACTS, text


def say(item: dict) -> str | None:
    """One line for a finished output item of pmai's stream (agent/events.jsonl)."""
    kind = item.get("type")
    if kind == "function_call":
        return f"CALL  {item['name']} {item.get('arguments', '')[:160]}"
    if kind == "message":
        return "SAY   " + text(item.get("content")).replace("\n", " ")[:300]
    if kind == "reasoning":
        summary = " ".join(p.get("text", "") for p in item.get("summary") or []).replace("\n", " ")
        return f"THINK {summary[:140]}" if summary else None
    return None


def new_lines(f: Path, offsets: dict) -> list[str]:
    """The complete lines added to f since the last call: a line still being written waits."""
    if not f.exists():
        return []
    with f.open("rb") as fh:
        fh.seek(offsets.get(f, 0))
        data = fh.read()
    done = data.rfind(b"\n") + 1
    offsets[f] = offsets.get(f, 0) + done
    return data[:done].decode(errors="replace").splitlines()


def events(trial: Path, offsets: dict, images: set) -> list[str]:
    out, agent = [], trial / "agent/events.jsonl"
    for raw in new_lines(agent, offsets):
        event = json.loads(raw)
        if event.get("type") == "response.output_item.done" and (line := say(event["item"])):
            out.append(line)
    viewer = trial / HOST_ARTIFACTS / "viewer"
    for raw in new_lines(viewer / "events.jsonl", offsets):
        event = json.loads(raw)
        if event["event"] == "ready":
            out.append(f"VIEW  ready in {event['seconds']} s, images in {viewer}/steps")
        elif event["event"] in ("broken", "bridge_error"):
            out.append(f"VIEW  {event['event']} {event.get('reason') or event.get('error')}")
    for image in sorted(set(viewer.glob("steps/*.jpg")) - images):  # the sidecar saves only a changed view
        images.add(image)
        out.append(f"IMAGE {image.relative_to(viewer)}")
    return out


def end(trial: Path) -> str:
    result = json.loads((trial / "result.json").read_text())
    if result.get("exception_info"):
        return f"END   error: {result['exception_info'].get('exception_type')} (see {trial}/exception.txt)"
    rewards = (result.get("verifier_result") or {}).get("rewards") or {}
    return f"END   reward {rewards['reward']}" if "reward" in rewards else "END   done (no score)"


def main(job: Path) -> None:
    print(f"following {job} (Ctrl-C to stop)")
    offsets, images, ended = {}, set(), set()
    while True:
        for trial in sorted(p for p in job.iterdir() if p.is_dir()):
            for line in events(trial, offsets, images):
                print(f"{trial.name[:28]:28} {line}", flush=True)
            if trial not in ended and (trial / "result.json").exists():
                ended.add(trial)
                print(f"{trial.name[:28]:28} {end(trial)}", flush=True)
        time.sleep(1)


if __name__ == "__main__":
    runs = [p for p in Path("results").glob("*") if p.is_dir() and not p.name.startswith(".")]
    if len(sys.argv) < 2 and not runs:
        sys.exit("No run in results/ yet: make run first.")
    job = Path(sys.argv[1]) if len(sys.argv) > 1 else max(runs, key=lambda p: p.stat().st_mtime)
    with contextlib.suppress(KeyboardInterrupt):
        main(job)
