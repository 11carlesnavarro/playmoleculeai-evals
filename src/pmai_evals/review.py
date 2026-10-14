"""Human review of any eval: a Harbor run for the review page (review.html), and the ratings back.

    uv run python -m pmai_evals.review collect results/<run> <out dir>
    uv run python -m pmai_evals.review export <dir of rating docs>
    uv run python -m pmai_evals.review serve results 8080               # make review
    uv run python -m pmai_evals.review combine results results/.view   # make view

collect writes <out>/runs/<run>.json, the images it shows in <out>/runs/<run>/<case>/, and <out>/<run>.db.json
(the run's entry in the page's `runs` collection). Claude publishes review.html with the files of <out> and
writes the entry. A case shows its prompt, the agent's last message, each image in the trial's
artifacts (final-view.png first), the tool calls, cost, time and test scores.
The reviewer marks each line of tests/rubric.txt yes or no, like an exam: a line is "<points> <criterion>",
the points add up to 10, and the score is the points of the yes lines (0 to 10). A case with no rubric gets
one line worth 10 points.

serve is the same page on this machine: each click is saved in evals/<eval>/ratings/<run>.json.
On claude.ai, export reads the page's `ratings` docs (ArtifactData list with out_dir) into that file.

combine builds the jobs that make view shows: one Harbor job for each job file, <view>/<eval>-<job file>/,
with all its runs (results/<eval>-<job file>-<date>/) and the run's date in the agent name, so each run is
one row and one Pareto point. The reviews in evals/<eval>/ratings/<run>.json are the reward human_reward
(score / 10) of each reviewed trial, and their mean is a metric of the run, with its cost_usd and minutes.
When the job file turns the verifier off (the eval has no score yet), the view shows no verifier rewards
for any of its runs: the old ones came from tests that the eval no longer has.
Its files are hard links to the runs' files (no space) except result.json and config.json; make view
builds it again each time.
"""

import http.server
import json
import os
import re
import shutil
import sys
import threading
import tomllib
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import yaml

IMAGES = {".png", ".jpg", ".jpeg", ".webp"}
NO_RUBRIC = [{"points": 10, "text": "The result does what the prompt asks."}]
KEY = "human_reward"  # the review score in harbor view
RUN = re.compile(r"(.+)-(\d{8})-(\d{6})")  # results/<eval>-<job file>-<date>, see NAME in the Makefile


def _local(stamp: str) -> datetime:
    """A Harbor time as local time. Harbor writes local times with no zone, but while a job runs its
    updated_at comes from the trial events, in UTC with an offset."""
    t = datetime.fromisoformat(stamp)
    return t.astimezone().replace(tzinfo=None) if t.tzinfo else t


def _seconds(span: dict | None) -> float | None:
    if not (span and span.get("started_at") and span.get("finished_at")):
        return None
    return round((datetime.fromisoformat(span["finished_at"]) - datetime.fromisoformat(span["started_at"]))
                 .total_seconds(), 1)


def _short(arguments: str) -> str:
    """The first text argument of a tool call, on one line."""
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return arguments[:140]
    text = next((v for v in args.values() if isinstance(v, str)), "")
    return " ".join(text.split())[:140]


def _trace(events: Path) -> tuple[list[dict], str]:
    """Tool calls in order, and the agent's last message."""
    calls, answer = [], ""
    for line in events.read_text().splitlines() if events.exists() else []:
        event = json.loads(line)
        if event.get("type") != "response.output_item.done":
            continue
        item = event["item"]
        if item["type"] == "function_call":
            calls.append({"name": item["name"], "args": _short(item.get("arguments"))})
        elif item["type"] == "message":
            answer = "".join(p.get("text", "") for p in item.get("content") or [])
    return calls, answer


def _rubric(path: Path) -> list[dict]:
    """tests/rubric.txt: one "<points> <criterion>" a line."""
    if not path.exists():
        return NO_RUBRIC
    lines = (line.split(None, 1) for line in path.read_text().splitlines() if line.strip())
    return [{"points": int(points), "text": text.strip()} for points, text in lines]


def score(rubric: list[dict], checks: list) -> float | None:
    """The points of the yes lines, out of 10; None until each line is marked."""
    if len(checks) != len(rubric) or None in checks:
        return None
    got = sum(r["points"] for r, check in zip(rubric, checks, strict=True) if check == "pass")
    return round(10 * got / sum(r["points"] for r in rubric), 1)


