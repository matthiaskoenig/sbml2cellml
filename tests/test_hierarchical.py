"""Tests of the hierarchical conversion of a CellML model to SBML comp."""

from pathlib import Path
from typing import Any

import libsbml
import numpy as np
import pytest

from sbml2cellml import convert_sbml2cellml
from sbml2cellml.cellml import write_model
from sbml2cellml.cellml2sbml import (
    COMP_PACKAGE,
    build_document,
    build_hierarchical_document,
    convert_cellml2sbml,
)
from sbml2cellml.sbml import document_to_string, flatten_comp, validate_document
from tests.cellml_models import analyse, multi_component_model, reset_model
from tests.conftest import DATA_DIR
from tests.simulators import simulate_sbml


def hierarchical(model: Any) -> libsbml.SBMLDocument:
    """The hierarchical document of a CellML model."""
    return build_hierarchical_document(model, analyse(model), {})


def definitions(doc: libsbml.SBMLDocument) -> dict[str, Any]:
    """The model definitions of a document by their name."""
    plugin = doc.getPlugin(COMP_PACKAGE)
    return {
        plugin.getModelDefinition(k).getName(): plugin.getModelDefinition(k)
        for k in range(plugin.getNumModelDefinitions())
    }


def submodels(model: libsbml.Model) -> dict[str, str]:
    """The model reference of every submodel of a model by the submodel id."""
    plugin = model.getPlugin(COMP_PACKAGE)
    return {
        plugin.getSubmodel(k).getId(): plugin.getSubmodel(k).getModelRef()
        for k in range(plugin.getNumSubmodels())
    }


def test_a_component_becomes_a_model_definition() -> None:
    doc = hierarchical(multi_component_model())
    assert doc.getPackageRequired(COMP_PACKAGE)
    assert set(definitions(doc)) == {"environment", "cell", "child"}
    assert validate_document(doc) == []


def test_an_encapsulated_component_is_a_submodel_of_its_parent() -> None:
    doc = hierarchical(multi_component_model())
    model = doc.getModel()
    # environment and cell are submodels of the model, child one of cell
    assert set(submodels(model)) == {"environment", "cell"}
    cell = definitions(doc)["cell"]
    assert set(submodels(cell)) == {"child"}
    assert submodels(cell)["child"] == definitions(doc)["child"].getId()


def test_the_equations_stay_in_their_component() -> None:
    doc = hierarchical(multi_component_model())
    cell, child = definitions(doc)["cell"], definitions(doc)["child"]
    # cell: dx/dt and y = 2 x and c = 2 rate, child: dz/dt and x = z
    assert {cell.getRule(k).getVariable() for k in range(cell.getNumRules())} == {
        "x",
        "y",
    }
    assert {child.getRule(k).getVariable() for k in range(child.getNumRules())} == {
        "z",
        "x",
    }
    # c = 2 * rate of the computed constant and x = x0 of the initial value
    assert cell.getNumInitialAssignments() == 2


def test_a_connected_variable_is_replaced_by_a_parameter_of_the_model() -> None:
    doc = hierarchical(multi_component_model())
    model = doc.getModel()
    # k of the environment and rate of the cell are one variable, the
    # variable of integration is the time of the SBML model
    assert [model.getParameter(k).getId() for k in range(model.getNumParameters())] == [
        "k"
    ]
    parameter = model.getParameter("k")
    assert parameter.getValue() == pytest.approx(0.1)
    plugin = parameter.getPlugin(COMP_PACKAGE)
    replacements = {
        (
            plugin.getReplacedElement(k).getSubmodelRef(),
            plugin.getReplacedElement(k).getIdRef(),
        )
        for k in range(plugin.getNumReplacedElements())
    }
    assert replacements == {("environment", "k"), ("cell", "rate")}


def test_a_variable_of_one_component_stays_in_its_definition() -> None:
    doc = hierarchical(multi_component_model())
    # x0 is only used in the cell, so it is no parameter of the model
    assert doc.getModel().getParameter("x0") is None
    assert definitions(doc)["cell"].getParameter("x0").getValue() == pytest.approx(2.0)


def test_flattening_gives_the_model_of_the_flat_conversion() -> None:
    model = multi_component_model()
    doc = hierarchical(model)
    flat = build_document(model, analyse(model), {}).getModel()
    flat_doc = flatten_comp(doc)
    assert flat_doc is not None
    flattened = flat_doc.getModel()
    assert flattened.getNumParameters() == flat.getNumParameters()
    assert flattened.getNumRules() == flat.getNumRules()
    assert flattened.getNumInitialAssignments() == flat.getNumInitialAssignments()


def test_the_hierarchical_model_simulates_like_the_flat_one() -> None:
    model = multi_component_model()
    flat = document_to_string(build_document(model, analyse(model), {}))
    comp = document_to_string(hierarchical(model))
    expected = simulate_sbml(flat, ["cell_x", "y", "z", "child_x"], 0.0, 10.0, 10)
    values = simulate_sbml(
        comp,
        ["cell__x", "cell__y", "cell__child__z", "cell__child__x"],
        0.0,
        10.0,
        10,
    )
    assert np.allclose(values, expected, rtol=1e-9, atol=1e-12)


def test_a_reset_becomes_an_event_of_its_component() -> None:
    doc = hierarchical(reset_model())
    definition = next(iter(definitions(doc).values()))
    # the resets of the component fire together and become one event
    assert definition.getNumEvents() == 1
    assert definition.getEvent(0).getNumEventAssignments() == 2
    assert validate_document(doc) == []


def test_a_model_of_one_component_has_one_submodel(tmp_path: Path) -> None:
    doc = convert_cellml2sbml(
        DATA_DIR / "decay_cellml_1_0.cellml",
        sbml_path=tmp_path / "decay.xml",
        hierarchical=True,
    )
    assert set(submodels(doc.getModel())) == {"main"}
    # nothing is connected, so the model itself has no parameter
    assert doc.getModel().getNumParameters() == 0
    assert definitions(doc)["main"].getNumParameters() == 2
    assert validate_document(doc) == []


def test_sbml2cellml_flattens_a_hierarchical_model(tmp_path: Path) -> None:
    model = multi_component_model()
    write_model(model, tmp_path / "multi.cellml")
    convert_cellml2sbml(
        tmp_path / "multi.cellml", sbml_path=tmp_path / "multi.xml", hierarchical=True
    )
    back = convert_sbml2cellml(
        tmp_path / "multi.xml", cellml_path=tmp_path / "back.cellml"
    )
    names = {
        back.component(0).variable(k).name()
        for k in range(back.component(0).variableCount())
    }
    assert {"cell__x", "cell__child__z", "cell__y", "k"} <= names
