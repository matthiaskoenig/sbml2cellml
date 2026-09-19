"""Tests of the bar diagram of a suite run."""

from pathlib import Path

from sbml2cellml.testsuite.figure import dark_path, render_figure, write_figures
from sbml2cellml.testsuite.results import STAGES, SuiteResult
from tests.test_testsuite_report import sample


def test_render_figure() -> None:
    fig = render_figure(sample())
    ax = fig.axes[0]
    # the stages from top to bottom in the order of the pipeline
    assert [label.get_text() for label in ax.get_yticklabels()] == list(STAGES)
    assert ax.yaxis_inverted()
    # one bar per stage and status with cases: 5 pass, 2 fail, no skip
    assert len(ax.patches) == 7
    legend = ax.get_legend()
    assert legend is not None
    assert [text.get_text() for text in legend.get_texts()] == ["pass", "fail", "skip"]
    texts = {text.get_text() for text in ax.texts}
    # pass rates at the end of the bars
    assert {"100.0%", "33.3%"} <= texts
    assert "3.5.0" in ax.get_title(loc="left")


def test_render_figure_without_cases() -> None:
    fig = render_figure(SuiteResult("3.5.0", "0.1.0"))
    assert len(fig.axes[0].patches) == 0


def test_write_figures(tmp_path: Path) -> None:
    path = tmp_path / "images" / "testsuite.svg"
    write_figures(sample(), path)
    dark = dark_path(path)
    assert dark == tmp_path / "images" / "testsuite_dark.svg"
    for file in (path, dark):
        text = file.read_text(encoding="utf-8")
        assert text.startswith("<?xml") and text.endswith("</svg>\n")
        # nothing for the whitespace hooks of pre-commit to change
        assert all(line == line.rstrip() for line in text.splitlines())
    assert path.read_text(encoding="utf-8") != dark.read_text(encoding="utf-8")


def test_write_figures_is_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "a.svg"
    second = tmp_path / "b.svg"
    write_figures(sample(), first)
    write_figures(sample(), second)
    assert first.read_bytes() == second.read_bytes()