def _images(trial: Path, out: Path) -> list[dict]:
    """Each image in the trial's artifacts, except the viewer steps: the final view first."""
    found = [p for p in sorted((trial / "artifacts").rglob("*")) if p.suffix.lower() in IMAGES
             and "steps" not in p.relative_to(trial).parts[:-1]]
    if any(p.name == "final-view.png" for p in found):
        found = [p for p in found if p.name != "final.png"]  # the sidecar's page shot: same view + chat
    found.sort(key=lambda p: p.name != "final-view.png")
    images, names = [], set()
    for p in found:
        name = p.name if p.name not in names else f"{len(names)}-{p.name}"
        names.add(name)
        out.mkdir(parents=True, exist_ok=True)
        shutil.copy(p, out / name)
        label = {"final-view.png": "Final view", "final.png": "Page at the end"}.get(p.name)
        images.append({"file": name, "label": label or p.name.removeprefix("saved-")})
    return images


def case(trial: Path, out: Path, eval_name: str, scored: bool) -> dict | None:
    """A trial for the page. None when its case was removed since the run: no prompt, no rubric."""
    task_dir = Path(json.loads((trial / "config.json").read_text())["task"]["path"])
    if not task_dir.is_dir():
        return None
    keywords = tomllib.loads((task_dir / "task.toml").read_text())["task"].get("keywords", [])
    result = json.loads((trial / "result.json").read_text()) if (trial / "result.json").exists() else None
    calls, answer = _trace(trial / "agent/events.jsonl")
    rewards = ((result or {}).get("verifier_result") or {}).get("rewards") or {} if scored else {}
    error = (result or {}).get("exception_info")
    return {
        "case": task_dir.name,
        "trial": trial.name,
        "tags": [k for k in keywords if k not in (eval_name, "holdout")],
        "holdout": "holdout" in keywords,
        "prompt": (task_dir / "instruction.md").read_text().strip(),
        "rubric": _rubric(task_dir / "tests/rubric.txt"),
        "status": "running" if result is None else "error" if error else "done",
        "error": error and error.get("exception_type"),
        "images": _images(trial, out / task_dir.name),
        "calls": calls,
        "answer": answer,
        "cost_usd": ((result or {}).get("agent_result") or {}).get("cost_usd"),
        "agent_seconds": _seconds((result or {}).get("agent_execution")),
        "agent_screenshots": len(list((trial / "agent/images").glob("call_*"))),  # the images tools returned
        "reward": rewards.get("reward"),
        "tests": {k: v for k, v in rewards.items() if k != "reward"},
    }


def _trials(run_dir: Path) -> tuple[list[Path], str]:
    """The trial dirs of a run, and the eval they come from."""
    trials = sorted(t for t in run_dir.iterdir() if (t / "config.json").exists())
    task_path = json.loads((trials[0] / "config.json").read_text())["task"]["path"]
    return trials, m.group(1) if (m := re.search(r"evals/([^/]+)/cases/", task_path)) else "other"


def _meta(run_dir: Path, trials: list[Path], eval_name: str) -> dict:
    """The run's entry in the run list of the page."""
    run = run_dir.name
    config = json.loads((run_dir / "config.json").read_text())
    m = RUN.fullmatch(run)
    return {"run": run, "eval": eval_name, "job": m[1].removeprefix(f"{eval_name}-") if m else run,
            "model": config["agents"][0].get("model_name"),
            "started": datetime.strptime(m[2] + m[3], "%Y%m%d%H%M%S").isoformat() if m else None,
            "cases": len(trials), "finished": sum((t / "result.json").exists() for t in trials)}


def collect(run_dir: Path, out: Path) -> None:
    run = run_dir.name
    trials, eval_name = _trials(run_dir)
    meta = _meta(run_dir, trials, eval_name)
    scored = _scored(eval_name, meta["job"])
    cases = [c for t in trials if (c := case(t, out / "runs" / run, eval_name, scored))]
    (out / "runs").mkdir(parents=True, exist_ok=True)
    (out / "runs" / f"{run}.json").write_text(json.dumps({**meta, "cases": cases}))
    (out / f"{run}.db.json").write_text(json.dumps(meta))
    print(f"{run}: {meta['finished']}/{meta['cases']} finished, {len(cases)} on the page -> {out}")
    # ponytail: an artifact version holds at most 511 files (about 16 a run); remove old runs (ratings stay)


