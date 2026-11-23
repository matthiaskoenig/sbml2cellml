"""The reader and the converter in rust (`crates/`, issue #68).

The rust crates read a CellML document and convert it to SBML without
libcellml and without libsbml, which the module `sbml2cellml._rust`
(`crates/python`, built into the wheel by maturin) makes available in the
process. It is the default engine of
`cellml2sbml.convert_cellml2sbml`: the conversion is faster than the one
through libcellml by two orders of magnitude, and it is the code which runs
in a browser next to sbmlsim-core.

What the rust converter does not do is left to libcellml by the caller: the
imports of a document (`has_imports`, which `cellml2sbml` flattens with
libcellml before it hands the document over), the metadata of the CellML
elements and the hierarchical conversion to the `comp` package of SBML.
"""

from __future__ import annotations

from sbml2cellml import _rust


class RustError(ValueError):
    """The rust reader or the rust converter refused a document."""


def convert_cellml_to_sbml(text: str) -> tuple[str, list[str]]:
    """Convert a CellML document to SBML level 3 version 2.

    Args:
        text: the CellML document, with its imports resolved.

    Returns:
        The SBML document and the warnings of the conversion.

    Raises:
        RustError: if the document cannot be read or converted.
    """
    try:
        return _rust.convert_cellml_to_sbml(text)
    except ValueError as err:
        raise RustError(str(err)) from err


def cellml_version(text: str) -> str:
    """The version of CellML a document is written in.

    Args:
        text: the CellML document.

    Returns:
        `"2.0"`, `"1.1"` or `"1.0"`.

    Raises:
        RustError: if the document is no CellML model.
    """
    try:
        return _rust.cellml_version(text)
    except ValueError as err:
        raise RustError(str(err)) from err


def has_imports(text: str) -> bool:
    """Whether a document imports a component or units.

    Args:
        text: the CellML document.

    Returns:
        `True` if the document has an import, which the conversion needs
        resolved.

    Raises:
        RustError: if the document is no CellML model.
    """
    try:
        return _rust.has_imports(text)
    except ValueError as err:
        raise RustError(str(err)) from err
