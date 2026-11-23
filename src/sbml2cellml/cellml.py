"""Reading, writing and validating CellML models with libcellml.

The functions wrap the libcellml `Parser`, `Printer`, `Validator` and
`Analyser`. Issues are returned instead of printed, so a caller decides what
to do with them; `errors` filters the issues of level `ERROR`.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import libcellml

#: name of every issue level of libcellml
LEVEL_NAMES: dict[int, str] = {
    libcellml.Issue.Level.ERROR: "ERROR",  # ty: ignore[unresolved-attribute]
    libcellml.Issue.Level.WARNING: "WARNING",  # ty: ignore[unresolved-attribute]
    libcellml.Issue.Level.MESSAGE: "MESSAGE",  # ty: ignore[unresolved-attribute]
}


class CellMLValidationError(ValueError):
    """A CellML model has issues of level ERROR."""


def _issues(logger: Any) -> list[libcellml.Issue]:
    """Issues collected by a libcellml logger (parser, validator, analyser)."""
    return [logger.issue(k) for k in range(logger.issueCount())]


def format_issue(issue: libcellml.Issue) -> str:
    """Format an issue as `[LEVEL] description`.

    Args:
        issue: issue of a libcellml logger.

    Returns:
        The one line description of the issue.
    """
    level = LEVEL_NAMES.get(issue.level(), str(issue.level()))
    return f"[{level}] {issue.description()}"


def format_issues(issues: list[libcellml.Issue]) -> str:
    """Format issues as one line per issue.

    Args:
        issues: issues of a libcellml logger.

    Returns:
        The formatted issues joined by newlines.
    """
    return "\n".join(format_issue(issue) for issue in issues)


def errors(issues: list[libcellml.Issue]) -> list[libcellml.Issue]:
    """The issues of level ERROR.

    Args:
        issues: issues of a libcellml logger.

    Returns:
        The subset of issues with level `ERROR`.
    """
    return [issue for issue in issues if issue.level() == libcellml.Issue.Level.ERROR]  # ty: ignore[unresolved-attribute]


def model_to_string(model: libcellml.Model) -> str:
    """Serialize a model to CellML 2.0.

    Args:
        model: CellML model.

    Returns:
        The CellML xml.
    """
    printer = libcellml.Printer()
    return printer.printModel(model)


def write_model(model: libcellml.Model, cellml_path: Path) -> None:
    """Write a model as CellML file.

    Args:
        model: CellML model.
        cellml_path: path of the file, overwritten if it exists.
    """
    Path(cellml_path).write_text(model_to_string(model), encoding="utf-8")


#: namespace of every version of CellML before 2.0, which the parser reads
#: in permissive mode only
CELLML_1_NAMESPACES: dict[str, str] = {
    "http://www.cellml.org/cellml/1.0#": "1.0",
    "http://www.cellml.org/cellml/1.1#": "1.1",
}


def cellml_version(text: str) -> str | None:
    """Version of CellML before 2.0 a document is written in.

    The models of the Physiome Model Repository are CellML 1.0 and 1.1
    documents, which libcellml reads in permissive mode (`strict` of the
    parser and the importer). The version is the namespace of the root
    element, so a namespace named in a comment or an annotation says
    nothing; a document which is no XML falls back to the namespaces it
    holds, so that the parser reports the problem.

    Args:
        text: the CellML document.

    Returns:
        `1.0` or `1.1` for a document with the namespace of that version,
        `None` for a CellML 2.0 document.
    """
    try:
        for _, element in ElementTree.iterparse(io.StringIO(text), events=("start",)):
            namespace = element.tag[1:].split("}", 1)[0] if "}" in element.tag else ""
            return CELLML_1_NAMESPACES.get(namespace)
    except ElementTree.ParseError:
        for namespace, version in CELLML_1_NAMESPACES.items():
            if namespace in text:
                return version
    return None


def read_model(cellml_path: Path, strict: bool = True) -> libcellml.Model:
    """Read a CellML file.

    Args:
        cellml_path: path of the CellML file.
        strict: parse CellML 2.0 only; a CellML 1.0 or 1.1 document needs
            `strict=False`, where the parser reads it as a 2.0 model.

    Returns:
        The parsed model.

    Raises:
        CellMLValidationError: if the parser reports errors.
    """
    parser = libcellml.Parser()
    parser.setStrict(strict)
    model = parser.parseModel(Path(cellml_path).read_text(encoding="utf-8"))
    parser_errors = errors(_issues(parser))
    if parser_errors:
        raise CellMLValidationError(
            f"CellML file '{cellml_path}' could not be parsed:\n"
            f"{format_issues(parser_errors)}"
        )
    return model


def validate_model(model: libcellml.Model) -> list[libcellml.Issue]:
    """Validate and analyse a model.

    The validator checks the model against the CellML specification, the
    analyser checks that the equations define every variable exactly once.

    Args:
        model: CellML model.

    Returns:
        The issues of the validator followed by the issues of the analyser,
        empty for a valid model.
    """
    validator = libcellml.Validator()
    validator.validateModel(model)
    issues = _issues(validator)

    analyser = libcellml.Analyser()
    analyser.analyseModel(model)
    issues.extend(_issues(analyser))
    return issues
