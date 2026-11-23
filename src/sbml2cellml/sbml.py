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


#: name of the SBML package for the hierarchical model composition
COMP_PACKAGE = "comp"


def flatten_comp(
    doc: libsbml.SBMLDocument, base_path: Path | None = None
) -> libsbml.SBMLDocument | None:
    """Flatten the submodels of a document which requires the `comp` package.

    The converters and the compiler of the simulator read one flat model, so
    a hierarchical model is flattened first: every element of a submodel
    becomes an element of the model, with the id of the submodel as prefix.
    The flattened document is written and read again, since the elements
    which libsbml takes from an external model definition keep parts of the
    document it loaded and freed for them (the history of an element of the
    glimepiride model, for instance).

    Args:
        doc: SBML document, flattened in place.
        base_path: directory the `source` of an external model definition is
            resolved from, the working directory when `None`.

    Returns:
        The flattened document, `None` when the document does not require
        the package.

    Raises:
        SBMLValidationError: if the package cannot be flattened.
    """
    if not doc.getPackageRequired(COMP_PACKAGE):
        return None
    properties = libsbml.ConversionProperties()
    properties.addOption("flatten comp", True)
    properties.addOption("leave ports", False)
    if base_path is not None:
        properties.addOption("basePath", str(base_path))
    if doc.convert(properties) != libsbml.LIBSBML_OPERATION_SUCCESS:
        raise SBMLValidationError(
            f"the comp package of the model cannot be flattened: {_errors(doc)}"
        )
    flat: libsbml.SBMLDocument = libsbml.readSBMLFromString(
        libsbml.writeSBMLToString(doc)
    )
    if flat.getModel() is None:
        raise SBMLValidationError(
            f"the flattened model cannot be read again: {_errors(flat)}"
        )
    return flat


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
