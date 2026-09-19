"""Roundtrip of the repressilator: SBML to CellML and back to SBML.

The model is the repressilator of Elowitz and Leibler (2000), BIOMD0000000012
of BioModels without its notes and annotations. It is simulated three times:
the SBML model with roadrunner, the converted CellML model with libopencor and
the SBML model converted back from the CellML with roadrunner again. The three
timecourses of the proteins are plotted side by side.

`python repressilator_example.py --docs` also updates the files of the
documentation page `docs/roundtrip.md`.
"""

import argparse
import io
import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.figure import Figure

from sbml2cellml import convert_cellml2sbml, convert_sbml2cellml, log
from sbml2cellml.console import console
from sbml2cellml.simulate import run_timecourse

EXAMPLES_DIR: Path = Path(__file__).parent
MODELS_DIR: Path = EXAMPLES_DIR / "models"
RESULTS_DIR: Path = EXAMPLES_DIR / "results"
DOCS_DIR: Path = EXAMPLES_DIR.parent / "docs"

#: the proteins of the three repressors, id and name
PROTEINS: dict[str, str] = {"PX": "LacI", "PY": "TetR", "PZ": "cI"}
#: end of the simulation in minutes and number of steps
END: float = 600.0
STEPS: int = 600

#: colors of the proteins, text and grid for light and dark backgrounds
THEMES: dict[str, dict[str, str | list[str]]] = {
    "light": {
        "series": ["#2a78d6", "#eb6834", "#1baf7a"],
        "text": "#0b0b0b",
        "text_secondary": "#52514e",
        "grid": "#d9d8d3",
    },
    "dark": {
        "series": ["#3987e5", "#d95926", "#199e70"],
        "text": "#ffffff",
        "text_secondary": "#c3c2b7",
        "grid": "#4a4a47",
    },
}


def convert(sbml_path: Path, results_dir: Path) -> tuple[Path, Path]:
    """Convert the SBML model to CellML and the CellML model back to SBML.

    Returns:
        The paths of the CellML model and of the SBML model of the roundtrip.
    """
    cellml_path = results_dir / "repressilator.cellml"
    roundtrip_path = results_dir / "repressilator_roundtrip.xml"
    convert_sbml2cellml(sbml_path, cellml_path=cellml_path)
    convert_cellml2sbml(cellml_path, sbml_path=roundtrip_path)
    return cellml_path, roundtrip_path


def simulate_roadrunner(sbml_path: Path, csv_path: Path) -> pd.DataFrame:
    """Simulate an SBML model with roadrunner in a process of its own.

    roadrunner and libopencor crash in one process, see
    `roadrunner_timecourse.py`.
    """
    subprocess.run(
        [
            sys.executable,
            str(EXAMPLES_DIR / "roadrunner_timecourse.py"),
            str(sbml_path),
            str(csv_path),
            *PROTEINS,
            "--end",
            str(END),
            "--steps",
            str(STEPS),
        ],
        check=True,
    )
    return pd.read_csv(csv_path)


def simulate_libopencor(cellml_path: Path) -> pd.DataFrame:
    """Simulate a CellML model with libopencor."""
    df, _ = run_timecourse(cellml_path, start=0.0, end=END, steps=STEPS)
    return df[["time", *PROTEINS]]


def plot_roundtrip(timecourses: dict[str, pd.DataFrame], dark: bool = False) -> Figure:
    """Plot the timecourses of the proteins side by side, one panel each.

    Args:
        timecourses: timecourse with the columns `time` and the proteins by
            the title of its panel.
        dark: colors for a dark background.
    """
    theme = THEMES["dark" if dark else "light"]
    fig, axes = plt.subplots(
        ncols=len(timecourses), figsize=(8.0, 3.0), sharex=True, sharey=True
    )
    for ax, (title, df) in zip(axes, timecourses.items(), strict=True):
        for (sid, name), color in zip(PROTEINS.items(), theme["series"], strict=True):
            ax.plot(df["time"], df[sid], color=color, linewidth=1.6, label=name)
        ax.set_title(title, color=theme["text"], fontsize=10, loc="left")
        ax.set_xticks(range(0, int(END) + 1, 200))
        ax.set_xlabel("time [min]", color=theme["text_secondary"], fontsize=10)
        ax.grid(visible=True, color=theme["grid"], linewidth=0.6)
        ax.set_axisbelow(True)
        ax.tick_params(
            color=theme["grid"], labelcolor=theme["text_secondary"], labelsize=10
        )
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(theme["grid"])
        ax.patch.set_alpha(0.0)
    axes[0].set_ylabel(
        "protein [molecules per cell]", color=theme["text_secondary"], fontsize=10
    )
    fig.legend(
        *axes[0].get_legend_handles_labels(),
        loc="upper center",
        bbox_to_anchor=(0.5, 1.08),
        ncols=len(PROTEINS),
        frameon=False,
        labelcolor=theme["text_secondary"],
        fontsize=10,
    )
    fig.patch.set_alpha(0.0)
    fig.tight_layout()
    return fig


