"""Reading, writing and validating SBML documents with libsbml.

The counterpart of `sbml2cellml.cellml` for the SBML side: errors are returned
as messages instead of printed, `SBMLValidationError` is raised by the callers
which want to stop on them.
"""

from pathlib import Path

import libsbml


class SBMLValidationError(ValueError):
    """An SBML document has errors."""


def _errors(doc: libsbml.SBMLDocument) -> list[str]:
    """Messages of severity error or fatal in the error log of a document."""
    log = doc.getErrorLog()
    messages: list[str] = []
    for k in range(log.getNumErrors()):
        error = log.getError(k)
        if error.getSeverity() >= libsbml.LIBSBML_SEV_ERROR:
            messages.append(
                f"[{error.getSeverityAsString()}] {error.getMessage().strip()}"
            )
    return messages


def document_to_string(doc: libsbml.SBMLDocument) -> str:
    """Serialize a document to SBML xml.

    Args:
        doc: SBML document.

    Returns:
        The SBML xml.
    """
    return libsbml.writeSBMLToString(doc)


def write_document(doc: libsbml.SBMLDocument, sbml_path: Path) -> None:
    """Write a document as SBML file.

    Args:
        doc: SBML document.
        sbml_path: path of the file, overwritten if it exists.
    """
    Path(sbml_path).write_text(document_to_string(doc), encoding="utf-8")


def read_document(sbml_path: Path) -> libsbml.SBMLDocument:
    """Read an SBML file.

    Args:
        sbml_path: path of the SBML file.

    Returns:
        The document.

    Raises:
        SBMLValidationError: if the file cannot be read or has no model.
    """
    doc: libsbml.SBMLDocument = libsbml.readSBMLFromFile(str(sbml_path))
    errors = _errors(doc)
    if errors or doc.getModel() is None:
        raise SBMLValidationError(
            f"SBML file '{sbml_path}' could not be read:\n" + "\n".join(errors)
        )
    return doc


def validate_document(doc: libsbml.SBMLDocument) -> list[str]:
    """Check the consistency of a document.

    Runs the libsbml consistency checks (units, identifiers, MathML, SBO,
    modeling practice). Unit problems are reported by libsbml as warnings and
    are not part of the result. The error log of the document is cleared
    before the check.

    Args:
        doc: SBML document.

    Returns:
        The messages of severity error or fatal, empty for a consistent document.
    """
    doc.getErrorLog().clearLog()
    doc.checkConsistency()
    return _errors(doc)
