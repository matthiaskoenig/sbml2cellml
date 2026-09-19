"""Bar diagram of a suite run, the figures `docs/images/testsuite*.svg`.

One horizontal bar per stage of the pipeline, stacked from the cases which
pass, fail and skip the stage, so the drop along the pipeline is visible at a
glance. The figure is written twice, for light and for dark backgrounds; both
are transparent, so they fit the documentation site as well as the README on
GitHub and PyPI.
"""

import io
from dataclasses import dataclass
from pathlib import Path, PurePath

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
    result: SuiteResult, title: str = "SBML test suite", dark: bool = False
) -> Figure:
    """Render the bar diagram.

    Args:
        result: a suite run.
        title: start of the title, followed by the version of the suite and
            the number of cases.
        dark: whether the figure is for a dark background.

    Returns:
        The figure with a transparent background.
    """
    theme = _DARK if dark else _LIGHT
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
    ax.set_xlabel("cases", color=theme.text_secondary, fontsize=10)
    ax.set_title(
        f"{title} {result.suite}: {total} cases, pass rate per stage",
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


def write_figures(
    result: SuiteResult, path: Path, title: str = "SBML test suite"
) -> None:
    """Write the bar diagram for light and for dark backgrounds.

    Args:
        result: a suite run.
        path: SVG file of the figure for light backgrounds, overwritten; the
            figure for dark backgrounds goes to `dark_path(path)`.
        title: start of the title of the figure.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # text as paths and fixed ids, without the date: the files only change
    # with the results and look the same without the font installed
    with mpl.rc_context({"svg.fonttype": "path", "svg.hashsalt": "sbml2cellml"}):
        for file, dark in ((path, False), (dark_path(path), True)):
            buffer = io.StringIO()
            render_figure(result, title=title, dark=dark).savefig(
                buffer, format="svg", metadata={"Date": None}
            )
            # matplotlib ends lines with spaces, which the pre-commit hooks
            # of the repository would remove from the committed figures
            lines = [line.rstrip() for line in buffer.getvalue().splitlines()]
            file.write_text("\n".join(lines) + "\n", encoding="utf-8")
