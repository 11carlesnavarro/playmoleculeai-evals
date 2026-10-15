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
        def test_skipped(): pytest.skip("does not apply")
        @pytest.mark.parametrize("x", ["a b"])
        def test_param(x): partial(0.5)
    """)
    pytester.runpytest_subprocess("-p", "pmai_evals.reward")
    assert json.loads(out.read_text()) == {
        "reward": 0.4,
        "test_ok": 1.0,
        "test_bad": 0.0,
        "test_half": 0.5,
        "test_setup_error": 0.0,
        "test_param[a b]": 0.5,
    }


def test_infra_error_gives_no_reward(pytester, tmp_path, monkeypatch):
    out = tmp_path / "reward.json"
    out.write_text("{}")  # from an old run
    monkeypatch.setenv("REWARD_JSON", str(out))
    pytester.makepyfile("""
        from pmai_evals.reward import InfraError
        def test_ok(): pass
        def test_viewer(): raise InfraError("viewer /open: 503 no WebGL2")
    """)
    result = pytester.runpytest_subprocess("-p", "pmai_evals.reward")
    assert not out.exists()
    result.stdout.fnmatch_lines(["*infra error, no reward:*", "*test_viewer: viewer /open: 503 no WebGL2"])


def test_a_test_file_that_does_not_import_gives_no_reward(pytester, tmp_path, monkeypatch):
    out = tmp_path / "reward.json"
    monkeypatch.setenv("REWARD_JSON", str(out))
    pytester.makepyfile("import not_installed\ndef test_ok(): pass\n")
    result = pytester.runpytest_subprocess("-p", "pmai_evals.reward")
    assert not out.exists()
    result.stdout.fnmatch_lines(["*infra error, no reward:*", "*cannot collect*"])
