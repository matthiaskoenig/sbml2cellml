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
from tests.sbml_models import simple_model, write_sbml

#: models the current converter renders as valid CellML
VALID_MODELS = ["glimepiride_kidney", "glimepiride_liver"]
#: models with known conversion gaps, see docs/roadmap.md
INVALID_MODELS = {
    "glimepiride_intestine": "SBML units on numbers and reaction ids in formulas",
    "glimepiride_body": "SBML units on numbers and reaction ids in formulas",
    "glimepiride_body_flat": "SBML units on numbers and reaction ids in formulas",
}


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


def _model_with_assignment_rules() -> libsbml.Model:
    """`simple_model` with a valued parameter and an unset species set by rules."""
    model_sbml = simple_model("rules")
    k2: libsbml.Parameter = model_sbml.createParameter()
    k2.setId("k2")
    k2.setValue(3.0)
    k2.setConstant(False)
    s3: libsbml.Species = model_sbml.createSpecies()
    s3.setId("S3")
    s3.setCompartment("cell")
    s3.setHasOnlySubstanceUnits(False)
    s3.setBoundaryCondition(False)
    s3.setConstant(False)
    for variable, formula in (("k2", "k1 + k1"), ("S3", "k1 * S1")):
        rule: libsbml.AssignmentRule = model_sbml.createAssignmentRule()
        rule.setVariable(variable)
        rule.setMath(libsbml.parseL3Formula(formula))
    return model_sbml


def test_assignment_rule_targets_have_no_initial_value(tmp_path: Path) -> None:
    """The rule defines the target at all times, including the start."""
    sbml_path = write_sbml(tmp_path / "rules.xml", _model_with_assignment_rules())
    v = variables(convert_sbml2cellml(sbml_path))
    assert v["k2"].initialValue() == ""
    assert v["S3"].initialValue() == ""
    # the other variables keep theirs
    assert float(v["k1"].initialValue()) == 0.5
    assert float(v["S1"].initialValue()) == 10.0


def test_unset_assignment_rule_target_logs_no_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    sbml_path = write_sbml(tmp_path / "rules.xml", _model_with_assignment_rules())
    with caplog.at_level(logging.WARNING, logger="sbml2cellml"):
        convert_sbml2cellml(sbml_path)
    assert "S3" not in caplog.text


def test_assigned_compartment_without_size_converts_with_one(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The initial amount of a species needs the size of its compartment."""
    model_sbml = simple_model("assigned_size")
    cell: libsbml.Compartment = model_sbml.getCompartment("cell")
    cell.unsetSize()
    cell.setConstant(False)
    rule: libsbml.AssignmentRule = model_sbml.createAssignmentRule()
    rule.setVariable("cell")
    rule.setMath(libsbml.parseL3Formula("k1 + k1"))
    s2: libsbml.Species = model_sbml.getSpecies("S2")
    s2.unsetInitialAmount()
    s2.setInitialConcentration(4.0)  # amount species, concentration given
    sbml_path = write_sbml(tmp_path / "assigned_size.xml", model_sbml)
    with caplog.at_level(logging.WARNING, logger="sbml2cellml"):
        v = variables(convert_sbml2cellml(sbml_path, validate=False))
    assert v["cell"].initialValue() == ""
    assert float(v["S2"].initialValue()) == 4.0
    assert "Size of compartment 'cell' is not set" in caplog.text


def test_numbers_without_units_convert_to_valid_cellml(tmp_path: Path) -> None:
    """Integer, rational and e-notation numbers in formulas pass libcellml."""
    model_sbml = simple_model("numbers")
    law: libsbml.KineticLaw = model_sbml.getReaction("r1").getKineticLaw()
    law.setMath(libsbml.parseL3Formula("2 * k1 * S1 * (3/4) + 1e-3"))
    sbml_path = write_sbml(tmp_path / "numbers.xml", model_sbml)
    model = convert_sbml2cellml(sbml_path)
    assert errors(validate_model(model)) == []


def _model_with_function_definition() -> libsbml.Model:
    """`simple_model` whose kinetic law calls `multiply(x, y) = x * y`."""
    model_sbml = simple_model("functions")
    fd: libsbml.FunctionDefinition = model_sbml.createFunctionDefinition()
    fd.setId("multiply")
    fd.setMath(libsbml.parseL3Formula("lambda(x, y, x * y)"))
    law: libsbml.KineticLaw = model_sbml.getReaction("r1").getKineticLaw()
    law.setMath(libsbml.parseL3Formula("multiply(k1, S1)"))
    return model_sbml


def test_function_definitions_are_inlined(tmp_path: Path) -> None:
    """CellML has no functions, a call becomes the body of the function."""
    sbml_path = write_sbml(
        tmp_path / "functions.xml", _model_with_function_definition()
    )
    model = convert_sbml2cellml(sbml_path)
    assert errors(validate_model(model)) == []
    math = model.component(0).math()
    assert "multiply" not in math
    assert "<times/>" in math


def _model_calling(functions: dict[str, str]) -> libsbml.Model:
    """`simple_model` with the given function definitions, the law calls `f`."""
    model_sbml = simple_model("calls")
    for fid, body in functions.items():
        fd: libsbml.FunctionDefinition = model_sbml.createFunctionDefinition()
        fd.setId(fid)
        fd.setMath(libsbml.parseL3Formula(body))
    law: libsbml.KineticLaw = model_sbml.getReaction("r1").getKineticLaw()
    law.setMath(libsbml.parseL3Formula("f(k1)"))
    return model_sbml


@pytest.mark.parametrize(
    ("functions", "recursive"),
    [
        ({"f": "lambda(x, f(x))"}, "f"),
        ({"f": "lambda(x, g(x))", "g": "lambda(x, f(x))"}, "f, g"),
    ],
)
def test_recursive_function_definitions_are_not_expanded(
    functions: dict[str, str],
    recursive: str,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """libsbml crashes on expanding a recursive function read from a file."""
    sbml_path = write_sbml(tmp_path / "calls.xml", _model_calling(functions))
    with caplog.at_level(logging.WARNING, logger="sbml2cellml"):
        model = convert_sbml2cellml(sbml_path, validate=False)
    assert (
        f"Function definitions of 'calls' could not be expanded, their calls "
        f"remain: recursive function definitions {recursive}" in caplog.text
    )
    assert "<ci>f</ci>" in model.component(0).math().replace(" ", "")


def test_function_definitions_libsbml_refuses_log_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A call of an undefined function makes libsbml refuse the document."""
    sbml_path = write_sbml(
        tmp_path / "calls.xml", _model_calling({"f": "lambda(x, g(x))"})
    )
    with caplog.at_level(logging.WARNING, logger="sbml2cellml"):
        convert_sbml2cellml(sbml_path, validate=False)
    assert "Function definitions of 'calls' could not be expanded" in caplog.text
    assert "invalid" in caplog.text


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
