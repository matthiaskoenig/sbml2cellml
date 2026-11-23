"""The `sbml2cellml-physiome` command.

    sbml2cellml-physiome run [--models physiome/models.json] [--ids ID,ID]
                             [--count N] [--work-dir physiome/work]
                             [--results FILE] [--report FILE]
                             [--timeout SECONDS] [-v]
    sbml2cellml-physiome update [--models physiome/models.json] [--count N] [-v]
    sbml2cellml-physiome report --results FILE --output FILE

`run` runs the pipeline over the models of the selection file (or the
exposures of `--ids`), writes the results and the report and, when the
results file exists, prints the regressions and improvements against it.
`update` refreshes the selection from the exposures of the repository.
`report` renders a results file. `run` and `report` write the bar diagram
next to the report (`images/physiome.svg` and `images/physiome_dark.svg`).

The check is run locally, not in continuous integration: it clones the
workspaces of the models and simulates each of them three times.
"""

import argparse
import logging
import sys
from pathlib import Path

from sbml2cellml import __version__, log
from sbml2cellml.physiome.cases import ABSOLUTE, DURATION, RELATIVE, STEPS
from sbml2cellml.physiome.models import (
    PHYSIOME_URL,
    Exposure,
    PhysiomeError,
    exposure,
    query_exposures,
    read_selection,
    write_selection,
)
from sbml2cellml.physiome.runner import run_physiome
from sbml2cellml.testsuite.report import tolerance_text, write_report
from sbml2cellml.testsuite.results import (
    CELLML_STAGES,
    SuiteResult,
    improvements,
    regressions,
)

