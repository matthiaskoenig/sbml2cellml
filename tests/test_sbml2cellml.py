"""Tests of the SBML to CellML conversion."""

import logging
from pathlib import Path

import libcellml
import libsbml
import pytest

from sbml2cellml import convert_sbml2cellml
from sbml2cellml.cellml import CellMLValidationError, errors, read_model, validate_model
from sbml2cellml.sbml2cellml import COMPONENT_ID, TIME_ID, SBML2CellMLConversionError
from tests.conftest import GLIMEPIRIDE_MODELS, MODELS_DIR

#: models the current converter renders as valid CellML
VALID_MODELS = ["glimepiride_kidney", "glimepiride_liver"]
#: models with known conversion gaps, see docs/roadmap.md
INVALID_MODELS = {
    "glimepiride_intestine": "function definition and units on numbers",
    "glimepiride_body": "units on numbers in formulas",
    "glimepiride_body_flat": "units on numbers in formulas",
}
#: libsbml frees a model when its document is garbage collected; keep every
#: document created by `simple_model` alive for the life of the test module.
_SBML_DOCUMENTS: list[libsbml.SBMLDocument] = []


def write_sbml(path: Path, model: libsbml.Model) -> Path:
    """Write the document of a model."""
    doc = model.getSBMLDocument()
    libsbml.writeSBMLToFile(doc, str(path))
    return path


def simple_model(mid: str = "simple") -> libsbml.Model:
    """SBML L3V2 model with one compartment, one parameter and two species.

    S1 is in concentration, S2 in amount, one reaction S1 -> S2 with `k1 * S1`.
    """
    doc = libsbml.SBMLDocument(3, 2)
    model: libsbml.Model = doc.createModel()
    model.setId(mid)
    c: libsbml.Compartment = model.createCompartment()
    c.setId("cell")
    c.setSize(2.0)
    c.setConstant(True)
    p: libsbml.Parameter = model.createParameter()
    p.setId("k1")
    p.setValue(0.5)
    p.setConstant(True)
    s1: libsbml.Species = model.createSpecies()
    s1.setId("S1")
    s1.setCompartment("cell")
    s1.setInitialConcentration(10.0)
    s1.setHasOnlySubstanceUnits(False)
    s1.setBoundaryCondition(False)
    s1.setConstant(False)
    s2: libsbml.Species = model.createSpecies()
    s2.setId("S2")
    s2.setCompartment("cell")
    s2.setInitialAmount(4.0)
    s2.setHasOnlySubstanceUnits(True)
    s2.setBoundaryCondition(False)
    s2.setConstant(False)
    r: libsbml.Reaction = model.createReaction()
    r.setId("r1")
    r.setReversible(False)
    reactant: libsbml.SpeciesReference = r.createReactant()
    reactant.setSpecies("S1")
    reactant.setConstant(True)
    reactant.setStoichiometry(1.0)
    product: libsbml.SpeciesReference = r.createProduct()
    product.setSpecies("S2")
    product.setConstant(True)
    product.setStoichiometry(1.0)
    klaw: libsbml.KineticLaw = r.createKineticLaw()
    klaw.setMath(libsbml.parseL3Formula("k1 * S1"))
    _SBML_DOCUMENTS.append(doc)
    return model


def variables(model: libcellml.Model) -> dict[str, libcellml.Variable]:
    component = model.component(0)
    return {
        component.variable(k).name(): component.variable(k)
        for k in range(component.variableCount())
    }


@pytest.mark.parametrize("name", GLIMEPIRIDE_MODELS)
def test_convert_glimepiride_structure(name: str, tmp_path: Path) -> None:
    sbml_path = MODELS_DIR / f"{name}.xml"
    cellml_path = tmp_path / f"{name}.cellml"
    model = convert_sbml2cellml(sbml_path, cellml_path=cellml_path, validate=False)

    assert model.componentCount() == 1
    assert model.component(0).name() == COMPONENT_ID

    doc = libsbml.readSBMLFromFile(str(sbml_path))
    m_sbml = doc.getModel()
    n_expected = (
        m_sbml.getNumCompartments()
        + m_sbml.getNumParameters()
        + m_sbml.getNumSpecies()
        + 1
    )
    assert model.component(0).variableCount() == n_expected
    assert TIME_ID in variables(model)

    # the written file parses back without issues
    assert cellml_path.is_file()
    read_model(cellml_path)


