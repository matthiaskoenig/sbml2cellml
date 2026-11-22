"""Figures of a suite run, `docs/images/testsuite*.svg`.

`write_figures` renders the bar diagram: one horizontal bar per stage of the
pipeline, stacked from the cases which pass, fail and skip the stage, so the
drop along the pipeline is visible at a glance. `write_timing_figures`
renders the timings of the two simulators: the wall time of the libopencor
simulation of the CellML model against the wall time of the sbmlsim-core
simulation of the SBML model, one point per case. Every figure is written
twice, for light and for dark backgrounds; all of them are transparent, so
they fit the documentation site as well as the README on GitHub and PyPI.
"""

import io
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePath
from statistics import median

import matplotlib as mpl
from matplotlib.figure import Figure
from matplotlib.patches import Patch

from sbml2cellml.testsuite.results import STAGES, STATUSES, SuiteResult

#: gap between two segments of a bar, as fraction of the cases
_GAP = 0.003
#: a segment narrower than this fraction of the cases gets no label
_LABEL_FRACTION = 0.04


@dataclass(frozen=True)
class _Theme:
    """Colors of the figure for one background."""

    #: fill of the pass, fail and skip segments
    fills: tuple[str, str, str]
    #: ink of the labels inside the pass, fail and skip segments
    inks: tuple[str, str, str]
    #: title, tick labels and pass rates
    text: str
    #: axis label and legend
    text_secondary: str
    #: grid lines and the axis
    grid: str


# blue and orange stay apart for every color vision deficiency, the skipped
# cases recede in a neutral gray
_LIGHT = _Theme(
    fills=("#2a78d6", "#eb6834", "#a3a29b"),
    inks=("#ffffff", "#0b0b0b", "#0b0b0b"),
    text="#0b0b0b",
    text_secondary="#52514e",
    grid="#d9d8d3",
)
_DARK = _Theme(
    fills=("#3987e5", "#d95926", "#6b6a65"),
    inks=("#ffffff", "#ffffff", "#ffffff"),
    text="#ffffff",
    text_secondary="#c3c2b7",
    grid="#4a4a47",
)


def dark_path[P: PurePath](path: P) -> P:
    """Path of the figure for dark backgrounds.

    Args:
        path: path of the figure for light backgrounds.

    Returns:
        The path with `_dark` added to the file name, `testsuite_dark.svg`
        for `testsuite.svg`.
    """
    return path.with_name(f"{path.stem}_dark{path.suffix}")


def render_figure(
    result: SuiteResult,
    title: str | None = None,
    dark: bool = False,
    cases: str = "cases",
) -> Figure:
    """Render the bar diagram.

    Args:
        result: a suite run.
        title: start of the title, followed by the number of cases; the
            SBML test suite with its version when `None`.
        dark: whether the figure is for a dark background.
        cases: what a case is, in the title and on the axis, e.g. `models`.

    Returns:
        The figure with a transparent background.
    """
    theme = _DARK if dark else _LIGHT
    if title is None:
        title = f"SBML test suite {result.suite}"
    total = len(result.cases)
    fig = Figure(figsize=(8.0, 3.6), layout="constrained")
    fig.patch.set_alpha(0.0)
    ax = fig.add_subplot()
    ax.patch.set_alpha(0.0)

    gap = _GAP * total
    for row, stage in enumerate(STAGES):
        counts = result.counts(stage)
        left = 0.0
        for status, fill, ink in zip(STATUSES, theme.fills, theme.inks, strict=True):
            count = counts[status]
            if not count:
                continue
            ax.barh(
                row,
                max(count - gap, gap),
                left=left + gap / 2,
                height=0.6,
                color=fill,
                linewidth=0,
            )
            if count >= _LABEL_FRACTION * total:
                ax.text(
                    left + count / 2,
                    row,
                    str(count),
                    ha="center",
                    va="center",
                    color=ink,
                    fontsize=10,
                )
            left += count
        if total:
            ax.text(
                total * 1.012,
                row,
                f"{100 * counts['pass'] / total:.1f}%",
                ha="left",
                va="center",
                color=theme.text,
                fontsize=11,
                fontweight="bold",
            )

    ax.set_yticks(range(len(STAGES)), labels=list(STAGES), fontsize=11)
    ax.invert_yaxis()
    # room for the pass rates right of the bars, the axis ends with the cases
    ax.set_xlim(0, (total or 1) * 1.09)
    ax.set_xticks([tick for tick in ax.get_xticks() if tick <= total])
    ax.spines["bottom"].set_bounds(0, total)
    ax.set_xlabel(cases, color=theme.text_secondary, fontsize=10)
    ax.set_title(
        f"{title}: {total} {cases}, pass rate per stage",
        loc="left",
        color=theme.text,
        fontsize=12,
        fontweight="bold",
        pad=28,
    )
    ax.tick_params(axis="y", length=0, labelcolor=theme.text)
    ax.tick_params(
        axis="x", color=theme.grid, labelcolor=theme.text_secondary, labelsize=10
    )
    ax.xaxis.grid(visible=True, color=theme.grid, linewidth=0.6)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(theme.grid)

    # every status in the legend, also one without cases in the first stage
    handles = [
        Patch(color=fill, label=status)
        for status, fill in zip(STATUSES, theme.fills, strict=True)
    ]
    ax.legend(
        handles=handles,
        loc="lower left",
        bbox_to_anchor=(0.0, 1.0),
        ncols=len(STATUSES),
        frameon=False,
        fontsize=10,
        labelcolor=theme.text_secondary,
        handlelength=1.0,
        handleheight=1.0,
        columnspacing=1.4,
        borderaxespad=0.2,
    )
    return fig


