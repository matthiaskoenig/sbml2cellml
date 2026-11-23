"""Figures which compare the two simulators over the checks.

`render_scatter` draws the integration time of libopencor against the
integration time of sbmlsim-core, one point per model and one color and
marker per check, so a point below the diagonal is a model libopencor
integrates faster. `render_medians` draws the median setup and the median
integration time of the two simulators per check. Every figure is written
twice, for light and for dark backgrounds, and is transparent, as the
figures of the reports (`sbml2cellml.testsuite.figure`).
"""

from pathlib import Path
from statistics import median

from matplotlib.figure import Figure

from sbml2cellml.overview.checks import Run
from sbml2cellml.testsuite.figure import (
    DARK,
    LIGHT,
    duration_text,
    setup_pairs,
    timing_pairs,
    write_variants,
)

#: marker of the series of a check, next to its color: the figures stay
#: readable for a color vision deficiency and in print
MARKERS = ("o", "^", "s")
#: the two simulators, with the index of their color in `Theme.fills` and
#: the index of their time in a pair of `timing_pairs`
SIMULATORS = (("libopencor", 0, 1), ("sbmlsim-core", 1, 0))


def render_scatter(runs: list[Run], dark: bool = False) -> Figure:
    """Render the integration times of the two simulators, one point per model.

    Only the models whose converted model reproduces the expected results
    are shown (`sbml2cellml.testsuite.figure.timing_pairs`): the two
    simulators integrate the same dynamics there.

    Args:
        runs: the runs of the checks.
        dark: whether the figure is for a dark background.

    Returns:
        The figure with a transparent background.
    """
    theme = DARK if dark else LIGHT
    pairs = {run.check.name: timing_pairs(run.result) for run in runs}
    values = [
        value for check in pairs.values() for pair in check.values() for value in pair
    ]
    low = min(values) / 1.6 if values else 1e-3
    high = max(values) * 1.6 if values else 1.0

    # square axes, so the diagonal is the line of equal time
    fig = Figure(figsize=(6.2, 6.2), layout="constrained")
    fig.patch.set_alpha(0.0)
    ax = fig.add_subplot()
    ax.patch.set_alpha(0.0)
    ax.plot(
        [low, high],
        [low, high],
        color=theme.grid,
        linewidth=1.0,
        linestyle="--",
        zorder=0,
    )
    for index, run in enumerate(runs):
        fill = theme.series[index % len(theme.series)]
        marker = MARKERS[index % len(MARKERS)]
        points = pairs[run.check.name]
        ax.scatter(
            [pair[0] for pair in points.values()],
            [pair[1] for pair in points.values()],
            s=14,
            color=fill,
            marker=marker,
            alpha=0.6,
            linewidths=0,
            label=f"{run.check.short} ({len(points)})",
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
    faster = sum(
        1
        for check in pairs.values()
        for sbmlsim, libopencor in check.values()
        if libopencor <= sbmlsim
    )
    total = sum(len(check) for check in pairs.values())
    ax.set_title(
        f"Integration time: libopencor faster for {faster} of {total}",
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
        ncols=len(runs) or 1,
        frameon=False,
        fontsize=10,
        labelcolor=theme.text_secondary,
        handlelength=1.0,
        borderaxespad=0.2,
        scatterpoints=1,
    )
    return fig


def render_medians(runs: list[Run], dark: bool = False) -> Figure:
    """Render the median setup and integration time of the two simulators.

    One panel for the setup and one for the integration, in both of them one
    pair of bars per check, over the models both simulators ran
    (`sbml2cellml.testsuite.figure.timing_pairs`).

    Args:
        runs: the runs of the checks.
        dark: whether the figure is for a dark background.

    Returns:
        The figure with a transparent background.
    """
    theme = DARK if dark else LIGHT
    phases = (
        ("setup", [setup_pairs(run.result) for run in runs]),
        ("integration", [timing_pairs(run.result) for run in runs]),
    )
    values = [
        median([pair[index] for pair in check.values()])
        for _, checks in phases
        for check in checks
        if check
        for _, _, index in SIMULATORS
    ]
    low = min(values) / 2.0 if values else 1e-3
    # room for the value at the end of a bar
    high = max(values) * 6.0 if values else 1.0

    fig = Figure(figsize=(8.6, 0.9 * (len(runs) or 1) + 1.9), layout="constrained")
    fig.patch.set_alpha(0.0)
    axes = fig.subplots(1, 2, sharey=True)
    for ax, (phase, checks) in zip(axes, phases, strict=True):
        ax.patch.set_alpha(0.0)
        for offset, (simulator, color, index) in zip(
            (-0.19, 0.19), SIMULATORS, strict=True
        ):
            for row, pairs in enumerate(checks):
                if not pairs:
                    continue
                value = median([pair[index] for pair in pairs.values()])
                ax.barh(
                    row + offset,
                    value,
                    height=0.34,
                    color=theme.fills[color],
                    linewidth=0,
                    label=simulator if row == 0 else None,
                )
                ax.text(
                    value * 1.25,
                    row + offset,
                    duration_text(value),
                    ha="left",
                    va="center",
                    color=theme.text_secondary,
                    fontsize=9,
                )
        ax.set_xscale("log")
        ax.set_xlim(low, high)
        ax.set_yticks(
            range(len(runs)), labels=[run.check.short for run in runs], fontsize=10
        )
        ax.set_xlabel(f"median {phase} (s)", color=theme.text_secondary, fontsize=10)
        ax.tick_params(axis="y", length=0, labelcolor=theme.text)
        ax.tick_params(
            axis="x", color=theme.grid, labelcolor=theme.text_secondary, labelsize=10
        )
        ax.xaxis.grid(visible=True, color=theme.grid, linewidth=0.6)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(theme.grid)

    # the axes share the y axis, so one inversion puts the first check on top
    axes[0].invert_yaxis()
    axes[0].set_title(
        "Wall time of the two simulators per check",
        loc="left",
        color=theme.text,
        fontsize=12,
        fontweight="bold",
        pad=28,
    )
    axes[0].legend(
        loc="lower left",
        bbox_to_anchor=(0.0, 1.0),
        ncols=len(SIMULATORS),
        frameon=False,
        fontsize=10,
        labelcolor=theme.text_secondary,
        handlelength=1.0,
        handleheight=1.0,
        columnspacing=1.4,
        borderaxespad=0.2,
    )
    return fig


def write_scatter_figures(runs: list[Run], path: Path) -> None:
    """Write the scatter of the integration times for light and dark backgrounds.

    Args:
        runs: the runs of the checks.
        path: SVG file of the figure for light backgrounds, overwritten; the
            figure for dark backgrounds goes next to it
            (`sbml2cellml.testsuite.figure.dark_path`).
    """
    write_variants(render_scatter, path, runs=runs)


def write_median_figures(runs: list[Run], path: Path) -> None:
    """Write the median wall times for light and for dark backgrounds.

    Args:
        runs: the runs of the checks.
        path: SVG file of the figure for light backgrounds, overwritten; the
            figure for dark backgrounds goes next to it
            (`sbml2cellml.testsuite.figure.dark_path`).
    """
    write_variants(render_medians, path, runs=runs)