DEFAULT_MODELS = Path("physiome") / "models.json"
DEFAULT_RESULTS = Path("physiome") / "results.json"
DEFAULT_REPORT = Path("docs") / "physiome.md"
#: bar diagram of the report, relative to the report
PHYSIOME_FIGURE = "images/physiome.svg"
#: start of the title of the bar diagram
PHYSIOME_FIGURE_TITLE = "Physiome Model Repository"
#: intro paragraph of the report
PHYSIOME_INTRO = (
    "CellML models of the [Physiome Model Repository]"
    "(https://models.physiomeproject.org) (the exposures in "
    "`physiome/models.json`, most of them CellML 1.0 and 1.1 documents, "
    "which libcellml reads in its permissive mode). Every model is "
    "simulated with [libopencor](https://opencor.ws/libopencor/) over 0 to "
    f"{DURATION:g} time units in {STEPS} steps (`libopencor`, a fine output "
    "grid: the models are stiff and many of them switch their right-hand "
    "side hard, where the two solvers step over the switch differently on a "
    "coarse grid), converted to "
    "SBML (`cellml2sbml`), simulated with "
    "[sbmlsim-core](https://matthiaskoenig.github.io/sbmlsim-core/) "
    "(`sbmlsim`), converted back to CellML (`sbml2cellml`) and simulated "
    "with libopencor again (`roundtrip`). See "
    "[Development](development.md#physiome) for how to run it.\n\n"
    "The repository has no expected results: the `sbmlsim` and the "
    "`roundtrip` simulation are compared with the `libopencor` simulation "
    "of the model of the repository, over every variable of the model. A "
    "value passes when `|value - expected| <= absolute + relative * "
    f"|expected|` with a relative tolerance of `{tolerance_text(RELATIVE)}` "
    f"and an absolute tolerance of `{tolerance_text(ABSOLUTE)}`. "
    "{solver}\n\n"
    "A `libopencor` failure means libopencor cannot simulate the model of "
    "the repository, it says nothing about the converters."
)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        The parser with the `run`, `update` and `report` subcommands.
    """
    parser = argparse.ArgumentParser(
        prog="sbml2cellml-physiome",
        description=(
            "Run the Physiome Model Repository selection through cellml2sbml "
            "and sbml2cellml."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser(
        "run", help="run the selection, write results and report"
    )
    run.add_argument(
        "--models", default=str(DEFAULT_MODELS), help="selection file (json)"
    )
    run.add_argument("--ids", help="comma separated exposure ids, overrides --models")
    run.add_argument("--count", type=int, help="run only the first N models")
    run.add_argument(
        "--work-dir", default="physiome/work", help="directory for the converted files"
    )
    run.add_argument(
        "--results", default=str(DEFAULT_RESULTS), help="results file (json)"
    )
    run.add_argument(
        "--report", default=str(DEFAULT_REPORT), help="report file (markdown)"
    )
    run.add_argument(
        "--timeout", type=float, default=60.0, help="seconds per simulation"
    )
    run.add_argument("-v", "--verbose", action="store_true", help="log the steps")

    update = subparsers.add_parser(
        "update", help="refresh the selection from the exposures of the repository"
    )
    update.add_argument(
        "--models", default=str(DEFAULT_MODELS), help="selection file (json)"
    )
    update.add_argument("--count", type=int, help="keep only the first N models")
    update.add_argument("-v", "--verbose", action="store_true", help="log the steps")

    report = subparsers.add_parser("report", help="render a results file")
    report.add_argument(
        "--results", default=str(DEFAULT_RESULTS), help="results file (json)"
    )
    report.add_argument(
        "--output", default=str(DEFAULT_REPORT), help="report file (markdown)"
    )
    return parser


def _exposures(args: argparse.Namespace) -> list[Exposure] | None:
    """The exposures of a `run`, from `--ids` or the selection file."""
    if args.ids:
        exposures: list[Exposure] = []
        for exposure_id in (value.strip() for value in args.ids.split(",")):
            found = exposure(f"{PHYSIOME_URL}/e/{exposure_id}")
            if found is None:
                print(f"Exposure {exposure_id} has no CellML file", file=sys.stderr)
                return None
            exposures.append(found)
        return exposures
    models_path = Path(args.models)
    if not models_path.is_file():
        print(f"Selection file does not exist: '{models_path}'", file=sys.stderr)
        return None
    return list(read_selection(models_path).models)


def _run(args: argparse.Namespace) -> int:
    """The `run` subcommand."""
    if args.verbose:
        log.enable_rich_logging(logging.INFO)
    try:
        exposures = _exposures(args)
    except PhysiomeError as err:
        print(str(err), file=sys.stderr)
        return 1
    if exposures is None:
        return 1
    if args.count is not None:
        exposures = exposures[: args.count]

    result = run_physiome(
        exposures,
        work_dir=Path(args.work_dir),
        timeout=args.timeout,
        progress=print,
    )
    if not result.cases:
        print("No cases to run", file=sys.stderr)
        return 1

    for stage in CELLML_STAGES:
        counts = result.counts(stage)
        print(
            f"{stage}: {counts['pass']} pass, {counts['fail']} fail, "
            f"{counts['skip']} skip"
        )
    print(f"{len(result.skipped)} models skipped")

    results_path = Path(args.results)
    if results_path.is_file():
        previous = SuiteResult.from_json(results_path)
        regs = regressions(previous, result)
        print(f"{len(regs)} regressions")
        for line in regs:
            print(line)
        imps = improvements(previous, result)
        print(f"{len(imps)} improvements")
        for line in imps:
            print(line)

    results_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_json(results_path)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    _write(result, report_path)
    print(f"{results_path}\n{report_path}")
    return 0


def _write(result: SuiteResult, path: Path) -> None:
    """Write the report and its figures."""
    write_report(
        result,
        path,
        title="Physiome Model Repository",
        intro=PHYSIOME_INTRO,
        command="sbml2cellml-physiome",
        names=True,
        figure=PHYSIOME_FIGURE,
        figure_title=PHYSIOME_FIGURE_TITLE,
        figure_cases="models",
    )


def _update(args: argparse.Namespace) -> int:
    """The `update` subcommand."""
    if args.verbose:
        log.enable_rich_logging(logging.INFO)
    try:
        exposures = query_exposures()
    except PhysiomeError as err:
        print(str(err), file=sys.stderr)
        return 1
    if args.count is not None:
        exposures = exposures[: args.count]
    models_path = Path(args.models)
    models_path.parent.mkdir(parents=True, exist_ok=True)
    selection = write_selection(exposures, models_path)
    print(f"{len(selection.models)} models written to {models_path}")
    return 0


def _report(args: argparse.Namespace) -> int:
    """The `report` subcommand."""
    results_path = Path(args.results)
    if not results_path.is_file():
        print(f"Results file does not exist: '{results_path}'", file=sys.stderr)
        return 1
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    _write(SuiteResult.from_json(results_path), output)
    print(output)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the command.

    Args:
        argv: arguments without the program name, `sys.argv[1:]` by default.

    Returns:
        0 on success, 1 on a missing selection or results file, a failed
        request or a run without cases.
    """
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return _run(args)
    if args.command == "update":
        return _update(args)
    return _report(args)


if __name__ == "__main__":
    sys.exit(main())
