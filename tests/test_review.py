"""pmai_evals.review: a run for the review page, and the ratings back."""

import json
from datetime import UTC, datetime

import pytest

from pmai_evals import review


def call(name, **args):
    return json.dumps({"type": "response.output_item.done",
                       "item": {"type": "function_call", "name": name, "arguments": json.dumps(args)}})


def test_collect_and_export(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    case = tmp_path / "evals/demo/cases/c1"
    (case / "tests").mkdir(parents=True)
    (case / "task.toml").write_text('[task]\nname = "x/c1"\nkeywords = ["demo", "pocket", "holdout"]\n')
    (case / "instruction.md").write_text("Show the pocket.\n")
    (case / "tests/rubric.txt").write_text("7 The ligand is visible.\n\n3 The pocket is labeled.\n")
    run = tmp_path / "results/demo-train-20261008-120000"
    trial = run / "c1__abc"
    viewer = trial / "artifacts/logs/artifacts/viewer"
    viewer.mkdir(parents=True)
    (trial / "agent/images").mkdir(parents=True)
    (trial / "agent/images/call_1-1.png").write_bytes(b"png")  # an image a tool returned
    (trial / "agent/images/viewer-000.jpg").write_bytes(b"jpg")  # the sidecar's page shot
    (run / "config.json").write_text(json.dumps({"agents": [{"model_name": "m1"}]}))
    (trial / "config.json").write_text(json.dumps({"task": {"path": "evals/demo/cases/c1"}}))
    for name in ("final-view.png", "final.png", "saved-fig.png"):
        (viewer / name).write_bytes(b"png")
    (trial / "agent/events.jsonl").write_text("\n".join([
        call("run_bash", command="cat SKILL.md"),
        call("pmview_python", code="mol.view()"),
        call("pmview_python", code="pmv.zoom()"),
        json.dumps({"type": "response.output_item.done",
                    "item": {"type": "message", "content": [{"type": "output_text", "text": "Done."}]}}),
    ]))

    review.collect(run, tmp_path / "out")
    data = json.loads((tmp_path / "out/runs/demo-train-20261008-120000.json").read_text())
    meta = json.loads((tmp_path / "out/demo-train-20261008-120000.db.json").read_text())
    assert (meta["eval"], meta["job"], meta["model"], meta["finished"]) == ("demo", "train", "m1", 0)
    c = data["cases"][0]
    assert (c["tags"], c["holdout"], c["status"]) == (["pocket"], True, "running")
    assert c["rubric"] == [{"points": 7, "text": "The ligand is visible."},
                           {"points": 3, "text": "The pocket is labeled."}]
    assert [i["file"] for i in c["images"]] == ["final-view.png", "saved-fig.png"]  # final.png: same view
    assert [x["name"] for x in c["calls"]] == ["run_bash", "pmview_python", "pmview_python"]
    assert (c["answer"], c["agent_screenshots"]) == ("Done.", 1)
    assert sorted(p.name for p in (tmp_path / "out/runs/demo-train-20261008-120000/c1").iterdir()) == [
        "final-view.png", "saved-fig.png"]  # the final view and the files of the task only

    docs = tmp_path / "docs/ratings"
    docs.mkdir(parents=True)
    rating = {"run": meta["run"], "eval": "demo", "case": "c1", "rubric": c["rubric"],
              "checks": ["pass", "fail"], "note": "labels missing"}
    (docs / "r1.json").write_text(json.dumps({"id": "r1", "data": rating, "version": 1}))
    review.export(docs)
    saved = tmp_path / "evals/demo/ratings/demo-train-20261008-120000.json"
    assert json.loads(saved.read_text()) == [rating]


def test_score():
    rubric = [{"points": 6, "text": "a"}, {"points": 3, "text": "b"}, {"points": 1, "text": "c"}]
    assert review.score(rubric, ["pass", "fail", "pass"]) == 7
    assert review.score(rubric, ["fail", "pass", "pass"]) == 4
    assert review.score(rubric, ["pass", None, "pass"]) is None
    assert review.score([{"points": 1, "text": "a"}, {"points": 2, "text": "b"}], ["pass", "fail"]) == 3.3


def test_combine(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    results = tmp_path / "results"
    for date in ("20261008-120000", "20261009-130000", "20261009-140000"):
        run = results / f"demo-train-{date}"
        trial = run / f"c1__{date[-6:-4]}"
        trial.mkdir(parents=True)
        (trial / "config.json").write_text(json.dumps({"task": {"path": "evals/demo/cases/c1"}}))
        (trial / "result.json").write_text(json.dumps({
            "agent_info": {"name": "pmai", "model_info": {"name": "m1"}}, "source": "cases",
            "config": {"agent": {"name": "pmai"}, "task": {"source": "cases"}},
            "agent_result": {"cost_usd": 0.25},
            "verifier_result": {"rewards": {"reward": 1.0}}}))
        going = date.endswith("140000")  # the last run is still going: Harbor's updated_at has a zone
        finished = None if going else "2026-10-08T13:00:00"
        updated = datetime(2026, 10, 8, 12, 30).astimezone().astimezone(UTC) if going else None
        stats = {"n_trials": 1, "metrics": [{"reward": 1.0}]}
        (run / "result.json").write_text(json.dumps({
            "started_at": "2026-10-08T12:00:00", "updated_at": updated and updated.isoformat(),
            "finished_at": finished,
            "n_total_trials": 1, "stats": {"n_completed_trials": 1, "cost_usd": 0.5,
                                           "evals": {"pmai__m1__cases": stats}}}))
        (run / "config.json").write_text(json.dumps({"job_name": run.name, "agents": [{"name": "pmai"}],
                                                     "datasets": [{"path": "evals/demo/cases"}]}))
    (results / "smoke-hello-20261008-090000").mkdir()  # no result.json yet: not shown
    ratings = tmp_path / "evals/demo/ratings/demo-train-20261008-120000.json"
    ratings.parent.mkdir(parents=True)
    rubric = [{"points": 6, "text": "a"}, {"points": 4, "text": "b"}]
    ratings.write_text(json.dumps([{"trial": "c1__12", "rubric": rubric, "checks": ["pass", "fail"]}]))
    review.combine(results, results / ".view")
    view = results / ".view/demo-train"
    assert [p.name for p in (results / ".view").iterdir()] == ["demo-train"]
    job = json.loads((view / "result.json").read_text())
    assert list(job["stats"]["evals"]) == [
        "pmai 10-08 12:00__m1__demo", "pmai 10-09 13:00__m1__demo", "pmai 10-09 14:00__m1__demo"]
    stats = job["stats"]
    first, second = (e["metrics"][0] for e in list(stats["evals"].values())[:2])
    assert first == {"human_reward": 0.6, "cost_usd": 0.25, "minutes": 60, "reward": 1.0}
    assert second == {"cost_usd": 0.25, "minutes": 60, "reward": 1.0}  # not reviewed
    assert (job["n_total_trials"], stats["n_completed_trials"], stats["cost_usd"]) == (3, 3, 1.5)
    times = job["started_at"], job["finished_at"]
    assert times == ("2026-10-08T12:00:00", "2026-10-08T14:30:00")  # Duration 1 + 1 + 0.5 h
    config = json.loads((view / "config.json").read_text())
    assert config["datasets"] == [{"path": "evals/demo"}]
    assert [a["name"] for a in config["agents"]] == [
        "pmai 10-08 12:00", "pmai 10-09 13:00", "pmai 10-09 14:00"]
    result = json.loads((view / "c1__12/result.json").read_text())
    assert result["agent_info"]["name"] == result["config"]["agent"]["name"] == "pmai 10-08 12:00"
    assert result["source"] == result["config"]["task"]["source"] == "demo"
    assert result["verifier_result"]["rewards"] == {"reward": 1.0, "human_reward": 0.6}
    assert (view / "c1__12/config.json").samefile(results / "demo-train-20261008-120000/c1__12/config.json")
    run_result = json.loads((results / "demo-train-20261008-120000/c1__12/result.json").read_text())
    assert run_result["agent_info"]["name"] == "pmai" and "human_reward" not in str(run_result)  # unchanged

    # the job file turns the verifier off: no verifier rewards, also in the runs made before
    (tmp_path / "evals/demo/train.yaml").write_text("verifier:\n  disable: true\n")
    review.combine(results, results / ".view")
    evals = json.loads((view / "result.json").read_text())["stats"]["evals"]
    first, second = (e["metrics"][0] for e in list(evals.values())[:2])
    assert first == {"human_reward": 0.6, "cost_usd": 0.25, "minutes": 60}
    assert second == {"cost_usd": 0.25, "minutes": 60}
    verifier = [json.loads((view / f"c1__{t}/result.json").read_text())["verifier_result"] for t in (12, 13)]
    assert verifier == [{"rewards": {"human_reward": 0.6}}, None]


def test_save_rating(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    doc = {"run": "demo-train-20261008-120000", "eval": "demo", "case": "c2", "checks": ["pass"]}
    review._save_rating(doc)
    review._save_rating(doc | {"case": "c1"})
    review._save_rating(doc | {"checks": ["fail"]})  # the same case again: replaced
    saved = json.loads((tmp_path / "evals/demo/ratings/demo-train-20261008-120000.json").read_text())
    assert [(d["case"], d["checks"]) for d in saved] == [("c1", ["pass"]), ("c2", ["fail"])]
    with pytest.raises(ValueError):
        review._save_rating(doc | {"run": "../../x"})
