"""The `sbml2cellml-testsuite` command.

    sbml2cellml-testsuite run [--cases 00001,00002] [--suite-dir DIR] [--work-dir DIR]
                              [--results FILE] [--report FILE] [--timeout SECONDS] [-v]
    sbml2cellml-testsuite report --results FILE --output FILE

`run` downloads the suite when no `--suite-dir` is given, runs the pipeline,
writes the results and the report. `report` renders a results file.
"""

import argparse
import logging
import sys
from pathlib import Path

from sbml2cellml import __version__, log
from sbml2cellml.testsuite.cases import TestSuiteError, ensure_suite, load_cases
from sbml2cellml.testsuite.report import write_report
from sbml2cellml.testsuite.results import STAGES, SuiteResult
from sbml2cellml.testsuite.runner import run_suite

DEFAULT_RESULTS = Path("testsuite") / "results.json"
DEFAULT_REPORT = Path("docs") / "testsuite.md"


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        The parser with the `run` and `report` subcommands.
    """
    parser = argparse.ArgumentParser(
        prog="sbml2cellml-testsuite",
        description="Run the SBML test suite through sbml2cellml and cellml2sbml.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="run the suite, write results and report")
    run.add_argument("--cases", help="comma separated case ids, all by default")
    run.add_argument(
        "--suite-dir", help="semantic directory of the suite, downloaded by default"
    )
    run.add_argument(
        "--work-dir", default="testsuite/work", help="directory for the converted files"
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
    try:
        root = Path(args.suite_dir) if args.suite_dir else ensure_suite()
    except TestSuiteError as err:
        print(str(err), file=sys.stderr)
        return 1
    ids = [cid.strip() for cid in args.cases.split(",")] if args.cases else None
    cases = load_cases(root, ids)
    if not cases:
        print(f"No cases found in '{root}'", file=sys.stderr)
        return 1

    result = run_suite(cases, Path(args.work_dir), timeout=args.timeout, progress=print)
    for cid, case in result.cases.items():
        statuses = " ".join(f"{stage}={case.stages[stage].status}" for stage in STAGES)
        print(f"{cid} {statuses}")
    for stage in STAGES:
        counts = result.counts(stage)
        print(
            f"{stage}: {counts['pass']} pass, {counts['fail']} fail, {counts['skip']} skip"
        )
    print(f"{len(result.skipped)} cases skipped")

    results_path = Path(args.results)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_json(results_path)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_report(result, report_path)
    print(f"{results_path}\n{report_path}")
    return 0


def _report(args: argparse.Namespace) -> int:
    """The `report` subcommand."""
    results_path = Path(args.results)
    if not results_path.is_file():
        print(f"Results file does not exist: '{results_path}'", file=sys.stderr)
        return 1
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    write_report(SuiteResult.from_json(results_path), output)
    print(output)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the command.

    Args:
        argv: arguments without the program name, `sys.argv[1:]` by default.

    Returns:
        0 on success, 1 on a missing suite or results file.
    """
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return _run(args)
    return _report(args)


if __name__ == "__main__":
    sys.exit(main())