def timing_pairs(result: SuiteResult) -> dict[str, tuple[float, float]]:
    """Wall time of the two simulators, for every case both of them ran.

    Args:
        result: a suite run.

    Returns:
        The seconds of the `sbmlsim` and of the `libopencor` stage by case
        id, for the cases which both stages simulated.
    """
    sbmlsim = result.seconds("sbmlsim")
    libopencor = result.seconds("libopencor")
    return {
        cid: (sbmlsim[cid], libopencor[cid])
        for cid in sorted(sbmlsim.keys() & libopencor.keys())
    }


def _milliseconds(seconds: float) -> str:
    """A wall time in milliseconds, as the figures write it.

    Args:
        seconds: a wall time.

    Returns:
        The milliseconds, with a decimal below ten, e.g. `1.4 ms`, `18 ms`.
    """
    value = seconds * 1e3
    return f"{value:.1f} ms" if value < 10.0 else f"{value:.0f} ms"


def render_timings(
    result: SuiteResult,
    title: str | None = None,
    dark: bool = False,
    cases: str = "cases",
) -> Figure:
    """Render the timings of the two simulators, one point per case.

    The wall time of the libopencor simulation of the CellML model against
    the wall time of the sbmlsim-core simulation of the SBML model, on
    logarithmic axes: a point below the diagonal is a case libopencor
    simulates faster, a point above it one sbmlsim-core simulates faster.

    Args:
        result: a suite run.
        title: start of the title; the SBML test suite with its version when
            `None`.
        dark: whether the figure is for a dark background.
        cases: what a case is, in the title, e.g. `models`.

    Returns:
        The figure with a transparent background.
    """
    theme = _DARK if dark else _LIGHT
    if title is None:
        title = f"SBML test suite {result.suite}"
    pairs = timing_pairs(result)
    sbmlsim = [pair[0] for pair in pairs.values()]
    libopencor = [pair[1] for pair in pairs.values()]

    # a square figure: the axes are square (equal decades on both axes, so
    # the diagonal is the line of equal time) and fill it
    fig = Figure(figsize=(5.8, 5.8), layout="constrained")
    fig.patch.set_alpha(0.0)
    ax = fig.add_subplot()
    ax.patch.set_alpha(0.0)

    faster = [(x, y) for x, y in zip(sbmlsim, libopencor, strict=True) if y <= x]
    slower = [(x, y) for x, y in zip(sbmlsim, libopencor, strict=True) if y > x]
    for points, fill, label in (
        (faster, theme.fills[0], "libopencor faster"),
        (slower, theme.fills[1], "sbmlsim-core faster"),
    ):
        ax.scatter(
            [x for x, _ in points],
            [y for _, y in points],
            s=12,
            color=fill,
            alpha=0.65,
            linewidths=0,
            label=f"{label} ({len(points)})",
        )
    values = [*sbmlsim, *libopencor]
    low = min(values) / 1.6 if values else 1e-3
    high = max(values) * 1.6 if values else 1.0
    ax.plot(
        [low, high],
        [low, high],
        color=theme.grid,
        linewidth=1.0,
        linestyle="--",
        zorder=0,
    )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(low, high)
    ax.set_ylim(low, high)
    ax.set_aspect("equal")
    ax.set_xlabel(
        "sbmlsim-core, SBML model (s)", color=theme.text_secondary, fontsize=10
    )
    ax.set_ylabel(
        "libopencor, CellML model (s)", color=theme.text_secondary, fontsize=10
    )
    if pairs:
        ax.text(
            0.97,
            0.04,
            f"{len(pairs)} {cases}, median {_milliseconds(median(sbmlsim))} "
            f"and {_milliseconds(median(libopencor))}",
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            color=theme.text_secondary,
            fontsize=10,
        )
    ax.set_title(
        f"{title}: simulation time",
        loc="left",
        color=theme.text,
        fontsize=12,
        fontweight="bold",
        pad=28,
    )
    ax.tick_params(
        axis="both", color=theme.grid, labelcolor=theme.text_secondary, labelsize=10
    )
    ax.grid(visible=True, color=theme.grid, linewidth=0.6, which="major")
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme.grid)
    ax.legend(
        loc="lower left",
        bbox_to_anchor=(0.0, 1.0),
        ncols=2,
        frameon=False,
        fontsize=10,
        labelcolor=theme.text_secondary,
        handlelength=1.0,
        borderaxespad=0.2,
        scatterpoints=1,
    )
    return fig


