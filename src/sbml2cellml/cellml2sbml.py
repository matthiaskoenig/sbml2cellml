"""Conversion of CellML 2.0 models to SBML level 3 version 2.

The libcellml analyser classifies the variables and equations of the model
and resolves the connections between components; the converter renders its
model as SBML: every variable is a parameter, states get rate rules,
algebraic variables assignment rules, computed constants initial assignments,
and the resets of the components become events. CellML units become unit
definitions. There are no compartments, species or reactions.
"""

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import libcellml
import libsbml

from sbml2cellml import cellml, sbml
from sbml2cellml.sbml import SBMLValidationError
from sbml2cellml.sbmlmath import (
    MathConversionError,
    ast_to_sbml,
    mathml_to_sbml,
    variable_node,
)
from sbml2cellml.units import UnitsConversionError, add_units, unit_id
from sbml2cellml.variables import VariableIds, sanitize_id

logger = logging.getLogger(__name__)

AstType = libcellml.AnalyserEquationAst.Type  # ty: ignore[unresolved-attribute]
EquationType = libcellml.AnalyserEquation.Type  # ty: ignore[unresolved-attribute]
VariableType = libcellml.AnalyserVariable.Type  # ty: ignore[unresolved-attribute]
ModelType = libcellml.AnalyserModel.Type  # ty: ignore[unresolved-attribute]


class CellML2SBMLConversionError(ValueError):
    """The CellML model cannot be converted."""


def convert_cellml2sbml(
    cellml_path: Path, sbml_path: Path | None = None, validate: bool = True
) -> libsbml.SBMLDocument:
    """Convert a CellML file to an SBML document.

    Args:
        cellml_path: path of the CellML file; imports are resolved relative to it.
        sbml_path: path the SBML is written to, not written if `None`.
        validate: check the consistency of the document with libsbml and raise
            if it has errors.

    Returns:
        The SBML document.

    Raises:
        CellML2SBMLConversionError: if the file does not exist, the imports
            cannot be resolved, the analyser reports errors, the model is not
            an ODE or algebraic model, or a construct is not supported.
        CellMLValidationError: if the file cannot be parsed.
        SBMLValidationError: if `validate` is set and the document has errors.
    """
    cellml_path = Path(cellml_path)
    if not cellml_path.is_file():
        raise CellML2SBMLConversionError(
            f"CellML file does not exist: '{cellml_path}'."
        )
    model = cellml.read_model(cellml_path)
    logger.info("Converting CellML model '%s' from '%s'", model.name(), cellml_path)
    model = _flatten(model, cellml_path.parent)
    analyser_model = _analyse(model)
    try:
        doc = build_document(model, analyser_model)
    except (MathConversionError, UnitsConversionError, KeyError) as err:
        raise CellML2SBMLConversionError(
            f"CellML model '{model.name()}' cannot be converted: {err}"
        ) from err

    if validate:
        errors = sbml.validate_document(doc)
        if errors:
            raise SBMLValidationError(
                f"SBML document converted from '{cellml_path}' has "
                f"{len(errors)} errors:\n" + "\n".join(errors)
            )
    if sbml_path is not None:
        sbml.write_document(doc, sbml_path)
        logger.info("SBML written to '%s'", sbml_path)
    return doc


def _flatten(model: libcellml.Model, base_path: Path) -> libcellml.Model:
    """Resolve the imports of a model and flatten it, if it has any."""
    if not model.hasImports():
        return model
    importer = libcellml.Importer()
    importer.resolveImports(model, str(base_path))
    issues = [importer.issue(k) for k in range(importer.issueCount())]
    errors = cellml.errors(issues)
    if errors or model.hasUnresolvedImports():
        raise CellML2SBMLConversionError(
            f"Imports of CellML model '{model.name()}' cannot be resolved from "
            f"'{base_path}':\n{cellml.format_issues(errors)}"
        )
    flat = importer.flattenModel(model)
    logger.info("Resolved and flattened the imports of '%s'", model.name())
    return flat


