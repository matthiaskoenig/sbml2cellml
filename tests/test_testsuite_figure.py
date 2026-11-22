"""Tests of the figures of a suite run."""

from pathlib import Path

import numpy as np

from sbml2cellml.testsuite.figure import (
    dark_path,
    render_figure,
    render_timings,
    timing_pairs,
    write_figures,
    write_timing_figures,
)
from sbml2cellml.testsuite.results import STAGES, SuiteResult
from tests.test_testsuite_report import sample, timed_sample


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


def test_render_figure_title_and_cases() -> None:
    ax = render_figure(sample(), title="BioModels", cases="models").axes[0]
    assert ax.get_title(loc="left") == "BioModels: 3 models, pass rate per stage"
    assert ax.get_xlabel() == "models"


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


def test_timing_pairs() -> None:
    # only the cases whose libopencor stage passes, i.e. the same dynamics
    assert timing_pairs(timed_sample()) == {
        "00001": (0.02, 0.01),
        "00007": (0.06, 0.18),
    }
    assert set(timing_pairs(timed_sample(), passing=False)) == {
        "00001",
        "00002",
        "00006",
        "00007",
    }
    # a run without timings has no pairs
    assert timing_pairs(sample()) == {}


def test_render_timings() -> None:
    ax = render_timings(timed_sample()).axes[0]
    assert ax.get_xscale() == "log"
    assert ax.get_yscale() == "log"
    assert ax.get_xlabel() == "sbmlsim-core, SBML model (s)"
    assert ax.get_ylabel() == "libopencor, CellML model (s)"
    assert ax.get_title(loc="left") == "SBML test suite 3.5.0: integration time"
    # the cases and the medians, 40 ms of sbmlsim-core and 95 ms of libopencor
    assert [text.get_text() for text in ax.texts] == ["2 cases, median 40 ms and 95 ms"]
    legend = ax.get_legend()
    assert legend is not None
    assert [text.get_text() for text in legend.get_texts()] == [
        "libopencor faster (1)",
        "sbmlsim-core faster (1)",
    ]


def test_render_timings_title_and_cases() -> None:
    ax = render_timings(timed_sample(), title="BioModels", cases="models").axes[0]
    assert ax.get_title(loc="left") == "BioModels: integration time"
    assert ax.texts[0].get_text().startswith("2 models, median")


def test_render_timings_without_timings() -> None:
    ax = render_timings(sample()).axes[0]
    # no points, so no median either
    assert len(ax.texts) == 0
    assert all(np.size(collection.get_offsets()) == 0 for collection in ax.collections)


def test_write_timing_figures(tmp_path: Path) -> None:
    path = tmp_path / "images" / "testsuite_timings.svg"
    write_timing_figures(timed_sample(), path)
    dark = dark_path(path)
    assert dark == tmp_path / "images" / "testsuite_timings_dark.svg"
    for file in (path, dark):
        text = file.read_text(encoding="utf-8")
        assert text.startswith("<?xml") and text.endswith("</svg>\n")
        assert all(line == line.rstrip() for line in text.splitlines())
    assert path.read_bytes() != dark.read_bytes()