def write_figures(
    result: SuiteResult,
    path: Path,
    title: str | None = None,
    cases: str = "cases",
) -> None:
    """Write the bar diagram for light and for dark backgrounds.

    Args:
        result: a suite run.
        path: SVG file of the figure for light backgrounds, overwritten; the
            figure for dark backgrounds goes to `dark_path(path)`.
        title: start of the title of the figure, see `render_figure`.
        cases: what a case is, see `render_figure`.
    """
    _write(render_figure, result, path, title=title, cases=cases)


def write_timing_figures(
    result: SuiteResult,
    path: Path,
    title: str | None = None,
    cases: str = "cases",
) -> None:
    """Write the timings of the two simulators for light and dark backgrounds.

    Args:
        result: a suite run.
        path: SVG file of the figure for light backgrounds, overwritten; the
            figure for dark backgrounds goes to `dark_path(path)`.
        title: start of the title of the figure, see `render_timings`.
        cases: what a case is, see `render_timings`.
    """
    _write(render_timings, result, path, title=title, cases=cases)


def _write(
    render: Callable[..., Figure],
    result: SuiteResult,
    path: Path,
    title: str | None = None,
    cases: str = "cases",
) -> None:
    """Write a figure for light and for dark backgrounds.

    Args:
        render: `render_figure` or `render_timings`.
        result: a suite run.
        path: SVG file of the figure for light backgrounds, overwritten; the
            figure for dark backgrounds goes to `dark_path(path)`.
        title: start of the title of the figure.
        cases: what a case is.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # text as paths and fixed ids, without the date: the files only change
    # with the results and look the same without the font installed
    with mpl.rc_context({"svg.fonttype": "path", "svg.hashsalt": "sbml2cellml"}):
        for file, dark in ((path, False), (dark_path(path), True)):
            buffer = io.StringIO()
            render(result, title=title, dark=dark, cases=cases).savefig(
                buffer, format="svg", metadata={"Date": None}
            )
            # matplotlib ends lines with spaces, which the pre-commit hooks
            # of the repository would remove from the committed figures
            lines = [line.rstrip() for line in buffer.getvalue().splitlines()]
            file.write_text("\n".join(lines) + "\n", encoding="utf-8")
