"""Benchmark of the two engines of both conversions.

The rust engine (`sbml2cellml.rust`, the crates of `crates/`) converts a
document in the process without libcellml and without libsbml; the python
engine reads the document with libcellml or libsbml and builds the result
with the other library. Both directions are measured, three runs each and
the fastest of the three per model:

* `cellml2sbml`, the models of the Physiome check and the CellML fixtures
  of the repository: `python` is `convert_cellml2sbml(path,
  engine="python")`, which asks the analyser of libcellml what the
  equations determine and builds the document with libsbml, `rust` the
  same call with the rust engine, which reads the SBML text of the rust
  conversion back with libsbml, and `text` the rust conversion alone.
* `sbml2cellml`, the models of the repository and of the BioModels check:
  `python` is `convert_sbml2cellml(path, engine="python")`, which reads the
  model with libsbml and builds the CellML model with libcellml, `rust` the
  same call with the rust engine, which parses the CellML text of the rust
  conversion with libcellml, and `text` the rust conversion alone.

The conversion alone is what a browser runs and what the compiler of
sbmlsim-core takes; the validation and the metadata are off in every run.

The script writes the figure `docs/images/convert_benchmark.svg` of the
CellML to SBML direction or `docs/images/convert_benchmark_cellml.svg` of
the SBML to CellML direction and their dark variants, prints the medians
and the slowest models, and keeps the measurements in
`~/.cache/sbml2cellml/convert_benchmark<direction>.json`.

It is run locally, like the checks of BioModels and of the Physiome
repository:

```bash
uv run python scripts/convert_benchmark.py
uv run python scripts/convert_benchmark.py --direction sbml2cellml
uv run python scripts/convert_benchmark.py --count 10 --repeats 5
```
"""

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Literal, get_args

from matplotlib.figure import Figure

from sbml2cellml import rust
from sbml2cellml.cellml2sbml import convert_cellml2sbml
from sbml2cellml.physiome.models import model_path, read_selection
from sbml2cellml.sbml2cellml import convert_sbml2cellml
from sbml2cellml.testsuite.figure import DARK, LIGHT, write_variants

REPO = Path(__file__).parent.parent
#: the CellML fixtures of the repository
FIXTURES = sorted((REPO / "tests" / "data").glob("*.cellml")) + sorted(
    (REPO / "examples" / "models").glob("*.cellml")
)
#: the SBML models of the repository
SBML_FIXTURES = sorted((REPO / "examples" / "models").glob("*.xml"))
#: which conversion is measured
Direction = Literal["cellml2sbml", "sbml2cellml"]
#: the values of `Direction`, for the command line
DIRECTIONS: tuple[str, ...] = get_args(Direction)
#: the figure of the benchmark of every direction
FIGURES: dict[str, Path] = {
    "cellml2sbml": REPO / "docs" / "images" / "convert_benchmark.svg",
    "sbml2cellml": REPO / "docs" / "images" / "convert_benchmark_cellml.svg",
}
#: the measurements of every direction
RESULTS: dict[str, Path] = {
    "cellml2sbml": Path.home() / ".cache" / "sbml2cellml" / "convert_benchmark.json",
    "sbml2cellml": Path.home()
    / ".cache"
    / "sbml2cellml"
    / "convert_benchmark_cellml.json",
}
#: what the size of a model is in every direction, for the figure
SIZES: dict[str, str] = {
    "cellml2sbml": "components of the model",
    "sbml2cellml": "quantities of the model",
}
#: what one of them is, for the report
SIZE: dict[str, str] = {"cellml2sbml": "components", "sbml2cellml": "quantities"}


@dataclass(frozen=True)
class Measurement:
    """What one model took with both engines, in seconds."""

    #: the file of the model
    path: str
    #: the size of the model, the components of a CellML document and the
    #: compartments, species, parameters and reactions of an SBML document
    components: int
    #: `convert_cellml2sbml` with the python engine, `None` when it refuses
    python: float | None
    #: `convert_cellml2sbml` with the rust engine, `None` when it refuses
    rust: float | None
    #: the rust conversion alone, without the libsbml document
    text: float | None

    @property
    def speedup(self) -> float | None:
        """How many times faster the rust engine converts the model."""
        if self.python is None or self.rust is None:
            return None
        return self.python / self.rust

    @property
    def text_speedup(self) -> float | None:
        """How many times faster the rust conversion alone is."""
        if self.python is None or self.text is None:
            return None
        return self.python / self.text


def fastest(call: Callable[[], object], repeats: int) -> float | None:
    """The fastest of several runs of a call, `None` when it raises.

    Args:
        call: what is measured.
        repeats: how often it is run.

    Returns:
        The wall time of the fastest run in seconds, `None` when the call
        raised in the first run.
    """
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        try:
            call()
        except Exception:
            return None
        times.append(time.perf_counter() - start)
    return min(times)


