"""Command line interfaces of sbml2cellml.

    sbml2cellml INPUT.xml [-o OUTPUT.cellml] [--no-validate] [-v]
    cellml2sbml INPUT.cellml [-o OUTPUT.xml] [--no-validate] [-v]

convert between SBML and CellML. Without `-o` the output is written next to
the input with the suffix of the other format.
"""

import argparse
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sbml2cellml import __version__, log
from sbml2cellml.cellml import CellMLValidationError
from sbml2cellml.cellml2sbml import CellML2SBMLConversionError, convert_cellml2sbml
from sbml2cellml.sbml import SBMLValidationError
from sbml2cellml.sbml2cellml import SBML2CellMLConversionError, convert_sbml2cellml

#: errors reported with exit code 1 instead of a traceback
CONVERSION_ERRORS = (
    SBML2CellMLConversionError,
    CellML2SBMLConversionError,
    CellMLValidationError,
    SBMLValidationError,
    OSError,
)


def _build_parser(
    prog: str, description: str, input_help: str, output_help: str
) -> argparse.ArgumentParser:
    """Parser shared by both commands."""
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument("input", help=input_help)
    parser.add_argument("-o", "--output", help=output_help)
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="write the output even if the validation reports errors",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="log the conversion steps"
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser of the `sbml2cellml` command.

    Returns:
        The parser.
    """
    return _build_parser(
        prog="sbml2cellml",
        description="Convert an SBML model to CellML.",
        input_help="SBML file",
        output_help="CellML file, by default the input with the suffix .cellml",
    )


def build_parser_cellml2sbml() -> argparse.ArgumentParser:
    """Build the argument parser of the `cellml2sbml` command.

    Returns:
        The parser.
    """
    return _build_parser(
        prog="cellml2sbml",
        description="Convert a CellML model to SBML.",
        input_help="CellML file",
        output_help="SBML file, by default the input with the suffix .xml",
    )


def _run(
    parser: argparse.ArgumentParser,
    convert: Callable[..., Any],
    suffix: str,
    argv: list[str] | None,
) -> int:
    """Run a conversion command.

    Args:
        parser: parser of the command.
        convert: converter taking the input path, the output path and `validate`.
        suffix: suffix of the default output file.
        argv: arguments without the program name, `sys.argv[1:]` by default.

    Returns:
        0 on success, 1 on a missing input, a conversion, a validation or an
        I/O error.
    """
    args = parser.parse_args(argv)
    if args.verbose:
        log.enable_rich_logging(logging.INFO)

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"Input file does not exist: '{input_path}'", file=sys.stderr)
        return 1
    output_path = Path(args.output) if args.output else input_path.with_suffix(suffix)

    try:
        convert(input_path, output_path, not args.no_validate)
    except CONVERSION_ERRORS as err:
        print(str(err), file=sys.stderr)
        return 1

    print(output_path)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the `sbml2cellml` command.

    Args:
        argv: arguments without the program name, `sys.argv[1:]` by default.

    Returns:
        0 on success, 1 on a missing input, a conversion, a validation or an
        I/O error.
    """
    return _run(
        build_parser(),
        lambda sbml_path, cellml_path, validate: convert_sbml2cellml(
            sbml_path, cellml_path=cellml_path, validate=validate
        ),
        ".cellml",
        argv,
    )


def main_cellml2sbml(argv: list[str] | None = None) -> int:
    """Run the `cellml2sbml` command.

    Args:
        argv: arguments without the program name, `sys.argv[1:]` by default.

    Returns:
        0 on success, 1 on a missing input, a conversion, a validation or an
        I/O error.
    """
    return _run(
        build_parser_cellml2sbml(),
        lambda cellml_path, sbml_path, validate: convert_cellml2sbml(
            cellml_path, sbml_path=sbml_path, validate=validate
        ),
        ".xml",
        argv,
    )


if __name__ == "__main__":
    sys.exit(main())
