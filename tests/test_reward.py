import json


def test_reward(pytester, tmp_path, monkeypatch):
    out = tmp_path / "reward.json"
    monkeypatch.setenv("REWARD_JSON", str(out))
    pytester.makepyfile("""
        import pytest
        from pmai_evals.reward import partial
        @pytest.fixture
        def broken(): raise RuntimeError
        def test_ok(): pass
        def test_bad(): assert False
        def test_half(): partial(0.5)
        def test_setup_error(broken): pass
    """)
    pytester.runpytest_subprocess("-p", "pmai_evals.reward")
    assert json.loads(out.read_text()) == {
        "reward": 0.375,
        "test_ok": 1.0,
        "test_bad": 0.0,
        "test_half": 0.5,
        "test_setup_error": 0.0,
    }
