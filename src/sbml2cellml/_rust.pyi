"""Type stubs of the rust module `sbml2cellml._rust` (`crates/python`)."""

def convert_cellml_to_sbml(text: str) -> tuple[str, list[str]]:
    """Convert a CellML document to SBML level 3 version 2.

    Args:
        text: the CellML document.

    Returns:
        The SBML document and what the conversion is told about.

    Raises:
        ValueError: if the document cannot be read or converted.
    """

def convert_sbml_to_cellml(text: str, name: str) -> tuple[str, list[str]]:
    """Convert an SBML document to CellML 2.0.

    Args:
        text: the SBML document.
        name: the name of the CellML model when the SBML model has no id.

    Returns:
        The CellML document and what the conversion is told about.

    Raises:
        ValueError: if the document cannot be read or converted.
    """

def cellml_version(text: str) -> str:
    """The version of CellML a document is written in.

    Args:
        text: the CellML document.

    Returns:
        `"2.0"`, `"1.1"` or `"1.0"`.

    Raises:
        ValueError: if the document is no CellML model.
    """

def has_imports(text: str) -> bool:
    """Whether a document imports a component or units.

    Args:
        text: the CellML document.

    Returns:
        `True` if the document has an import, which the conversion needs
        resolved.

    Raises:
        ValueError: if the document is no CellML model.
    """