def measure(path: Path, repeats: int, direction: Direction) -> Measurement:
    """Measure both engines on one model.

    Args:
        path: the CellML or SBML file.
        repeats: how often every engine runs.
        direction: which conversion is measured.

    Returns:
        The measurement of the model.
    """
    text = path.read_text(encoding="utf-8")
    if direction == "cellml2sbml":
        return Measurement(
            path=str(path),
            components=text.count("<component "),
            python=fastest(
                lambda: convert_cellml2sbml(
                    path, validate=False, metadata=False, engine="python"
                ),
                repeats,
            ),
            rust=fastest(
                lambda: convert_cellml2sbml(
                    path, validate=False, metadata=False, engine="rust"
                ),
                repeats,
            ),
            text=fastest(lambda: rust.convert_cellml_to_sbml(text), repeats),
        )
    return Measurement(
        path=str(path),
        components=sum(
            text.count(element)
            for element in ("<compartment ", "<species ", "<parameter ", "<reaction ")
        ),
        python=fastest(
            lambda: convert_sbml2cellml(
                path, validate=False, metadata=False, engine="python"
            ),
            repeats,
        ),
        rust=fastest(
            lambda: convert_sbml2cellml(
                path, validate=False, metadata=False, engine="rust"
            ),
            repeats,
        ),
        text=fastest(lambda: rust.convert_sbml_to_cellml(text, path.stem), repeats),
    )


def corpus(direction: Direction) -> list[Path]:
    """The documents of the corpus of a direction.

    Args:
        direction: which conversion is measured.

    Returns:
        The fixtures of the repository and the models of the Physiome check
        for the CellML to SBML direction, the SBML models of the repository
        and the models of the BioModels check for the other one.
    """
    if direction == "sbml2cellml":
        from sbml2cellml.biomodels.models import biomodels_cache

        return list(SBML_FIXTURES) + sorted(biomodels_cache().glob("*/*.xml"))
    paths = list(FIXTURES)
    for exposure in read_selection(REPO / "physiome" / "models.json").models:
        try:
            paths.append(model_path(exposure))
        except Exception as err:  # a model which is not in the cache
            print(f"{exposure.id}: {err}", file=sys.stderr)
    return paths


def render(
    measurements: list[Measurement],
    size: str = SIZES["cellml2sbml"],
    dark: bool = False,
) -> Figure:
    """Render the figure of the benchmark.

    The left panel is the time of the python engine against the time of
    the rust engine on logarithmic axes, one point per model, with the line
    of equal time; the right panel how many times faster the rust engine
    and the rust conversion alone are, over the number of components of the
    model, with the median of both.

    Args:
        measurements: the measurements of the corpus.
        size: what the size of a model is, the label of the x axis of the
            right panel (`SIZES`).
        dark: whether the figure is for a dark background.

    Returns:
        The figure with a transparent background.
    """
    theme = DARK if dark else LIGHT
    pairs = [
        (m.components, python, engine, text)
        for m in measurements
        if (python := m.python) is not None
        and (engine := m.rust) is not None
        and (text := m.text) is not None
    ]
    fig = Figure(figsize=(9.6, 4.8), layout="constrained")
    fig.patch.set_alpha(0.0)
    times, speedups = fig.subplots(1, 2)
    for ax in (times, speedups):
        ax.patch.set_alpha(0.0)
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.tick_params(
            axis="both", color=theme.grid, labelcolor=theme.text_secondary, labelsize=10
        )
        ax.grid(visible=True, color=theme.grid, linewidth=0.6, which="major")
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(theme.grid)

    times.scatter(
        [python for _, python, _, _ in pairs],
        [engine for _, _, engine, _ in pairs],
        s=14,
        color=theme.series[0],
        alpha=0.7,
        linewidths=0,
    )
    values = [value for _, python, engine, _ in pairs for value in (python, engine)]
    low = min(values) / 1.6 if values else 1e-4
    high = max(values) * 1.6 if values else 1.0
    times.plot(
        [low, high],
        [low, high],
        color=theme.grid,
        linewidth=1.0,
        linestyle="--",
        zorder=0,
    )
    times.set_xlim(low, high)
    times.set_ylim(low, high)
    times.set_aspect("equal")
    times.set_xlabel("python engine (s)", color=theme.text_secondary, fontsize=10)
    times.set_ylabel("rust engine (s)", color=theme.text_secondary, fontsize=10)
    times.set_title(
        "Conversion time",
        loc="left",
        color=theme.text,
        fontsize=12,
        fontweight="bold",
        pad=10,
    )

    for index, (label, values) in enumerate(
        (
            ("rust engine", [(size, python / e) for size, python, e, _ in pairs]),
            (
                "rust conversion alone",
                [(size, python / text) for size, python, _, text in pairs],
            ),
        )
    ):
        speedups.scatter(
            [size for size, _ in values],
            [factor for _, factor in values],
            s=14,
            color=theme.series[index],
            marker=("o", "^")[index],
            alpha=0.7,
            linewidths=0,
            label=f"{label} (median {median([f for _, f in values]):.0f}x)",
        )
        speedups.axhline(
            median([factor for _, factor in values]),
            color=theme.series[index],
            linewidth=1.0,
            linestyle="--",
            alpha=0.5,
            zorder=0,
        )
    speedups.set_xlabel(size, color=theme.text_secondary, fontsize=10)
    speedups.set_ylabel(
        "times faster than the python engine", color=theme.text_secondary, fontsize=10
    )
    speedups.set_title(
        f"Speedup over {len(pairs)} models",
        loc="left",
        color=theme.text,
        fontsize=12,
        fontweight="bold",
        pad=10,
    )
    # the legend of the two series above the panels, so that the titles of
    # the two panels sit at the same height
    fig.legend(
        *speedups.get_legend_handles_labels(),
        loc="outside upper right",
        ncols=2,
        frameon=False,
        fontsize=10,
        labelcolor=theme.text_secondary,
        handlelength=1.0,
        borderaxespad=0.2,
        scatterpoints=1,
    )
    return fig


