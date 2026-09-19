"""Tests of the CellML to SBML conversion."""

from pathlib import Path
from typing import Any

import libcellml
import libsbml
import pytest

from sbml2cellml import cellml2sbml, convert_cellml2sbml
from sbml2cellml.cellml import write_model
from sbml2cellml.cellml2sbml import CellML2SBMLConversionError, build_document
from sbml2cellml.sbml import SBMLValidationError, validate_document
from tests.cellml_models import (
    analyse,
    assignment,
    cn,
    math,
    math_model,
    multi_component_model,
    nla_model,
    reset_model,
    variable,
)
from tests.conftest import TEST_MODEL_PATH

DATA_DIR = Path(__file__).parent / "data"


def parameters(model: libsbml.Model) -> dict[str, libsbml.Parameter]:
    return {p.getId(): p for p in model.getListOfParameters()}


def rules(model: libsbml.Model) -> dict[str, libsbml.Rule]:
    return {r.getVariable(): r for r in model.getListOfRules()}


def initial_assignments(model: libsbml.Model) -> dict[str, str]:
    return {
        ia.getSymbol(): libsbml.formulaToL3String(ia.getMath())
        for ia in model.getListOfInitialAssignments()
    }


def test_convert_test_model(tmp_path: Path) -> None:
    sbml_path = tmp_path / "test_model.xml"
    doc = convert_cellml2sbml(TEST_MODEL_PATH, sbml_path=sbml_path)
    model = doc.getModel()
    assert doc.getLevel() == 3
    assert doc.getVersion() == 2
    assert model.getId() == "test_model"
    assert model.getTimeUnits() == "second"
    assert model.getNumCompartments() == 0
    assert model.getNumSpecies() == 0
    p = parameters(model)
    assert set(p) == {"m", "alpha"}
    assert p["alpha"].getConstant() and p["alpha"].getValue() == 0.05
    assert p["alpha"].getUnits() == "per_second"
    assert not p["m"].getConstant() and p["m"].getValue() == 10.0
    assert p["m"].getUnits() == "kilogram"
    r = rules(model)
    assert set(r) == {"m"}
    assert r["m"].isRate()
    assert libsbml.formulaToL3String(r["m"].getMath()) == "-alpha * m"
    assert model.getUnitDefinition("per_second") is not None
    assert validate_document(doc) == []
    assert sbml_path.is_file()
    assert libsbml.readSBMLFromFile(str(sbml_path)).getModel().getId() == "test_model"


def test_convert_multi_component_model(tmp_path: Path) -> None:
    cellml_path = tmp_path / "multi.cellml"
    write_model(multi_component_model(), cellml_path)
    doc = convert_cellml2sbml(cellml_path)
    model = doc.getModel()
    assert model.getTimeUnits() == "second"
    p = parameters(model)
    assert set(p) == {"k", "cell_x", "x0", "y", "c", "kc", "z", "child_x"}
    # constants
    assert (
        p["k"].getConstant()
        and p["k"].getValue() == 0.1
        and p["k"].getUnits() == "per_second"
    )
    assert (
        p["x0"].getConstant()
        and p["x0"].getValue() == 2.0
        and p["x0"].getUnits() == "mM"
    )
    assert p["kc"].getConstant() and p["kc"].getValue() == 0.5
    # computed constant: constant parameter with an initial assignment
    assert p["c"].getConstant() and not p["c"].isSetValue()
    # states
    assert not p["cell_x"].getConstant() and not p["cell_x"].isSetValue()
    assert p["cell_x"].getName() == "x"
    assert not p["z"].getConstant() and p["z"].getValue() == 1.0
    # algebraic
    assert not p["y"].getConstant() and not p["y"].isSetValue()
    assert not p["child_x"].getConstant()
    ia = initial_assignments(model)
    assert ia == {"cell_x": "x0", "c": "2 * k"}
    r = rules(model)
    assert set(r) == {"cell_x", "z", "y", "child_x"}
    assert r["cell_x"].isRate()
    assert libsbml.formulaToL3String(r["cell_x"].getMath()) == "-k * cell_x"
    assert r["z"].isRate()
    assert r["y"].isAssignment()
    assert libsbml.formulaToL3String(r["y"].getMath()) == "2 * cell_x"
    assert libsbml.formulaToL3String(r["child_x"].getMath()) == "z"
    assert validate_document(doc) == []


def test_convert_reset_model(tmp_path: Path) -> None:
    cellml_path = tmp_path / "reset.cellml"
    write_model(reset_model(), cellml_path)
    doc = convert_cellml2sbml(cellml_path)
    model = doc.getModel()
    assert model.getNumEvents() == 2

    # count is only ever written by the second reset, so it must not be
    # constant even though the analyser types it CONSTANT
    p = parameters(model)
    assert not p["count"].getConstant()
    assert p["count"].getValue() == 0.0

    event = model.getEvent(0)
    assert event.getId() == "reset_1"
    assert event.getUseValuesFromTriggerTime()
    trigger = event.getTrigger()
    assert trigger.getPersistent() and trigger.getInitialValue()
    assert libsbml.formulaToL3String(trigger.getMath()) == "m == m_div"
    assert libsbml.formulaToL3String(event.getPriority().getMath()) == "-0"
    assert event.getNumEventAssignments() == 1
    assignment = event.getEventAssignment(0)
    assert assignment.getVariable() == "m"
    assert libsbml.formulaToL3String(assignment.getMath()) == "m / 2 dimensionless"

    count_event = model.getEvent(1)
    assert count_event.getId() == "reset_2"
    assert count_event.getNumEventAssignments() == 1
    count_assignment = count_event.getEventAssignment(0)
    assert count_assignment.getVariable() == "count"
    assert (
        libsbml.formulaToL3String(count_assignment.getMath())
        == "count + 1 dimensionless"
    )
    assert validate_document(doc) == []


