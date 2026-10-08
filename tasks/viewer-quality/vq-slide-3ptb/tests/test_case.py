"""Viewer quality: the result is the final view. You rate it by hand against rubric.txt (line 1 is the
gate: if it fails, the view fails). The reward says only that the view was saved."""

from pmai_evals import trial


def test_final_view_saved():
    trial.final_image()


def test_slide_saved():  # the user asked for this file: keep it for the rating too
    png = trial.WORK / "figures/benzamidine.png"
    assert png.exists()
    (trial.final_image().parent / "saved-benzamidine.png").write_bytes(png.read_bytes())
