"""Command line interface of sbml2cellml.

    sbml2cellml INPUT.xml [-o OUTPUT.cellml] [--no-validate] [-v]

converts an SBML file to CellML. Without `-o` the CellML is written next to
the input with the `.cellml` suffix.
"""

import argparse
import logging
import sys
from pathlib import Path

from sbml2cellml import __version__, log
from sbml2cellml.cellml import CellMLValidationError
from sbml2cellml.sbml2cellml import SBML2CellMLConversionError, convert_sbml2cellml


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser of the command.

    Returns:
        The parser.
    """
    parser = argparse.ArgumentParser(
        prog="sbml2cellml", description="Convert an SBML model to CellML."
    )
    parser.add_argument("input", help="SBML file")
    parser.add_argument(
        "-o",
        "--output",
        help="CellML file, by default the input with the suffix .cellml",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="write the CellML even if libcellml reports errors",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="log the conversion steps"
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command.

    Args:
        argv: arguments without the program name, `sys.argv[1:]` by default.

    Returns:
        0 on success, 1 on a missing input, a conversion or a validation error.
    """
    args = build_parser().parse_args(argv)
    if args.verbose:
        log.enable_rich_logging(logging.INFO)

    sbml_path = Path(args.input)
    if not sbml_path.is_file():
        print(f"Input file does not exist: '{sbml_path}'", file=sys.stderr)
        return 1
    cellml_path = Path(args.output) if args.output else sbml_path.with_suffix(".cellml")

    try:
        convert_sbml2cellml(
            sbml_path, cellml_path=cellml_path, validate=not args.no_validate
        )
    except (SBML2CellMLConversionError, CellMLValidationError) as err:
        print(str(err), file=sys.stderr)
        return 1

    print(cellml_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