def test_reset_target_on_connected_copy_is_not_constant() -> None:
    """A reset may be declared on a connected copy of a variable living in
    another component; the parameter of the representative must still be
    made non-constant (the reset target is keyed by SBML id, not by
    (component, variable) name)."""
    model = reset_model()
    environment = model.component("environment")
    count = environment.variable("count")
    m = environment.variable("m")

    counter = libcellml.Component("counter")
    model.addComponent(counter)
    count_c = variable(counter, "count_c", "dimensionless", interface="public")
    m_c = variable(counter, "m_c", "kilogram", interface="public")

    count.setInterfaceType("public")
    m.setInterfaceType("public")
    libcellml.Variable.addEquivalence(count, count_c)
    libcellml.Variable.addEquivalence(m, m_c)

    reset = libcellml.Reset()
    reset.setOrder(2)
    reset.setVariable(count_c)
    reset.setTestVariable(m_c)
    reset.setTestValue(math(assignment("m_c", cn("7", "kilogram"))))
    reset.setResetValue(
        math(assignment("count_c", f"<apply><plus/><ci>count_c</ci>{cn('1')}</apply>"))
    )
    counter.addReset(reset)

    doc = build_document(model, analyse(model))
    p = parameters(doc.getModel())
    assert not p["count"].getConstant()
    assert validate_document(doc) == []


def test_convert_nla_model_raises(tmp_path: Path) -> None:
    cellml_path = tmp_path / "nla.cellml"
    write_model(nla_model(), cellml_path)
    with pytest.raises(
        CellML2SBMLConversionError, match="cannot be analysed"
    ) as excinfo:
        convert_cellml2sbml(cellml_path)
    assert "x" in str(excinfo.value) and "y" in str(excinfo.value)


def test_convert_dae_model_has_an_algebraic_rule(tmp_path: Path) -> None:
    """An implicit equation becomes the algebraic rule `0 = left - right`."""
    cellml_path = tmp_path / "dae.cellml"
    model = math_model({"a": "<ci>x</ci>"})
    # with an initial value (the guess of the solver) `a = x` is implicit
    model.component("main").variable("a").setInitialValue(1.0)
    write_model(model, cellml_path)
    doc = convert_cellml2sbml(cellml_path)
    model_sbml: libsbml.Model = doc.getModel()
    rules = [r for r in model_sbml.getListOfRules() if r.isAlgebraic()]
    assert [libsbml.formulaToL3String(r.getMath()) for r in rules] == ["a - x"]
    a: libsbml.Parameter = model_sbml.getParameter("a")
    assert a.getConstant() is False and a.getValue() == 1.0
    assert model_sbml.getRuleByVariable("x").isRate()
    assert validate_document(doc) == []


def test_convert_with_imports() -> None:
    doc = convert_cellml2sbml(DATA_DIR / "import_parent.cellml")
    model = doc.getModel()
    p = parameters(model)
    assert set(p) == {"m", "k"}
    assert rules(model)["m"].isRate()
    assert model.getUnitDefinition("per_second") is not None
    assert validate_document(doc) == []


def test_convert_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CellML2SBMLConversionError, match="does not exist"):
        convert_cellml2sbml(tmp_path / "missing.cellml")


def test_convert_invalid_cellml_raises(tmp_path: Path) -> None:
    path = tmp_path / "invalid.cellml"
    path.write_text(
        '<?xml version="1.0"?><model xmlns="http://www.cellml.org/cellml/2.0#" name="bad">'
        '<component name="c"><variable name="x" units="second"/>'
        '<math xmlns="http://www.w3.org/1998/Math/MathML"><apply><eq/><ci>x</ci><ci>y</ci></apply></math>'
        "</component></model>"
    )
    with pytest.raises(CellML2SBMLConversionError, match="analysed"):
        convert_cellml2sbml(path)


def test_convert_model_id_avoids_variable_collision() -> None:
    model = reset_model()
    model.setName("m")
    doc = build_document(model, analyse(model))
    assert validate_document(doc) == []
    model_sbml = doc.getModel()
    assert model_sbml.getId() == "m_2"
    p = parameters(model_sbml)
    assert "m" in p


def test_build_document_is_consistent_and_detects_injected_error() -> None:
    model = reset_model()
    doc = build_document(model, analyse(model))
    assert validate_document(doc) == []
    # an assignment rule on the constant alpha makes the document inconsistent
    rule = doc.getModel().createAssignmentRule()
    rule.setVariable("alpha")
    rule.setMath(libsbml.parseL3Formula("1"))
    assert validate_document(doc)


def test_validate_raises_on_inconsistent_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`convert_cellml2sbml` raises `SBMLValidationError` on an inconsistent
    document when `validate` is set, but `validate=False` still writes it."""
    path = tmp_path / "test_model.cellml"
    path.write_text(TEST_MODEL_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    real_build_document = cellml2sbml.build_document

    def inconsistent_build_document(
        model: libcellml.Model, analyser_model: Any
    ) -> libsbml.SBMLDocument:
        doc = real_build_document(model, analyser_model)
        rule = doc.getModel().createAssignmentRule()
        rule.setVariable("alpha")
        rule.setMath(libsbml.parseL3Formula("1"))
        return doc

    monkeypatch.setattr(cellml2sbml, "build_document", inconsistent_build_document)

    with pytest.raises(SBMLValidationError):
        convert_cellml2sbml(path)

    out = tmp_path / "out.xml"
    convert_cellml2sbml(path, sbml_path=out, validate=False)
    assert out.is_file()