@pytest.mark.parametrize("name", VALID_MODELS)
def test_convert_glimepiride_valid(name: str) -> None:
    model = convert_sbml2cellml(MODELS_DIR / f"{name}.xml", validate=False)
    assert errors(validate_model(model)) == []


@pytest.mark.parametrize("name", list(INVALID_MODELS))
def test_convert_glimepiride_invalid(name: str) -> None:
    """Known conversion gaps, remove the model from INVALID_MODELS once fixed."""
    model = convert_sbml2cellml(MODELS_DIR / f"{name}.xml", validate=False)
    assert errors(validate_model(model)), INVALID_MODELS[name]


def test_validate_raises_for_invalid_model() -> None:
    with pytest.raises(CellMLValidationError):
        convert_sbml2cellml(MODELS_DIR / "glimepiride_body.xml", validate=True)


def test_validate_passes_for_valid_model(tmp_path: Path) -> None:
    cellml_path = tmp_path / "liver.cellml"
    convert_sbml2cellml(
        MODELS_DIR / "glimepiride_liver.xml", cellml_path=cellml_path, validate=True
    )
    assert cellml_path.is_file()


def test_missing_model_raises(tmp_path: Path) -> None:
    path = tmp_path / "empty.xml"
    path.write_text(
        '<?xml version="1.0"?><sbml xmlns="http://www.sbml.org/sbml/level3/version2/core" level="3" version="2"/>'
    )
    with pytest.raises(SBML2CellMLConversionError, match="No model"):
        convert_sbml2cellml(path)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(SBML2CellMLConversionError, match="does not exist"):
        convert_sbml2cellml(tmp_path / "does_not_exist.xml")


def test_simple_model_initial_values(tmp_path: Path) -> None:
    sbml_path = write_sbml(tmp_path / "simple.xml", simple_model())
    model = convert_sbml2cellml(sbml_path)
    v = variables(model)
    assert model.name() == "simple"
    assert set(v) == {TIME_ID, "cell", "k1", "S1", "S2"}
    assert float(v["cell"].initialValue()) == 2.0
    assert float(v["k1"].initialValue()) == 0.5
    # concentration stays concentration, amount stays amount
    assert float(v["S1"].initialValue()) == 10.0
    assert float(v["S2"].initialValue()) == 4.0
    # the reaction term of a concentration species is scaled by the compartment
    math = model.component(0).math()
    assert "<diff/>" in math
    assert 'cellml:units="dimensionless"' in math


def test_amount_given_for_concentration_species(tmp_path: Path) -> None:
    model_sbml = simple_model("amounts")
    s1: libsbml.Species = model_sbml.getSpecies("S1")
    s1.unsetInitialConcentration()
    s1.setInitialAmount(6.0)  # concentration species, amount given: 6 / 2
    sbml_path = write_sbml(tmp_path / "amounts.xml", model_sbml)
    v = variables(convert_sbml2cellml(sbml_path))
    assert float(v["S1"].initialValue()) == 3.0


def test_nan_initial_value_logs_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    model_sbml = simple_model("nan")
    p: libsbml.Parameter = model_sbml.createParameter()
    p.setId("k_undefined")
    p.setConstant(True)
    sbml_path = write_sbml(tmp_path / "nan.xml", model_sbml)
    with caplog.at_level(logging.WARNING, logger="sbml2cellml"):
        v = variables(convert_sbml2cellml(sbml_path))
    assert float(v["k_undefined"].initialValue()) == 1.0
    assert "k_undefined" in caplog.text


def test_event_and_initial_assignment_log_warnings(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    model_sbml = simple_model("events")
    ia: libsbml.InitialAssignment = model_sbml.createInitialAssignment()
    ia.setSymbol("k1")
    ia.setMath(libsbml.parseL3Formula("2 * 0.5"))
    event: libsbml.Event = model_sbml.createEvent()
    event.setId("e1")
    event.setUseValuesFromTriggerTime(True)
    trigger: libsbml.Trigger = event.createTrigger()
    trigger.setMath(libsbml.parseL3Formula("time > 10"))
    trigger.setPersistent(True)
    trigger.setInitialValue(True)
    ea: libsbml.EventAssignment = event.createEventAssignment()
    ea.setVariable("k1")
    ea.setMath(libsbml.parseL3Formula("1.0"))
    sbml_path = write_sbml(tmp_path / "events.xml", model_sbml)
    with caplog.at_level(logging.WARNING, logger="sbml2cellml"):
        convert_sbml2cellml(sbml_path, validate=False)
    assert "Event 'e1'" in caplog.text
    assert "InitialAssignment for 'k1'" in caplog.text
