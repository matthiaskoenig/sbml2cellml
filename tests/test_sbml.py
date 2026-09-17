"""Tests of the libsbml helpers."""

from pathlib import Path

import libsbml
import pytest

from sbml2cellml.sbml import (
    SBMLValidationError,
    document_to_string,
    read_document,
    validate_document,
    write_document,
)
from tests.conftest import MODELS_DIR


def parameter_document() -> libsbml.SBMLDocument:
    doc = libsbml.SBMLDocument(3, 2)
    model = doc.createModel()
    model.setId("m")
    p = model.createParameter()
    p.setId("k")
    p.setValue(1.0)
    p.setConstant(True)
    p.setUnits("dimensionless")
    return doc


def test_read_document() -> None:
    doc = read_document(MODELS_DIR / "glimepiride_liver.xml")
    assert doc.getModel() is not None
    assert doc.getModel().getNumSpecies() > 0


def test_read_document_raises_on_broken_xml(tmp_path: Path) -> None:
    path = tmp_path / "broken.xml"
    path.write_text("<sbml this is not xml")
    with pytest.raises(SBMLValidationError):
        read_document(path)


def test_write_and_read_roundtrip(tmp_path: Path) -> None:
    doc = parameter_document()
    path = tmp_path / "m.xml"
    write_document(doc, path)
    assert document_to_string(read_document(path)) == document_to_string(doc)


def test_validate_consistent_document() -> None:
    assert validate_document(parameter_document()) == []


def test_validate_inconsistent_document() -> None:
    doc = parameter_document()
    rule = doc.getModel().createAssignmentRule()
    rule.setVariable("k")  # k is constant, an assignment rule on it is an error
    rule.setMath(libsbml.parseL3Formula("2"))
    errors = validate_document(doc)
    assert errors
    assert errors[0].startswith("[Error]") or errors[0].startswith("[ERROR]")
