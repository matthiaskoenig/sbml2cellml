"""Tests of the SBML to CellML conversion."""

import logging
import math
from pathlib import Path

import libcellml
import libsbml
import pytest

from sbml2cellml import convert_sbml2cellml
from sbml2cellml.cellml import CellMLValidationError, errors, read_model, validate_model
from sbml2cellml.sbml2cellml import COMPONENT_ID, TIME_ID, SBML2CellMLConversionError
from tests.conftest import GLIMEPIRIDE_MODELS, MODELS_DIR
from tests.sbml_models import delay_model, simple_model, write_sbml


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
    # time, the compartments, parameters and species, and the reactions whose
    # id a formula uses as its rate
    sbml_ids = {TIME_ID} | {
        element.getId()
        for listing in (
            m_sbml.getListOfCompartments(),
            m_sbml.getListOfParameters(),
            m_sbml.getListOfSpecies(),
        )
        for element in listing
    }
    reaction_ids = {reaction.getId() for reaction in m_sbml.getListOfReactions()}
    names = set(variables(model))
    assert sbml_ids <= names
    assert names - sbml_ids <= reaction_ids

    # the written file parses back without issues
    assert cellml_path.is_file()
    read_model(cellml_path)


@pytest.mark.parametrize("name", GLIMEPIRIDE_MODELS)
def test_convert_glimepiride_valid(name: str) -> None:
    """The models have a complete unit annotation and units on numbers."""
    model = convert_sbml2cellml(MODELS_DIR / f"{name}.xml", validate=False)
    assert errors(validate_model(model)) == []
    component = model.component(COMPONENT_ID)
    units = {
        component.variable(k).units().name() for k in range(component.variableCount())
    }
    assert "dimensionless" in units and len(units) > 5


def test_convert_delay_invalid(tmp_path: Path) -> None:
    """Known conversion gap, see docs/conversion-issues.md: CellML has no delay."""
    path = write_sbml(tmp_path / "delay.xml", delay_model())
    model = convert_sbml2cellml(path, validate=False)
    assert errors(validate_model(model))


def test_validate_raises_for_invalid_model(tmp_path: Path) -> None:
    path = write_sbml(tmp_path / "delay.xml", delay_model())
    with pytest.raises(CellMLValidationError):
        convert_sbml2cellml(path, validate=True)


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


def test_time_and_avogadro_convert_to_valid_cellml(tmp_path: Path) -> None:
    """A kinetic law with the time and avogadro symbols passes libcellml."""
    model_sbml = simple_model("symbols")
    law: libsbml.KineticLaw = model_sbml.getReaction("r1").getKineticLaw()
    law.setMath(libsbml.parseL3Formula("k1 * S1 * time / avogadro"))
    sbml_path = write_sbml(tmp_path / "symbols.xml", model_sbml)
    model = convert_sbml2cellml(sbml_path)
    assert errors(validate_model(model)) == []


def _with_local_parameters(model_sbml: libsbml.Model) -> libsbml.Model:
    """Kinetic laws `k * S1` (r1, local k = 0.5) and `k * S2` (r2, local k = 2)."""
    r1: libsbml.Reaction = model_sbml.getReaction("r1")
    r1.getKineticLaw().setMath(libsbml.parseL3Formula("k * S1"))
    local: libsbml.LocalParameter = r1.getKineticLaw().createLocalParameter()
    local.setId("k")
    local.setValue(0.5)
    r2: libsbml.Reaction = model_sbml.createReaction()
    r2.setId("r2")
    r2.setReversible(False)
    reactant: libsbml.SpeciesReference = r2.createReactant()
    reactant.setSpecies("S2")
    reactant.setConstant(True)
    reactant.setStoichiometry(1.0)
    product: libsbml.SpeciesReference = r2.createProduct()
    product.setSpecies("S1")
    product.setConstant(True)
    product.setStoichiometry(1.0)
    law: libsbml.KineticLaw = r2.createKineticLaw()
    law.setMath(libsbml.parseL3Formula("k * S2"))
    local = law.createLocalParameter()
    local.setId("k")
    local.setValue(2.0)
    return model_sbml