def _analyse(model: libcellml.Model) -> Any:
    """Analyse a model, raising on errors and unsupported model types."""
    analyser = libcellml.Analyser()
    analyser.analyseModel(model)
    issues = [analyser.issue(k) for k in range(analyser.issueCount())]
    errors = cellml.errors(issues)
    if errors:
        raise CellML2SBMLConversionError(
            f"CellML model '{model.name()}' cannot be analysed:\n"
            f"{cellml.format_issues(errors)}"
        )
    analyser_model = analyser.model()
    model_type = analyser_model.type()
    if model_type not in (ModelType.ODE, ModelType.ALGEBRAIC):
        type_name = libcellml.AnalyserModel.typeAsString(model_type)
        raise CellML2SBMLConversionError(
            f"CellML model '{model.name()}' is of type '{type_name}', only ODE "
            f"and algebraic models are supported."
        )
    return analyser_model


def build_document(model: libcellml.Model, analyser_model: Any) -> libsbml.SBMLDocument:
    """Build the SBML document of an analysed CellML model.

    Args:
        model: the (flattened) CellML model.
        analyser_model: its analyser model without errors.

    Returns:
        The SBML document, not validated.

    Raises:
        MathConversionError, UnitsConversionError, KeyError: for constructs
            which cannot be converted; `convert_cellml2sbml` wraps them.
    """
    doc = libsbml.SBMLDocument(3, 2)
    model_sbml: libsbml.Model = doc.createModel()
    name = model.name() or "model"
    model_sbml.setId(sanitize_id(name))
    model_sbml.setName(name)

    unit_ids = add_units(model, model_sbml)
    ids = VariableIds(analyser_model)

    voi = analyser_model.voi()
    if voi is not None:
        model_sbml.setTimeUnits(unit_id(voi.variable().units().name(), unit_ids))

    for k in range(analyser_model.stateCount()):
        _add_parameter(
            model_sbml, analyser_model.state(k), ids, unit_ids, constant=False
        )
    for k in range(analyser_model.variableCount()):
        variable = analyser_model.variable(k)
        variable_type = variable.type()
        if variable_type == VariableType.EXTERNAL:
            raise MathConversionError(
                f"External variable '{variable.variable().name()}' is not supported."
            )
        constant = variable_type in (
            VariableType.CONSTANT,
            VariableType.COMPUTED_CONSTANT,
        )
        _add_parameter(model_sbml, variable, ids, unit_ids, constant=constant)

    for k in range(analyser_model.equationCount()):
        _add_equation(model_sbml, analyser_model.equation(k), ids)

    _add_events(model_sbml, model, ids)
    return doc


def _add_parameter(
    model_sbml: libsbml.Model,
    analyser_variable: Any,
    ids: VariableIds,
    unit_ids: dict[str, str],
    constant: bool,
) -> None:
    """Add the parameter of a variable, with its value or initial assignment."""
    variable = analyser_variable.variable()
    sid = ids.id_for(variable)
    parameter: libsbml.Parameter = model_sbml.createParameter()
    parameter.setId(sid)
    parameter.setConstant(constant)
    parameter.setUnits(unit_id(variable.units().name(), unit_ids))
    if sid != variable.name():
        parameter.setName(variable.name())
    logger.info("'%s' parameter for variable '%s'", sid, variable.name())

    initialising = analyser_variable.initialisingVariable()
    if initialising is None or not initialising.initialValue():
        return
    initial = initialising.initialValue()
    try:
        parameter.setValue(float(initial))
    except ValueError:
        # the initial value is the name of another variable of the same component
        reference = ids.lookup(initialising.parent().name(), initial)
        assignment: libsbml.InitialAssignment = model_sbml.createInitialAssignment()
        assignment.setSymbol(sid)
        node = libsbml.ASTNode(libsbml.AST_NAME)
        node.setName(reference)
        assignment.setMath(node)
        logger.info("%s initialised from '%s'", sid, reference)


