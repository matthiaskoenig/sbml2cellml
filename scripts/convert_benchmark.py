"""Benchmark of the two engines of the CellML to SBML conversion.

The rust engine (`sbml2cellml.rust`, the crates of `crates/`) reads a
CellML document and writes the SBML of it in the process; the python engine
(`sbml2cellml.cellml2sbml`) reads the document with libcellml, asks its
analyser what the equations determine and builds the document with libsbml.
Both are measured over the models of the Physiome check and the CellML
fixtures of the repository, three times each, the fastest run of the three
per model:

* `python`: `convert_cellml2sbml(path, engine="python")`, the conversion
  through libcellml, without the validation and without the metadata.
* `rust`: `convert_cellml2sbml(path, engine="rust")`, the rust conversion
  and the libsbml document read from its text, which the python API returns.
* `text`: the rust conversion alone, which is what a browser runs and what
  the compiler of sbmlsim-core takes.

The script writes the figure `docs/images/convert_benchmark.svg` and its
dark variant, prints the medians and the slowest models, and keeps the
measurements in `~/.cache/sbml2cellml/convert_benchmark.json`.

It is run locally, like the checks of BioModels and of the Physiome
repository:

```bash
uv run python scripts/convert_benchmark.py
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

from matplotlib.figure import Figure

from sbml2cellml import rust
from sbml2cellml.cellml2sbml import convert_cellml2sbml
from sbml2cellml.physiome.models import model_path, read_selection
from sbml2cellml.testsuite.figure import DARK, LIGHT, write_variants

REPO = Path(__file__).parent.parent
#: the CellML fixtures of the repository
FIXTURES = sorted((REPO / "tests" / "data").glob("*.cellml")) + sorted(
    (REPO / "examples" / "models").glob("*.cellml")
)
#: the figure of the benchmark
FIGURE = REPO / "docs" / "images" / "convert_benchmark.svg"
#: the measurements
RESULTS = Path.home() / ".cache" / "sbml2cellml" / "convert_benchmark.json"


@dataclass(frozen=True)
class Measurement:
    """What one model took with both engines, in seconds."""

    #: the file of the model
    path: str
    #: the number of components of the model, its size
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


def measure(path: Path, repeats: int) -> Measurement:
    """Measure both engines on one model.

    Args:
        path: the CellML file.
        repeats: how often every engine runs.

    Returns:
        The measurement of the model.
    """
    text = path.read_text(encoding="utf-8")
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


def corpus() -> list[Path]:
    """The documents of the corpus: the fixtures and the Physiome selection."""
    paths = list(FIXTURES)
    for exposure in read_selection(REPO / "physiome" / "models.json").models:
        try:
            paths.append(model_path(exposure))
        except Exception as err:  # a model which is not in the cache
            print(f"{exposure.id}: {err}", file=sys.stderr)
    return paths


def render(measurements: list[Measurement], dark: bool = False) -> Figure:
    """Render the figure of the benchmark.

    The left panel is the time of the python engine against the time of
    the rust engine on logarithmic axes, one point per model, with the line
    of equal time; the right panel how many times faster the rust engine
    and the rust conversion alone are, over the number of components of the
    model, with the median of both.

    Args:
        measurements: the measurements of the corpus.
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
    speedups.set_xlabel(
        "components of the model", color=theme.text_secondary, fontsize=10
    )
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


def report(measurements: list[Measurement]) -> None:
    """Print the medians, the extremes and what one engine alone converts.

    Args:
        measurements: the measurements of the corpus.
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
            f"({slowest.components} components), "
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
    """Measure both engines over the corpus and write the figure."""
    parser = argparse.ArgumentParser(
        prog="convert_benchmark",
        description="Benchmark the rust and the python engine of cellml2sbml.",
    )
    parser.add_argument("files", nargs="*", help="CellML files, the corpus by default")
    parser.add_argument("--count", type=int, help="measure only the first N files")
    parser.add_argument(
        "--repeats", type=int, default=3, help="runs per engine and model (default: 3)"
    )
    parser.add_argument(
        "--no-figure", action="store_true", help="do not write the figure"
    )
    args = parser.parse_args(argv)

    paths = [Path(file) for file in args.files] or corpus()
    if args.count:
        paths = paths[: args.count]
    measurements = []
    for index, path in enumerate(paths, start=1):
        measurement = measure(path, args.repeats)
        measurements.append(measurement)
        speedup = measurement.speedup
        print(
            f"[{index}/{len(paths)}] {path.name}: "
            + (f"{speedup:.0f}x faster" if speedup else "one engine only"),
            file=sys.stderr,
        )
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(
        json.dumps([asdict(m) for m in measurements], indent=2) + "\n",
        encoding="utf-8",
    )
    report(measurements)
    if not args.no_figure:
        write_variants(render, FIGURE, measurements=measurements)
        print(f"figure written to {FIGURE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