def test_local_parameters_become_variables_per_reaction(tmp_path: Path) -> None:
    """Local parameters of the same id in two reactions keep their values."""
    model_sbml = _with_local_parameters(simple_model("locals"))
    sbml_path = write_sbml(tmp_path / "locals.xml", model_sbml)
    model = convert_sbml2cellml(sbml_path)
    assert errors(validate_model(model)) == []
    v = variables(model)
    assert float(v["r1_k"].initialValue()) == 0.5
    assert float(v["r2_k"].initialValue()) == 2.0
    assert "<ci>k</ci>" not in model.component(0).math().replace(" ", "")


def test_local_parameter_shadows_global_parameter(tmp_path: Path) -> None:
    model_sbml = simple_model("shadow")
    law: libsbml.KineticLaw = model_sbml.getReaction("r1").getKineticLaw()
    local: libsbml.LocalParameter = law.createLocalParameter()
    local.setId("k1")  # the law k1 * S1 means the local k1
    local.setValue(3.0)
    sbml_path = write_sbml(tmp_path / "shadow.xml", model_sbml)
    model = convert_sbml2cellml(sbml_path)
    v = variables(model)
    assert float(v["k1"].initialValue()) == 0.5
    assert float(v["r1_k1"].initialValue()) == 3.0
    math = model.component(0).math().replace(" ", "")
    assert "<ci>r1_k1</ci>" in math
    assert "<ci>k1</ci>" not in math


def test_local_parameter_id_avoids_existing_ids(tmp_path: Path) -> None:
    model_sbml = _with_local_parameters(simple_model("collision"))
    taken: libsbml.Parameter = model_sbml.createParameter()
    taken.setId("r1_k")
    taken.setValue(9.0)
    taken.setConstant(True)
    sbml_path = write_sbml(tmp_path / "collision.xml", model_sbml)
    model = convert_sbml2cellml(sbml_path)
    assert errors(validate_model(model)) == []
    v = variables(model)
    assert float(v["r1_k"].initialValue()) == 9.0
    assert float(v["r1_k_2"].initialValue()) == 0.5


def _with_rule(model_sbml: libsbml.Model, variable: str, formula: str) -> None:
    """Add a non-constant parameter (if missing) set by an assignment rule."""
    if model_sbml.getElementBySId(variable) is None:
        p: libsbml.Parameter = model_sbml.createParameter()
        p.setId(variable)
        p.setConstant(False)
    rule: libsbml.AssignmentRule = model_sbml.createAssignmentRule()
    rule.setVariable(variable)
    rule.setMath(libsbml.parseL3Formula(formula))


def test_species_reference_id_is_a_variable_of_its_stoichiometry(
    tmp_path: Path,
) -> None:
    model_sbml = simple_model("reference_id")
    reference: libsbml.SpeciesReference = model_sbml.getReaction("r1").getReactant(0)
    reference.setId("s1ref")
    reference.setStoichiometry(2.0)
    _with_rule(model_sbml, "p", "s1ref + s1ref")
    sbml_path = write_sbml(tmp_path / "reference_id.xml", model_sbml)
    model = convert_sbml2cellml(sbml_path)
    assert errors(validate_model(model)) == []
    assert float(variables(model)["s1ref"].initialValue()) == 2.0


def test_assigned_stoichiometry_has_no_initial_value(tmp_path: Path) -> None:
    model_sbml = simple_model("assigned_stoichiometry")
    reference: libsbml.SpeciesReference = model_sbml.getReaction("r1").getReactant(0)
    reference.setId("s1ref")
    reference.setConstant(False)
    reference.setStoichiometry(2.0)
    _with_rule(model_sbml, "s1ref", "k1 + k1")
    sbml_path = write_sbml(tmp_path / "assigned_stoichiometry.xml", model_sbml)
    model = convert_sbml2cellml(sbml_path)
    assert errors(validate_model(model)) == []
    assert variables(model)["s1ref"].initialValue() == ""