def write_svg(fig: Figure, path: Path) -> None:
    """Write a figure as SVG which only changes when the figure does.

    Text as paths, fixed ids and no date; matplotlib ends lines with spaces,
    which the pre-commit hooks of the repository would remove.
    """
    with mpl.rc_context({"svg.fonttype": "path", "svg.hashsalt": "sbml2cellml"}):
        buffer = io.StringIO()
        fig.savefig(buffer, format="svg", bbox_inches="tight", metadata={"Date": None})
    plt.close(fig)
    lines = [line.rstrip() for line in buffer.getvalue().splitlines()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def largest_differences(timecourses: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Largest difference of every protein to the first timecourse, per panel."""
    reference, *others = timecourses.values()
    return pd.DataFrame(
        {
            title: (df[list(PROTEINS)] - reference[list(PROTEINS)]).abs().max()
            for title, df in zip(list(timecourses)[1:], others, strict=True)
        }
    )


def differences_table(differences: pd.DataFrame) -> str:
    """The largest differences as a markdown table, for the documentation."""
    lines = [
        f"| protein | {' | '.join(differences.columns)} |",
        f"| --- | {' | '.join('---:' for _ in differences.columns)} |",
    ]
    for sid, row in differences.iterrows():
        values = " | ".join(f"{value:.1g}" for value in row)
        lines.append(f"| {PROTEINS[str(sid)]} (`{sid}`) | {values} |")
    return "\n".join(lines) + "\n"


def main(update_docs: bool = False) -> None:
    """Convert, simulate and plot; write everything into `examples/results/`."""
    RESULTS_DIR.mkdir(exist_ok=True)
    sbml_path = MODELS_DIR / "repressilator.xml"

    console.rule("convert", style="white")
    cellml_path, roundtrip_path = convert(sbml_path, RESULTS_DIR)

    console.rule("simulate", style="white")
    timecourses = {
        "1 SBML, roadrunner": simulate_roadrunner(
            sbml_path, RESULTS_DIR / "repressilator_sbml.csv"
        ),
        "2 CellML, libopencor": simulate_libopencor(cellml_path),
        "3 SBML, roadrunner": simulate_roadrunner(
            roundtrip_path, RESULTS_DIR / "repressilator_roundtrip.csv"
        ),
    }
    differences = largest_differences(timecourses)
    console.print(differences)
    differences_path = RESULTS_DIR / "repressilator_differences.md"
    differences_path.write_text(differences_table(differences), encoding="utf-8")

    figures: dict[str, Path] = {}
    for dark in (False, True):
        name = "repressilator_dark.svg" if dark else "repressilator.svg"
        figures[name] = RESULTS_DIR / name
        write_svg(plot_roundtrip(timecourses, dark=dark), figures[name])

    if update_docs:
        (DOCS_DIR / "roundtrip").mkdir(exist_ok=True)
        for path in (cellml_path, roundtrip_path, differences_path):
            shutil.copy(path, DOCS_DIR / "roundtrip" / path.name)
        for name, path in figures.items():
            shutil.copy(path, DOCS_DIR / "images" / name)
        console.print(f"documentation updated in '{DOCS_DIR}'")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--docs", action="store_true", help="update the files of docs/roundtrip.md"
    )
    args = parser.parse_args()
    log.enable_rich_logging()
    main(update_docs=args.docs)