def export(docs_dir: Path) -> None:
    docs = [json.loads(p.read_text()) for p in sorted(docs_dir.rglob("*.json"))]
    docs = [d.get("data", d) if "run" not in d else d for d in docs]
    for (eval_name, run) in sorted({(d["eval"], d["run"]) for d in docs}):
        mine = sorted((d for d in docs if d["run"] == run), key=lambda d: d["case"])
        path = _ratings(eval_name, run)
        _write(path, mine)
        scores = [s for d in mine if (s := score(d["rubric"], d["checks"])) is not None]
        mean = sum(scores) / max(len(scores), 1)
        print(f"\n{path}: {len(scores)} reviewed, mean score {mean:.1f} / 10")
        for d in mine:
            failed = [r["text"] for r, c in zip(d["rubric"], d["checks"], strict=False) if c == "fail"]
            s = score(d["rubric"], d["checks"])
            print(f"  {d['case']:28} {'-' if s is None else s:>4}  {'; '.join(failed)[:90]}")


def _ratings(eval_name: str, run: str) -> Path:
    return Path("evals") / eval_name / "ratings" / f"{run}.json"


def _write(path: Path, docs: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(docs, indent=1, ensure_ascii=False) + "\n")


def _eval_key(result: dict) -> str:
    """Harbor's key of a trial's agent, model and dataset (JobStats.format_agent_evals_key)."""
    agent = result["agent_info"]
    model = (agent.get("model_info") or {}).get("name")
    return "__".join(x for x in (agent["name"], model, result.get("source") or "adhoc") if x)


def _scored(eval_name: str, job: str) -> bool:
    """False when the job file evals/<eval>/<job>.yaml turns the verifier off: the eval has no score yet."""
    path = Path("evals") / eval_name / f"{job}.yaml"
    return not (path.exists() and (yaml.safe_load(path.read_text()).get("verifier") or {}).get("disable"))


def _link(src: str, dst: str) -> None:
    try:
        os.link(src, dst)
    except OSError:  # a file of another user (the container's nobody): copy it
        shutil.copy2(src, dst)


def _view_trial(trial: Path, out: Path, date: str, eval_name: str, scored: bool,
                rating: float | None) -> tuple[str, float] | None:
    """The trial in the view: its files linked, its result.json written again with the run's date in the
    agent name and the review score as a reward. Its eval key and cost; None while it runs."""
    shutil.copytree(trial, out / trial.name, copy_function=_link)
    path = out / trial.name / "result.json"
    if not path.exists():
        return None
    result = json.loads(path.read_text())
    path.unlink()  # a link to the run's file: write a new one
    key = _eval_key(result)
    rewards = (result.get("verifier_result") or {}).get("rewards") if scored else None
    if rating is not None:
        rewards = (rewards or {}) | {KEY: rating}
    result["verifier_result"] = None if rewards is None else {"rewards": rewards}
    result["agent_info"]["name"] += f" {date}"
    result["config"]["agent"]["name"] = result["agent_info"]["name"]  # the viewer reads it
    # Harbor names a local dataset after its folder, "cases" in each eval: use the eval's name
    result["source"] = result["config"]["task"]["source"] = eval_name
    path.write_text(json.dumps(result, indent=4, ensure_ascii=False))
    return key, (result.get("agent_result") or {}).get("cost_usd") or 0


