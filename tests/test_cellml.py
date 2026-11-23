"""Tests of the libcellml helpers."""

from pathlib import Path

import libcellml
import pytest

from sbml2cellml.cellml import (
    CellMLValidationError,
    cellml_version,
    errors,
    format_issue,
    model_to_string,
    read_model,
    validate_model,
    write_model,
)
from tests.conftest import DATA_DIR, TEST_MODEL_PATH


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


def test_cellml_version_of_a_2_0_model() -> None:
    assert cellml_version(TEST_MODEL_PATH.read_text(encoding="utf-8")) is None


@pytest.mark.parametrize("version", ["1.0", "1.1"])
def test_cellml_version_of_an_older_model(version: str) -> None:
    text = f'<model xmlns="http://www.cellml.org/cellml/{version}#" name="m"/>'
    assert cellml_version(text) == version


def test_cellml_version_ignores_a_namespace_outside_the_root() -> None:
    text = (
        '<model xmlns="http://www.cellml.org/cellml/2.0#" name="m">'
        "<!-- http://www.cellml.org/cellml/1.1# --></model>"
    )
    assert cellml_version(text) is None


def test_cellml_version_of_a_document_which_is_no_xml() -> None:
    assert cellml_version("broken http://www.cellml.org/cellml/1.1#") == "1.1"


def test_read_a_cellml_1_0_model_needs_the_permissive_parser() -> None:
    path = DATA_DIR / "decay_cellml_1_0.cellml"
    with pytest.raises(CellMLValidationError, match="strict parsing mode"):
        read_model(path)
    model = read_model(path, strict=False)
    assert model.name() == "decay"
    assert model.componentCount() == 1


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
