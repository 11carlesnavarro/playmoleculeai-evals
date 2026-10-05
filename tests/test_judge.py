from types import SimpleNamespace

from pmai_evals import judge as j


class FakeStream:
    def __init__(self, text, stop_reason, sent, **kwargs):
        sent.append(kwargs)
        block = SimpleNamespace(type="text", text=text)
        self.msg = SimpleNamespace(content=[block], stop_reason=stop_reason)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get_final_message(self):
        return self.msg


def fake_client(monkeypatch, text, stop_reason="end_turn"):
    sent = []
    messages = SimpleNamespace(stream=lambda **kw: FakeStream(text, stop_reason, sent, **kw))
    monkeypatch.setattr(j.anthropic, "Anthropic", lambda: SimpleNamespace(messages=messages))
    return sent


def test_judge(tmp_path, monkeypatch):
    monkeypatch.setattr(j, "LOG", tmp_path / "judge.md")
    (tmp_path / "a.png").write_bytes(b"png")
    (tmp_path / "b.txt").write_text("body")
    sent = fake_client(monkeypatch, "looks right\nPASS")
    assert j.judge("is it right?", files=[tmp_path / "a.png", tmp_path / "b.txt"], text="answer")
    kinds = [c["type"] for c in sent[0]["messages"][0]["content"]]
    assert kinds == ["text", "image", "text", "text"]
    assert "is it right?" in (tmp_path / "judge.md").read_text()

    fake_client(monkeypatch, "PASS is not the verdict\nFAIL")
    assert not j.judge("x")
    fake_client(monkeypatch, "")
    assert not j.judge("x")


def test_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(j, "LOG", tmp_path / "judge.md")
    fake_client(monkeypatch, "", stop_reason="refusal")
    try:
        j.judge("x")
    except RuntimeError:
        return
    raise AssertionError("a refusal must not pass or fail silently")