def test_reaction_id_in_a_formula_is_the_rate(tmp_path: Path) -> None:
    model_sbml = simple_model("reaction_id")
    _with_rule(model_sbml, "flux", "r1")
    sbml_path = write_sbml(tmp_path / "reaction_id.xml", model_sbml)
    model = convert_sbml2cellml(sbml_path)
    assert errors(validate_model(model)) == []
    assert "r1" in variables(model)


def test_model_without_differential_equations_has_no_time(tmp_path: Path) -> None:
    """CellML knows the variable of integration only from a differential
    equation; an algebraic model without one would have `time` of unknown type."""
    doc = libsbml.SBMLDocument(3, 2)
    model_sbml: libsbml.Model = doc.createModel()
    model_sbml.setId("algebraic")
    k: libsbml.Parameter = model_sbml.createParameter()
    k.setId("k")
    k.setValue(2.0)
    k.setConstant(True)
    _with_rule(model_sbml, "p", "k + k")
    sbml_path = write_sbml(tmp_path / "algebraic.xml", model_sbml)
    model = convert_sbml2cellml(sbml_path)
    assert errors(validate_model(model)) == []
    assert TIME_ID not in variables(model)


def test_initial_assignments_give_initial_values(tmp_path: Path) -> None:
    """libsbml evaluates the initial assignments to initial values."""
    model_sbml = simple_model("initial_assignments")
    for symbol, formula in (("k1", "2 * 0.75"), ("S1", "k1 * 4")):
        ia: libsbml.InitialAssignment = model_sbml.createInitialAssignment()
        ia.setSymbol(symbol)
        ia.setMath(libsbml.parseL3Formula(formula))
    sbml_path = write_sbml(tmp_path / "initial_assignments.xml", model_sbml)
    v = variables(convert_sbml2cellml(sbml_path))
    assert float(v["k1"].initialValue()) == 1.5
    assert float(v["S1"].initialValue()) == 6.0


def _model_with_initial_assignment_and_rate_rule(name: str, rate: str) -> libsbml.Model:
    """x = 5 at the start with dx/dt = rate, p = 1 / x and q = 2 * x at the start."""
    model_sbml = simple_model(name)
    for pid in ("x", "p", "q"):
        parameter: libsbml.Parameter = model_sbml.createParameter()
        parameter.setId(pid)
        parameter.setConstant(False)
    for symbol, formula in (("x", "5"), ("q", "2 * x")):
        ia: libsbml.InitialAssignment = model_sbml.createInitialAssignment()
        ia.setSymbol(symbol)
        ia.setMath(libsbml.parseL3Formula(formula))
    rate_rule: libsbml.RateRule = model_sbml.createRateRule()
    rate_rule.setVariable("x")
    rate_rule.setMath(libsbml.parseL3Formula(rate))
    rule: libsbml.AssignmentRule = model_sbml.createAssignmentRule()
    rule.setVariable("p")
    rule.setMath(libsbml.parseL3Formula("1 / x"))
    return model_sbml


def test_initial_assignment_of_a_rate_rule_target(tmp_path: Path) -> None:
    """libsbml takes the rate of x for its value: q = 2 * 3 instead of 2 * 5."""
    model_sbml = _model_with_initial_assignment_and_rate_rule("rate_target", "3")
    sbml_path = write_sbml(tmp_path / "rate_target.xml", model_sbml)
    model = convert_sbml2cellml(sbml_path)
    v = variables(model)
    assert float(v["x"].initialValue()) == 5.0
    assert float(v["q"].initialValue()) == 10.0
    # the rate rule is still converted
    assert "<diff/>" in model.component(0).math()


def test_initial_assignment_of_a_rate_rule_target_in_its_rate(tmp_path: Path) -> None:
    """libsbml crashes: it evaluates the rate p = 1 / x of x for the value of x."""
    model_sbml = _model_with_initial_assignment_and_rate_rule("rate_cycle", "p")
    sbml_path = write_sbml(tmp_path / "rate_cycle.xml", model_sbml)
    v = variables(convert_sbml2cellml(sbml_path))
    assert float(v["x"].initialValue()) == 5.0
    assert float(v["q"].initialValue()) == 10.0


