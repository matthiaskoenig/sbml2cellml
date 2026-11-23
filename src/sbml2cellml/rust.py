"""The reader and the converter in rust (`crates/`, issue #68).

The rust crates convert a CellML document to SBML and an SBML document to
CellML without libcellml and without libsbml, which the module
`sbml2cellml._rust` (`crates/python`, built into the wheel by maturin) makes
available in the process. It is the default engine of
`cellml2sbml.convert_cellml2sbml` and of `sbml2cellml.convert_sbml2cellml`:
the conversion is faster than the one through libcellml by two orders of
magnitude, and it is the code which runs in a browser next to sbmlsim-core.

What the rust converter does not do is left to libcellml and libsbml by the
caller: the imports of a CellML document (`has_imports`, which `cellml2sbml`
flattens with libcellml before it hands the document over), the submodels of
a hierarchical SBML model (which `sbml2cellml` flattens with libsbml), the
metadata of the elements and the hierarchical conversion to the `comp`
package of SBML.
"""

from __future__ import annotations

from typing import Literal, get_args

from sbml2cellml import _rust

#: which converter writes the result of a conversion, `"rust"` for the
#: crates of this package, `"python"` for libsbml and libcellml and
#: `"auto"` for rust wherever it covers the conversion
Engine = Literal["auto", "rust", "python"]

#: the values of `Engine`, for the command line
ENGINES: tuple[str, ...] = get_args(Engine)


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


def convert_sbml_to_cellml(text: str, name: str) -> tuple[str, list[str]]:
    """Convert an SBML document to CellML 2.0.

    Args:
        text: the SBML document of any level and version, with the
            submodels of a hierarchical model flattened.
        name: the name of the CellML model when the SBML model has no id.

    Returns:
        The CellML document and the warnings of the conversion.

    Raises:
        RustError: if the document cannot be read or converted.
    """
    try:
        return _rust.convert_sbml_to_cellml(text, name)
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
