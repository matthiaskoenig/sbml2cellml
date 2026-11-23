"""The `sbml2cellml-overview` command.

    sbml2cellml-overview [--testsuite FILE] [--biomodels FILE] [--physiome FILE]
                         [--benchmarks docs/benchmarks.md]
                         [--models docs/models.md] [-v]

Renders the two pages across the checks from their committed results:
`docs/benchmarks.md` with the wall times of libopencor and sbmlsim-core and
its figures (`images/benchmarks.svg` and `images/benchmarks_medians.svg`,
each of them for light and for dark backgrounds) and `docs/models.md` with
the models of every check and the stages they pass. The command runs no
simulation; it is rerun after a check wrote new results.
"""

import argparse
import logging
import sys
from pathlib import Path

from sbml2cellml import __version__, log
from sbml2cellml.overview.checks import CHECKS, load_runs
from sbml2cellml.overview.report import write_benchmarks, write_models

DEFAULT_BENCHMARKS = Path("docs") / "benchmarks.md"
DEFAULT_MODELS = Path("docs") / "models.md"


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Returns:
        The parser with one option per check and one per page.
    """
    parser = argparse.ArgumentParser(
        prog="sbml2cellml-overview",
        description=(
            "Render the benchmark and the model page from the results of the checks."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    for check in CHECKS:
        parser.add_argument(
            f"--{check.name}",
            default=str(check.results),
            help=f"results file of the {check.name} check (json)",
        )
    parser.add_argument(
        "--benchmarks",
        default=str(DEFAULT_BENCHMARKS),
        help="benchmark page (markdown)",
    )
    parser.add_argument(
        "--models", default=str(DEFAULT_MODELS), help="model page (markdown)"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log the steps")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command.

    Args:
        argv: arguments without the program name, `sys.argv[1:]` by default.

    Returns:
        0 on success, 1 when no results file of a check exists.
    """
    args = build_parser().parse_args(argv)
    if args.verbose:
        log.enable_rich_logging(logging.INFO)
    runs = load_runs({check.name: Path(getattr(args, check.name)) for check in CHECKS})
    if not runs:
        print("No results of a check, nothing to render", file=sys.stderr)
        return 1
    benchmarks = Path(args.benchmarks)
    models = Path(args.models)
    write_benchmarks(runs, benchmarks)
    write_models(runs, models)
    names = ", ".join(run.check.name for run in runs)
    print(f"{len(runs)} checks ({names})\n{benchmarks}\n{models}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
