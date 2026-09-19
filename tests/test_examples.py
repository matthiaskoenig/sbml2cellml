"""The examples run without error.

They write into `examples/results/` (gitignored) and simulate with libopencor,
so they are skipped without it.
"""

import importlib.util
import runpy
import sys
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


@pytest.mark.skipif(
    # not imported: roadrunner and libopencor crash in one process
    importlib.util.find_spec("roadrunner") is None,
    reason="the roundtrip example simulates with roadrunner",
)
def test_roundtrip_example_matches_the_documentation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`docs/roundtrip.md` shows the models the example writes.

    Update them with `python examples/repressilator_example.py --docs`.
    """
    monkeypatch.setenv("MPLBACKEND", "Agg")
    monkeypatch.chdir(tmp_path)
    # the example parses its command line, which is the one of pytest here
    monkeypatch.setattr(sys, "argv", ["repressilator_example.py"])
    runpy.run_path(str(EXAMPLES_DIR / "repressilator_example.py"), run_name="__main__")
    results = EXAMPLES_DIR / "results"
    for name in ("repressilator.svg", "repressilator_dark.svg"):
        assert (results / name).is_file()
    documented = EXAMPLES_DIR.parent / "docs" / "roundtrip"
    for name in ("repressilator.cellml", "repressilator_roundtrip.xml"):
        assert (results / name).read_text() == (documented / name).read_text()