def _add_equation(model_sbml: libsbml.Model, equation: Any, ids: VariableIds) -> None:
    """Add the rule or initial assignment of an equation."""
    equation_type = equation.type()
    type_name = libcellml.AnalyserEquation.typeAsString(equation_type)
    names = [
        equation.variable(k).variable().name() for k in range(equation.variableCount())
    ]
    if equation_type in (EquationType.NLA, EquationType.EXTERNAL):
        raise MathConversionError(
            f"Equation of type '{type_name}' for {names} is not supported."
        )
    ast = equation.ast()
    if ast.type() != AstType.EQUALITY:
        raise MathConversionError(f"Equation for {names} is not an equality.")
    left, right = ast.leftChild(), ast.rightChild()
    rhs = ast_to_sbml(right, ids)

    if equation_type == EquationType.ODE:
        state = left.rightChild() if left.type() == AstType.DIFF else None
        if state is None or state.type() != AstType.CI:
            raise MathConversionError(
                f"ODE for {names} does not start with a derivative."
            )
        sid = ids.id_for(state.variable())
        rule: libsbml.Rule = model_sbml.createRateRule()
        rule.setVariable(sid)
        rule.setMath(rhs)
        logger.info("d%s/dt = %s", sid, libsbml.formulaToL3String(rhs))
        return

    if left.type() != AstType.CI:
        raise MathConversionError(
            f"Equation of type '{type_name}' for {names} is implicit, only "
            f"'variable = expression' is supported."
        )
    sid = ids.id_for(left.variable())
    if equation_type in (
        EquationType.TRUE_CONSTANT,
        EquationType.VARIABLE_BASED_CONSTANT,
    ):
        assignment: libsbml.InitialAssignment = model_sbml.createInitialAssignment()
        assignment.setSymbol(sid)
        assignment.setMath(rhs)
        logger.info("%s = %s (initial assignment)", sid, libsbml.formulaToL3String(rhs))
    elif equation_type == EquationType.ALGEBRAIC:
        rule = model_sbml.createAssignmentRule()
        rule.setVariable(sid)
        rule.setMath(rhs)
        logger.info("%s = %s", sid, libsbml.formulaToL3String(rhs))
    else:
        raise MathConversionError(
            f"Equation of type '{type_name}' for {names} is not supported."
        )


def _components(parent: Any) -> Iterator[Any]:
    """The components of a model or component, recursively (encapsulation)."""
    for k in range(parent.componentCount()):
        component = parent.component(k)
        yield component
        yield from _components(component)


def _add_events(
    model_sbml: libsbml.Model, model: libcellml.Model, ids: VariableIds
) -> None:
    """Add an event per reset of every component."""
    index = 0
    for component in _components(model):
        for k in range(component.resetCount()):
            index += 1
            _add_reset(model_sbml, component, component.reset(k), index, ids)


def _add_reset(
    model_sbml: libsbml.Model, component: Any, reset: Any, index: int, ids: VariableIds
) -> None:
    """Add the event of a reset.

    The trigger is the equality of the test variable and the test value, the
    priority the negated order (CellML applies the lowest order first, SBML
    the highest priority), the assignment sets the reset variable.
    """
    test_variable = reset.testVariable()
    variable = reset.variable()
    event: libsbml.Event = model_sbml.createEvent()
    event.setId(f"reset_{index}")
    event.setUseValuesFromTriggerTime(True)

    trigger: libsbml.Trigger = event.createTrigger()
    trigger.setPersistent(True)
    trigger.setInitialValue(True)
    condition = libsbml.ASTNode(libsbml.AST_RELATIONAL_EQ)
    condition.addChild(variable_node(test_variable, ids))
    condition.addChild(
        _reset_expression(reset.testValue(), test_variable, component, ids)
    )
    trigger.setMath(condition)

    priority: libsbml.Priority = event.createPriority()
    order = libsbml.ASTNode(libsbml.AST_REAL)
    order.setValue(-float(reset.order()))
    priority.setMath(order)

    assignment: libsbml.EventAssignment = event.createEventAssignment()
    assignment.setVariable(ids.id_for(variable))
    assignment.setMath(_reset_expression(reset.resetValue(), variable, component, ids))
    logger.info(
        "reset_%d: %s == %s -> %s",
        index,
        ids.id_for(test_variable),
        libsbml.formulaToL3String(condition.getChild(1)),
        ids.id_for(variable),
    )


def _reset_expression(
    mathml: str, variable: Any, component: Any, ids: VariableIds
) -> libsbml.ASTNode:
    """Expression of a test or reset value.

    The MathML is either the expression itself or the equation
    `variable = expression`, in which case the right side is used.
    """
    node = mathml_to_sbml(mathml, component.name(), ids)
    if (
        node.getType() == libsbml.AST_RELATIONAL_EQ
        and node.getNumChildren() == 2
        and node.getChild(0).getType() == libsbml.AST_NAME
        and node.getChild(0).getName() == ids.id_for(variable)
    ):
        return node.getChild(1).deepCopy()
    return node