def test_initial_assignments_with_recursive_functions_are_not_expanded(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """libsbml crashes on expanding them with a recursive function present."""
    model_sbml = _model_calling({"f": "lambda(x, f(x))"})
    ia: libsbml.InitialAssignment = model_sbml.createInitialAssignment()
    ia.setSymbol("k1")
    ia.setMath(libsbml.parseL3Formula("2 * 3"))
    sbml_path = write_sbml(tmp_path / "calls.xml", model_sbml)
    with caplog.at_level(logging.WARNING, logger="sbml2cellml"):
        convert_sbml2cellml(sbml_path, validate=False)
    assert "Initial assignments of 'calls' could not be expanded" in caplog.text
    assert "InitialAssignment for 'k1' not converted" in caplog.text


def test_non_finite_initial_values_become_equations(tmp_path: Path) -> None:
    """CellML initial values are real numbers: INF and NaN become equations."""
    model_sbml = simple_model("non_finite")
    for pid in ("P", "Q", "R"):
        p: libsbml.Parameter = model_sbml.createParameter()
        p.setId(pid)
        p.setConstant(True)
    # values, and an initial assignment libsbml evaluates
    model_sbml.getParameter("Q").setValue(-math.inf)
    model_sbml.getParameter("R").setValue(math.nan)
    for symbol, formula in (("P", "INF"),):
        ia: libsbml.InitialAssignment = model_sbml.createInitialAssignment()
        ia.setSymbol(symbol)
        ia.setMath(libsbml.parseL3Formula(formula))
    sbml_path = write_sbml(tmp_path / "non_finite.xml", model_sbml)
    model = convert_sbml2cellml(sbml_path)
    assert errors(validate_model(model)) == []
    v = variables(model)
    assert [v[pid].initialValue() for pid in ("P", "Q", "R")] == ["", "", ""]
    math_text = model.component(0).math()
    assert math_text.count("<infinity/>") == 2
    assert "<notanumber/>" in math_text


def test_initial_assignment_to_nan_is_not_evaluated(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """libsbml does not evaluate an initial assignment to NaN; it stays."""
    model_sbml = simple_model("nan_assignment")
    ia: libsbml.InitialAssignment = model_sbml.createInitialAssignment()
    ia.setSymbol("k1")
    ia.setMath(libsbml.parseL3Formula("NaN"))
    sbml_path = write_sbml(tmp_path / "nan_assignment.xml", model_sbml)
    with caplog.at_level(logging.WARNING, logger="sbml2cellml"):
        convert_sbml2cellml(sbml_path, validate=False)
    assert "Initial assignments of 'nan_assignment' could not be expanded (1 of 1)" in (
        caplog.text
    )
    assert "InitialAssignment for 'k1' not converted" in caplog.text


def test_boundary_species_has_no_reaction_terms(tmp_path: Path) -> None:
    model_sbml = simple_model("boundary")
    model_sbml.getSpecies("S1").setBoundaryCondition(True)
    sbml_path = write_sbml(tmp_path / "boundary.xml", model_sbml)
    model = convert_sbml2cellml(sbml_path)
    math_text = model.component(0).math().replace(" ", "").replace("\n", "")
    # only S2 gets a differential equation
    assert math_text.count("<diff/>") == 1
    assert "<bvar><ci>time</ci></bvar><ci>S2</ci>" in math_text


def test_elements_without_math_have_no_effect(tmp_path: Path) -> None:
    """SBML L3V2 allows rules and kinetic laws without math."""
    model_sbml = simple_model("no_math")
    for pid in ("p", "q"):
        parameter: libsbml.Parameter = model_sbml.createParameter()
        parameter.setId(pid)
        parameter.setValue(3.0)
        parameter.setConstant(False)
    model_sbml.createAssignmentRule().setVariable("p")
    model_sbml.createRateRule().setVariable("q")
    model_sbml.removeReaction(0)
    reaction: libsbml.Reaction = model_sbml.createReaction()
    reaction.setId("r2")
    reaction.setReversible(False)
    reactant: libsbml.SpeciesReference = reaction.createReactant()
    reactant.setSpecies("S1")
    reactant.setConstant(True)
    reactant.setStoichiometry(1.0)
    reaction.createKineticLaw()
    sbml_path = write_sbml(tmp_path / "no_math.xml", model_sbml)
    model = convert_sbml2cellml(sbml_path)
    assert errors(validate_model(model)) == []
    v = variables(model)
    assert float(v["p"].initialValue()) == 3.0
    assert float(v["q"].initialValue()) == 3.0
    assert "<diff/>" not in model.component(0).math()


def test_rate_of_in_an_initial_assignment_is_evaluated(tmp_path: Path) -> None:
    """p = rateOf(S1) at the start: -k1 [S1] / cell = -0.5 * 10 / 2."""
    model_sbml = simple_model("initial_rate")
    p: libsbml.Parameter = model_sbml.createParameter()
    p.setId("p")
    p.setConstant(True)
    ia: libsbml.InitialAssignment = model_sbml.createInitialAssignment()
    ia.setSymbol("p")
    ia.setMath(libsbml.parseL3Formula("rateOf(S1)"))
    sbml_path = write_sbml(tmp_path / "initial_rate.xml", model_sbml)
    v = variables(convert_sbml2cellml(sbml_path))
    assert float(v["p"].initialValue()) == -2.5


def test_rate_of_its_own_equation_is_not_converted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """dx/dt = rateOf(x) has no right-hand side to insert."""
    model_sbml = simple_model("cycle")
    x: libsbml.Parameter = model_sbml.createParameter()
    x.setId("x")
    x.setValue(1.0)
    x.setConstant(False)
    rule: libsbml.RateRule = model_sbml.createRateRule()
    rule.setVariable("x")
    rule.setMath(libsbml.parseL3Formula("rateOf(x)"))
    sbml_path = write_sbml(tmp_path / "cycle.xml", model_sbml)
    with caplog.at_level(logging.WARNING, logger="sbml2cellml"):
        convert_sbml2cellml(sbml_path, validate=False)
    assert "rateOf(x) not converted, the rate of 'x' depends on itself" in caplog.text


def test_rate_of_an_assignment_rule_target_is_not_converted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    model_sbml = simple_model("assigned_rate")
    _with_rule(model_sbml, "p", "k1 * S1")
    _with_rule(model_sbml, "q", "rateOf(p)")
    sbml_path = write_sbml(tmp_path / "assigned_rate.xml", model_sbml)
    with caplog.at_level(logging.WARNING, logger="sbml2cellml"):
        convert_sbml2cellml(sbml_path, validate=False)
    assert "rateOf(p) not converted, 'p' is computed by a rule" in caplog.text


def _algebraic_rule(model_sbml: libsbml.Model, formula: str) -> None:
    rule: libsbml.AlgebraicRule = model_sbml.createAlgebraicRule()
    rule.setMath(libsbml.parseL3Formula(formula))


def _parameter(
    model_sbml: libsbml.Model, pid: str, value: float, constant: bool
) -> None:
    parameter: libsbml.Parameter = model_sbml.createParameter()
    parameter.setId(pid)
    parameter.setValue(value)
    parameter.setConstant(constant)


def test_algebraic_rule_determines_its_free_variable(tmp_path: Path) -> None:
    """0 = x + y + S1 - 20: x is free, y constant, S1 changed by the reaction."""
    model_sbml = simple_model("algebraic_rule")
    _parameter(model_sbml, "x", 1.0, constant=False)
    _parameter(model_sbml, "y", 2.0, constant=True)
    _algebraic_rule(model_sbml, "x + y + S1 - 20")
    sbml_path = write_sbml(tmp_path / "algebraic_rule.xml", model_sbml)
    model = convert_sbml2cellml(sbml_path)
    assert errors(validate_model(model)) == []
    v = variables(model)
    # x has the solution at the start (20 - 2 - 10) as guess of the solver;
    # libcellml takes any other variable with an initial value for the unknown
    # too, so the constant of the rule is stated as the equation y = 2
    assert float(v["x"].initialValue()) == 8.0
    assert v["y"].initialValue() == ""
    assert float(v["S1"].initialValue()) == 10.0  # a state keeps its value
    assert float(v["k1"].initialValue()) == 0.5  # not in the rule


def test_algebraic_rules_are_matched_with_their_variables(tmp_path: Path) -> None:
    """0 = a + b - 3 could determine a or b, 0 = a - 1 only a."""
    model_sbml = simple_model("matching")
    _parameter(model_sbml, "a", 0.0, constant=False)
    _parameter(model_sbml, "b", 0.0, constant=False)
    _algebraic_rule(model_sbml, "a + b - 3")
    _algebraic_rule(model_sbml, "a - 1")
    sbml_path = write_sbml(tmp_path / "matching.xml", model_sbml)
    model = convert_sbml2cellml(sbml_path)
    assert errors(validate_model(model)) == []
    v = variables(model)
    # a is the unknown of the second rule and used by the first: no guess
    assert v["a"].initialValue() == ""
    assert float(v["b"].initialValue()) == 2.0  # solved at the start: 3 - 1


def test_algebraic_rule_is_solved_at_the_start(tmp_path: Path) -> None:
    """The solution is the guess of the solver and the size of the compartment
    which converts the initial values of its species."""
    model_sbml = simple_model("solved")
    cell: libsbml.Compartment = model_sbml.getCompartment("cell")
    cell.unsetSize()
    cell.setConstant(False)
    _algebraic_rule(model_sbml, "cell - 2.5")
    _parameter(model_sbml, "x", 1.0, constant=False)
    _algebraic_rule(model_sbml, "x * x - 9")
    s1: libsbml.Species = model_sbml.getSpecies("S1")
    s1.unsetInitialConcentration()
    s1.setInitialAmount(6.0)  # a concentration variable: 6 / 2.5
    sbml_path = write_sbml(tmp_path / "solved.xml", model_sbml)
    model = convert_sbml2cellml(sbml_path)
    assert errors(validate_model(model)) == []
    v = variables(model)
    assert float(v["cell"].initialValue()) == 2.5
    assert float(v["S1"].initialValue()) == pytest.approx(2.4)
    assert float(v["x"].initialValue()) == pytest.approx(3.0)


@pytest.mark.parametrize("rate", ["3", "-x"])
def test_algebraic_rule_with_a_rate_rule_target_without_value(
    rate: str, tmp_path: Path
) -> None:
    """libsbml takes the rate of x for its unknown value: y = 3, a crash for -x."""
    model_sbml = simple_model("unknown_state")
    _parameter(model_sbml, "x", math.nan, constant=False)
    _parameter(model_sbml, "y", 1.0, constant=False)
    rule: libsbml.RateRule = model_sbml.createRateRule()
    rule.setVariable("x")
    rule.setMath(libsbml.parseL3Formula(rate))
    _algebraic_rule(model_sbml, "y - x")
    sbml_path = write_sbml(tmp_path / "unknown_state.xml", model_sbml)
    v = variables(convert_sbml2cellml(sbml_path, validate=False))
    # not solved at the start: y keeps its value
    assert float(v["y"].initialValue()) == 1.0


def test_algebraic_rule_without_a_free_variable_logs_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    model_sbml = simple_model("overdetermined")
    _algebraic_rule(model_sbml, "k1 - 0.5")  # k1 is constant
    sbml_path = write_sbml(tmp_path / "overdetermined.xml", model_sbml)
    with caplog.at_level(logging.WARNING, logger="sbml2cellml"):
        model = convert_sbml2cellml(sbml_path)
    assert "AlgebraicRule 'k1 - 0.5' not converted, it determines no variable" in (
        caplog.text
    )
    assert float(variables(model)["k1"].initialValue()) == 0.5


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


def test_event_logs_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    model_sbml = simple_model("events")
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
