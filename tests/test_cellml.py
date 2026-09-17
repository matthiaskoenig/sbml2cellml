"""Tests of the libcellml helpers."""

from pathlib import Path

import libcellml
import pytest

from sbml2cellml.cellml import (
    CellMLValidationError,
    errors,
    format_issue,
    model_to_string,
    read_model,
    validate_model,
    write_model,
)
from tests.conftest import TEST_MODEL_PATH


def invalid_model() -> libcellml.Model:
    """Model whose math references a variable which does not exist."""
    model = libcellml.Model("invalid")
    component = libcellml.Component("c")
    component.setMath(
        '<math xmlns="http://www.w3.org/1998/Math/MathML">'
        "<apply><eq/><ci>x</ci><ci>y</ci></apply></math>"
    )
    model.addComponent(component)
    return model


def test_read_model() -> None:
    model = read_model(TEST_MODEL_PATH)
    assert model.name() == "test_model"
    assert model.componentCount() == 1
    assert model.component(0).variableCount() == 3


def test_read_model_raises_on_invalid_xml(tmp_path: Path) -> None:
    path = tmp_path / "broken.cellml"
    path.write_text("<model this is not xml")
    with pytest.raises(CellMLValidationError):
        read_model(path)


def test_write_and_read_roundtrip(tmp_path: Path) -> None:
    model = read_model(TEST_MODEL_PATH)
    path = tmp_path / "test_model.cellml"
    write_model(model, path)
    assert path.is_file()
    assert model_to_string(read_model(path)) == model_to_string(model)


def test_validate_valid_model_has_no_issues() -> None:
    model = read_model(TEST_MODEL_PATH)
    assert validate_model(model) == []


def test_validate_invalid_model_has_errors() -> None:
    issues = validate_model(invalid_model())
    assert issues
    assert errors(issues)
    description = format_issue(errors(issues)[0])
    assert description.startswith("[ERROR]")
    assert "'x'" in description or "x" in description
