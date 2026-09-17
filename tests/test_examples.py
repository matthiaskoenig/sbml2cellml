"""The examples run without error.

They write into `examples/results/` (gitignored) and simulate with libopencor,
so they are skipped without it.
"""

import runpy
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import pytest

pytest.importorskip("libopencor")
matplotlib.use("Agg")

EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


@pytest.mark.parametrize(
    ("script", "result"),
    [
        ("cellml_example.py", "test_model.cellml"),
        ("glimepiride_example.py", "glimepiride_body.cellml"),
        ("cellml2sbml_example.py", "cell_growth.xml"),
    ],
)
def test_example_runs(
    script: str, result: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MPLBACKEND", "Agg")
    monkeypatch.setattr(plt, "show", lambda *args, **kwargs: None)
    monkeypatch.chdir(tmp_path)
    runpy.run_path(str(EXAMPLES_DIR / script), run_name="__main__")
    assert (EXAMPLES_DIR / "results" / result).is_file()