def report(measurements: list[Measurement], size: str = SIZE["cellml2sbml"]) -> None:
    """Print the medians, the extremes and what one engine alone converts.

    Args:
        measurements: the measurements of the corpus.
        size: what the size of a model is (`SIZE`).
    """
    times = [
        (m, m.python, m.rust, m.text)
        for m in measurements
        if m.python is not None and m.rust is not None and m.text is not None
    ]
    speedups = sorted(python / engine for _, python, engine, _ in times)
    text_speedups = sorted(python / text for _, python, _, text in times)
    print(f"{len(measurements)} models, {len(times)} converted by both engines")
    if times:
        for label, index in (
            ("python engine", 1),
            ("rust engine  ", 2),
            ("rust alone   ", 3),
        ):
            values = [row[index] for row in times]
            print(
                f"  {label}: median {median(values) * 1e3:.1f} ms, "
                f"total {sum(values):.2f} s"
            )
        print(
            f"  speedup: median {median(speedups):.0f}x, "
            f"from {speedups[0]:.0f}x to {speedups[-1]:.0f}x; "
            f"the conversion alone median {median(text_speedups):.0f}x"
        )
        slowest, python, engine, _ = max(times, key=lambda row: row[1])
        print(
            f"  slowest model: {Path(slowest.path).name} "
            f"({slowest.components} {size}), "
            f"{python * 1e3:.0f} ms python, {engine * 1e3:.1f} ms rust"
        )
    for label, found in (
        ("rust only", [m for m in measurements if m.python is None and m.rust]),
        ("python only", [m for m in measurements if m.rust is None and m.python]),
        ("neither", [m for m in measurements if m.rust is None and m.python is None]),
    ):
        if found:
            print(f"  {label}: {len(found)}")


def main(argv: list[str] | None = None) -> int:
    """Measure both engines over the corpus of a direction and write the figure."""
    parser = argparse.ArgumentParser(
        prog="convert_benchmark",
        description="Benchmark the rust and the python engine of both conversions.",
    )
    parser.add_argument("files", nargs="*", help="the files, the corpus by default")
    parser.add_argument(
        "--direction",
        choices=DIRECTIONS,
        default="cellml2sbml",
        help="which conversion is measured (default: cellml2sbml)",
    )
    parser.add_argument("--count", type=int, help="measure only the first N files")
    parser.add_argument(
        "--repeats", type=int, default=3, help="runs per engine and model (default: 3)"
    )
    parser.add_argument(
        "--no-figure", action="store_true", help="do not write the figure"
    )
    args = parser.parse_args(argv)

    direction: Direction = args.direction
    paths = [Path(file) for file in args.files] or corpus(direction)
    if args.count:
        paths = paths[: args.count]
    measurements = []
    for index, path in enumerate(paths, start=1):
        measurement = measure(path, args.repeats, direction)
        measurements.append(measurement)
        speedup = measurement.speedup
        print(
            f"[{index}/{len(paths)}] {path.name}: "
            + (f"{speedup:.0f}x faster" if speedup else "one engine only"),
            file=sys.stderr,
        )
    results = RESULTS[direction]
    results.parent.mkdir(parents=True, exist_ok=True)
    results.write_text(
        json.dumps([asdict(m) for m in measurements], indent=2) + "\n",
        encoding="utf-8",
    )
    report(measurements, SIZE[direction])
    if not args.no_figure:
        figure = FIGURES[direction]
        write_variants(render, figure, measurements=measurements, size=SIZES[direction])
        print(f"figure written to {figure}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
