"""The `sbml2cellml-biomodels` command.

    sbml2cellml-biomodels run [--models biomodels/models.json] [--ids ID,ID]
                              [--count N] [--work-dir biomodels/work]
                              [--results FILE] [--report FILE] [--timeout SECONDS] [-v]
    sbml2cellml-biomodels update [--models biomodels/models.json] [--count N]
    sbml2cellml-biomodels report --results FILE --output FILE

`run` runs the pipeline over `--ids` or, by default, the selection file,
writes the results and the report; it gives up without writing either when
too many ids failed to download (`DOWNLOAD_FAILURE_FRACTION`, e.g. a
BioModels outage) or when no case was left to run, and, when `--results`
already exists, prints its regressions and improvements against the new run.
`update` refreshes the selection file from the current BioModels search.
`report` renders a results file. `run` and `report` write the bar diagram of
the report next to it (`images/biomodels.svg` and `images/biomodels_dark.svg`).

The check is run locally, not in continuous integration: it downloads and
simulates more than a thousand models.
"""

import argparse
import logging
import sys
from pathlib import Path

from sbml2cellml import __version__, log
from sbml2cellml.biomodels.models import (
    load_selection,
    query_curated_ids,
    write_selection,
)
from sbml2cellml.biomodels.runner import run_biomodels
from sbml2cellml.testsuite.report import write_report
from sbml2cellml.testsuite.results import STAGES, SuiteResult, improvements, regressions

DEFAULT_MODELS = Path("biomodels") / "models.json"
DEFAULT_RESULTS = Path("biomodels") / "results.json"
DEFAULT_REPORT = Path("docs") / "biomodels.md"
#: bar diagram of the report, relative to the report
BIOMODELS_FIGURE = "images/biomodels.svg"
#: start of the title of the bar diagram
BIOMODELS_FIGURE_TITLE = "BioModels, manually curated"
#: fraction of the requested ids whose download may fail before `run` gives
#: up instead of writing a mostly empty result (e.g. a BioModels outage)
DOWNLOAD_FAILURE_FRACTION = 0.05
#: intro paragraph of the BioModels report
BIOMODELS_INTRO = (
    "Manually curated SBML models of [BioModels](https://www.biomodels.org) "
    "(the ids in `biomodels/models.json`). Every model is simulated with "
    "roadrunner over 0 to 100 time units in 100 steps (`reference`), converted "
    "to CellML (`sbml2cellml`), simulated with libopencor (`libopencor`), "
    "converted back to SBML (`cellml2sbml`) and simulated with roadrunner again "
    "(`roundtrip`); the two later simulations are compared with the reference "
    "for every species and every other variable set by a rate rule or an "
    "assignment rule, with a relative tolerance of 1e-3 and an absolute "
    "tolerance of 1e-6. A `reference` failure means roadrunner cannot simulate "
    "the model, it says nothing about the converters. See "
    "[Development](development.md#biomodels) for how to run it."
)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        The parser with the `run`, `update` and `report` subcommands.
    """
    parser = argparse.ArgumentParser(
        prog="sbml2cellml-biomodels",
        description=(
            "Run the curated BioModels selection through sbml2cellml and cellml2sbml."
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
    run.add_argument("--ids", help="comma separated model ids, overrides --models")
    run.add_argument("--count", type=int, help="run only the first N ids")
    run.add_argument(
        "--work-dir", default="biomodels/work", help="directory for the converted files"
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
        "update", help="refresh the selection file from the current BioModels search"
    )
    update.add_argument(
        "--models", default=str(DEFAULT_MODELS), help="selection file (json)"
    )
    update.add_argument("--count", type=int, help="keep only the first N ids")

    report = subparsers.add_parser("report", help="render a results file")
    report.add_argument(
        "--results", default=str(DEFAULT_RESULTS), help="results file (json)"
    )
    report.add_argument(
        "--output", default=str(DEFAULT_REPORT), help="report file (markdown)"
    )
    return parser


def _run(args: argparse.Namespace) -> int:
    """The `run` subcommand."""
    if args.verbose:
        log.enable_rich_logging(logging.INFO)
    if args.ids:
        ids = [mid.strip() for mid in args.ids.split(",")]
    else:
        models_path = Path(args.models)
        if not models_path.is_file():
            print(f"Selection file does not exist: '{models_path}'", file=sys.stderr)
            return 1
        ids = list(load_selection(models_path).models)
    if args.count is not None:
        ids = ids[: args.count]

    result = run_biomodels(
        ids, work_dir=Path(args.work_dir), timeout=args.timeout, progress=print
    )

    download_failures = sum(
        1 for reason in result.skipped.values() if reason.startswith("download failed")
    )
    if ids and download_failures > DOWNLOAD_FAILURE_FRACTION * len(ids):
        print(
            f"{download_failures} of {len(ids)} ids failed to download, more than "
            f"{DOWNLOAD_FAILURE_FRACTION:.0%} of the ids",
            file=sys.stderr,
        )
        return 1
    if not result.cases:
        print("No cases to run", file=sys.stderr)
        return 1

    for stage in STAGES:
        counts = result.counts(stage)
        print(
            f"{stage}: {counts['pass']} pass, {counts['fail']} fail, {counts['skip']} skip"
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
    write_report(
        result,
        report_path,
        title="BioModels",
        intro=BIOMODELS_INTRO,
        command="sbml2cellml-biomodels",
        names=True,
        figure=BIOMODELS_FIGURE,
        figure_title=BIOMODELS_FIGURE_TITLE,
        figure_cases="models",
    )
    print(f"{results_path}\n{report_path}")
    return 0


def _update(args: argparse.Namespace) -> int:
    """The `update` subcommand."""
    ids = query_curated_ids()
    if args.count is not None:
        ids = ids[: args.count]
    models_path = Path(args.models)
    models_path.parent.mkdir(parents=True, exist_ok=True)
    selection = write_selection(models_path, ids)
    print(f"{len(selection.models)} ids written to {models_path}")
    return 0


def _report(args: argparse.Namespace) -> int:
    """The `report` subcommand."""
    results_path = Path(args.results)
    if not results_path.is_file():
        print(f"Results file does not exist: '{results_path}'", file=sys.stderr)
        return 1
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_report(
        SuiteResult.from_json(results_path),
        output,
        title="BioModels",
        intro=BIOMODELS_INTRO,
        command="sbml2cellml-biomodels",
        names=True,
        figure=BIOMODELS_FIGURE,
        figure_title=BIOMODELS_FIGURE_TITLE,
        figure_cases="models",
    )
    print(output)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the command.

    Args:
        argv: arguments without the program name, `sys.argv[1:]` by default.

    Returns:
        0 on success, 1 on a missing selection or results file.
    """
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return _run(args)
    if args.command == "update":
        return _update(args)
    return _report(args)


if __name__ == "__main__":
    sys.exit(main())
