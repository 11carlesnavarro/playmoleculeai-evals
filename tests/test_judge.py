import json
from types import SimpleNamespace

import pytest

from pmai_evals import judge as j
from pmai_evals.reward import InfraError


def fake_client(monkeypatch, verdicts=None, refusal=False, error=None):
    sent = []

    def create(**kw):
        sent.append(kw)
        if error:
            raise error
        part = SimpleNamespace(type="refusal" if refusal else "output_text")
        out = json.dumps({"verdicts": verdicts or []})
        return SimpleNamespace(output=[SimpleNamespace(type="message", content=[part])], output_text=out)

    monkeypatch.setattr(j.openai, "OpenAI", lambda: SimpleNamespace(responses=SimpleNamespace(create=create)))
    return sent


def test_grade(tmp_path, monkeypatch):
    monkeypatch.setattr(j, "LOG", tmp_path / "judge.md")
    (tmp_path / "a.PNG").write_bytes(b"png")
    (tmp_path / "b.txt").write_text("body")
    (tmp_path / "c.pdf").write_bytes(b"%PDF")
    v = [{"reason": "looks right", "pass": True}, {"reason": "no labels", "pass": False}]
    sent = fake_client(monkeypatch, v)
    assert (
        j.grade(["is it right?", "labels?"], files=[tmp_path / f for f in ("a.PNG", "b.txt", "c.pdf")],
                text="answer")
        == v
    )
    kinds = [c["type"] for c in sent[0]["input"][0]["content"]]
    assert kinds == ["input_text", "input_image", "input_text", "input_file", "input_text"]
    assert "1. is it right?\n2. labels?" in sent[0]["input"][0]["content"][-1]["text"]
    assert sent[0]["text"]["format"]["schema"]["properties"]["verdicts"]["minItems"] == 2
    assert "no labels\n\nFAIL" in (tmp_path / "judge.md").read_text()

    fake_client(monkeypatch, [{"reason": "", "pass": False}])
    assert not j.judge("x")


def test_a_judge_that_cannot_answer_is_an_infra_error(tmp_path, monkeypatch):
    """No reward, not a 0: the agent did not fail."""
    monkeypatch.setattr(j, "LOG", tmp_path / "judge.md")
    fake_client(monkeypatch, [])
    with pytest.raises(InfraError, match="0 verdicts for 1"):
        j.judge("x")
    fake_client(monkeypatch, refusal=True)
    with pytest.raises(InfraError, match="refused"):
        j.judge("x")
    fake_client(monkeypatch, error=j.openai.OpenAIError("rate limit"))
    with pytest.raises(InfraError, match="judge: rate limit"):
        j.judge("x")
