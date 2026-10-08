from pmai_evals import trial


def test_file():
    assert (trial.WORK / "hello.txt").read_text().strip() == "hello from pmai"


def test_answer():
    assert trial.tag() == "done"


def test_no_tool_errors():
    assert not trial.tool_errors()