def combine(results: Path, view: Path) -> None:
    groups = defaultdict(list)
    for run in sorted(results.iterdir()):
        if (m := RUN.fullmatch(run.name)) and (run / "result.json").exists():
            groups[m.group(1)].append(run)
    shutil.rmtree(view, ignore_errors=True)
    for group, runs in groups.items():
        out = view / group
        out.mkdir(parents=True)
        evals, totals, starts, seconds, agents = {}, defaultdict(float), [], 0.0, []
        for run in runs:
            _, day, hour = RUN.fullmatch(run.name).groups()
            date = f"{day[4:6]}-{day[6:]} {hour[:2]}:{hour[2:4]}"
            job = json.loads((run / "result.json").read_text())
            trials, eval_name = _trials(run)
            scored = _scored(eval_name, group.removeprefix(f"{eval_name}-"))
            ratings = _ratings(eval_name, run.name)
            human = {d["trial"]: s / 10 for d in (json.loads(ratings.read_text()) if ratings.exists() else [])
                     if (s := score(d["rubric"], d["checks"])) is not None}
            scores, costs = defaultdict(list), defaultdict(float)
            for trial in trials:
                rating = human.get(trial.name)
                if seen := _view_trial(trial, out, date, eval_name, scored, rating):
                    key, cost = seen
                    costs[key] += cost
                    if rating is not None:
                        scores[key].append(rating)
            starts.append(_local(job["started_at"]))
            end = _local(job.get("finished_at") or job["updated_at"])
            run_seconds = (end - starts[-1]).total_seconds()
            seconds += run_seconds
            for key, stats in job["stats"]["evals"].items():
                parts = key.split("__")
                # the review score (mean of the reviewed trials), cost and time as columns of Overview
                mine = {KEY: round(sum(scores[key]) / len(scores[key]), 3)} if scores[key] else {}
                mine |= {"cost_usd": round(costs[key], 3), "minutes": round(run_seconds / 60)}
                metrics = (stats.get("metrics") if scored else None) or [{}]
                metrics[0] = mine | metrics[0]
                key = "__".join([f"{parts[0]} {date}", *parts[1:-1], eval_name])
                evals[key] = stats | {"metrics": metrics}
            for name, value in [("n_total_trials", job["n_total_trials"]), *job["stats"].items()]:
                if type(value) in (int, float):
                    totals[name] += value
            agents += [a | {"name": f"{a['name']} {date}"}
                       for a in json.loads((run / "config.json").read_text())["agents"]]
        n_total = int(totals.pop("n_total_trials"))
        stats = {k: int(v) if k.startswith("n_") else v for k, v in totals.items()} | {"evals": evals}
        start = min(starts)
        end = (start + timedelta(seconds=seconds)).isoformat()  # Duration = the time of all runs
        result = {"id": str(uuid.uuid4()), "started_at": start.isoformat(), "updated_at": end,
                  "finished_at": end, "n_total_trials": n_total, "stats": stats}
        (out / "result.json").write_text(json.dumps(result, indent=4, ensure_ascii=False))
        config = json.loads((runs[-1] / "config.json").read_text()) | {"job_name": group, "agents": agents}
        for dataset in config.get("datasets") or []:
            if dataset.get("path"):
                dataset["path"] = f"evals/{eval_name}"  # the label in the jobs list
        (out / "config.json").write_text(json.dumps(config, indent=4, ensure_ascii=False))
    print(f"{view}: {len(groups)} jobs, one for each job file, one agent for each run")


def _save_rating(doc: dict) -> None:
    """One review from the page into evals/<eval>/ratings/<run>.json, the file export writes."""
    if not (RUN.fullmatch(doc["run"]) and re.fullmatch(r"[\w-]+", doc["eval"])):
        raise ValueError(f"not a run: {doc['eval']}/{doc['run']}")
    path = _ratings(doc["eval"], doc["run"])
    docs = json.loads(path.read_text()) if path.exists() else []
    _write(path, sorted([d for d in docs if d["case"] != doc["case"]] + [doc], key=lambda d: d["case"]))


def serve(results: Path, port: int) -> None:
    """The review page on this machine (make review): the same page, its `runs` and `ratings` from here."""
    cache = results / ".review"
    page = "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
    page += Path(__file__).with_name("review.html").read_text()
    lock = threading.Lock()

    def runs() -> dict[str, Path]:
        return {r.name: r for r in sorted(results.iterdir())
                if RUN.fullmatch(r.name) and any((t / "config.json").exists() for t in r.iterdir())}

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(cache), **kwargs)

        def _send(self, body: str, kind: str = "application/json") -> None:
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            path = self.path.split("?")[0]
            if path == "/":
                return self._send(page, "text/html; charset=utf-8")
            if path == "/api/runs":
                metas = [{"id": n, "data": _meta(r, *_trials(r))} for n, r in runs().items()]
                return self._send(json.dumps(metas))
            if path == "/api/ratings":
                files = sorted(Path("evals").glob("*/ratings/*.json"))
                docs = [d for f in files for d in json.loads(f.read_text())]
                return self._send(json.dumps([{"id": f"{d['run']}__{d['case']}", "data": d} for d in docs]))
            if (m := re.fullmatch(r"/runs/([^/]+)\.json", path)) and (run := runs().get(m[1])):
                collect(run, cache)  # again at each open: a running run grows
            super().do_GET()

        def do_PUT(self) -> None:
            doc = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            try:
                with lock:
                    _save_rating(doc)
            except (KeyError, ValueError, OSError) as error:
                self.send_error(400, str(error))
                return
            self._send("{}")

        def log_message(self, *args) -> None:
            pass

    cache.mkdir(exist_ok=True)
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        sys.exit(f"Port {port} is busy (make view?). Stop it, or use another one: make review PORT=<port>.")
    print(f"Review page: http://localhost:{port}  (reviews go to evals/<eval>/ratings/; Ctrl-C to stop)")
    with server:
        server.serve_forever()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    command, path = sys.argv[1], Path(sys.argv[2])
    if command == "collect":
        collect(path, Path(sys.argv[3]))
    elif command == "export":
        export(path)
    elif command == "combine":
        combine(path, Path(sys.argv[3]))
    else:
        serve(path, int(sys.argv[3]))
