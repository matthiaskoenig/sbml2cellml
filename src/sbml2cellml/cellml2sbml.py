"""Conversion of CellML 2.0 models to SBML level 3 version 2.

The libcellml analyser classifies the variables and equations of the model
and resolves the connections between components; the converter renders its
model as SBML: every variable is a parameter, states get rate rules,
algebraic variables assignment rules, computed constants initial assignments,
and the resets of the components become events. CellML units become unit
definitions. There are no compartments, species or reactions.
"""

import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import libcellml
import libsbml

from sbml2cellml import cellml, sbml
from sbml2cellml.sbml import SBMLValidationError
from sbml2cellml.sbmlmath import (
    MathConversionError,
    NumberUnits,
    ast_to_sbml,
    count_numbers,
    mathml_to_sbml,
    variable_node,
)
from sbml2cellml.units import UnitsConversionError, add_units, unit_id
from sbml2cellml.variables import VariableIds, analyser_variables

logger = logging.getLogger(__name__)

AstType = libcellml.AnalyserEquationAst.Type  # ty: ignore[unresolved-attribute]
EquationType = libcellml.AnalyserEquation.Type  # ty: ignore[unresolved-attribute]
VariableType = libcellml.AnalyserVariable.Type  # ty: ignore[unresolved-attribute]
ModelType = libcellml.AnalyserModel.Type  # ty: ignore[unresolved-attribute]
#: model types which can be converted; an implicit (NLA) equation becomes an
#: algebraic rule
SUPPORTED_MODEL_TYPES = (
    ModelType.ODE,
    ModelType.ALGEBRAIC,
    ModelType.DAE,
    ModelType.NLA,
)


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
    except (MathConversionError, UnitsConversionError) as err:
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
    if flat is None:
        raise CellML2SBMLConversionError(
            f"CellML model '{model.name()}' could not be flattened:\n"
            f"{cellml.format_issues(issues)}"
        )
    logger.info("Resolved and flattened the imports of '%s'", model.name())
    return flat


def _analyse(model: libcellml.Model) -> Any:
    """Analyse a model, raising on errors and unsupported model types."""
    analyser = libcellml.Analyser()
    analyser.analyseModel(model)
    issues = [analyser.issue(k) for k in range(analyser.issueCount())]
    errors = cellml.errors(issues)
    analyser_model = analyser.analyserModel()
    if errors:
        type_name = (
            libcellml.AnalyserModel.typeAsString(analyser_model.type())
            if analyser_model is not None
            else "unknown"
        )
        raise CellML2SBMLConversionError(
            f"CellML model '{model.name()}' cannot be analysed (type '{type_name}'):\n"
            f"{cellml.format_issues(errors)}"
        )
    model_type = analyser_model.type()
    if model_type not in SUPPORTED_MODEL_TYPES:
        type_name = libcellml.AnalyserModel.typeAsString(model_type)
        raise CellML2SBMLConversionError(
            f"CellML model '{model.name()}' is of type '{type_name}', only ODE, "
            f"DAE, NLA and algebraic models are supported."
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
        MathConversionError: for a construct which cannot be converted;
            `convert_cellml2sbml` wraps it.
        UnitsConversionError: for units which cannot be converted;
            `convert_cellml2sbml` wraps it.
    """
    doc = libsbml.SBMLDocument(3, 2)
    model_sbml: libsbml.Model = doc.createModel()
    name = model.name() or "model"

    unit_ids = add_units(model, model_sbml)
    ids = VariableIds(analyser_model)

    model_sbml.setId(ids.reserve(name))
    model_sbml.setName(name)

    voi = analyser_model.voi()
    if voi is not None:
        model_sbml.setTimeUnits(unit_id(voi.variable().units().name(), unit_ids))

    # variables which only a reset writes are not constant, even though the
    # analyser types them CONSTANT or COMPUTED_CONSTANT (they have an
    # `initial_value` and no equation); the reset may be declared on a
    # connected copy of the variable in another component, so the targets
    # are keyed by SBML id, not by (component, variable) name
    reset_targets = {
        ids.id_for(component.reset(k).variable())
        for component in _components(model)
        for k in range(component.resetCount())
    }

    for k in range(analyser_model.stateCount()):
        _add_parameter(
            model_sbml, analyser_model.state(k), ids, unit_ids, constant=False
        )
    for variable in analyser_variables(analyser_model):
        variable_type = variable.type()
        if variable_type == VariableType.EXTERNAL_VARIABLE:
            raise MathConversionError(
                f"External variable '{variable.variable().name()}' is not supported."
            )
        sid = ids.id_for(variable.variable())
        constant = (
            variable_type in (VariableType.CONSTANT, VariableType.COMPUTED_CONSTANT)
            and sid not in reset_targets
        )
        _add_parameter(model_sbml, variable, ids, unit_ids, constant=constant)

    def sbml_unit_id(units_name: str) -> str:
        return unit_id(units_name, unit_ids)

    number_units = NumberUnits(model, ids, sbml_unit_id)
    for k in range(analyser_model.analyserEquationCount()):
        _add_equation(model_sbml, analyser_model.analyserEquation(k), ids, number_units)

    _add_events(model_sbml, model, ids, sbml_unit_id)
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
        try:
            reference = ids.lookup(initialising.parent().name(), initial)
        except KeyError as err:
            raise MathConversionError(
                f"Initial value '{initial}' of variable '{variable.name()}' in "
                f"component '{initialising.parent().name()}' is not a variable of "
                f"that component."
            ) from err
        assignment: libsbml.InitialAssignment = model_sbml.createInitialAssignment()
        assignment.setSymbol(sid)
        node = libsbml.ASTNode(libsbml.AST_NAME)
        node.setName(reference)
        assignment.setMath(node)
        logger.info("%s initialised from '%s'", sid, reference)


def _equation_variables(equation: Any) -> list[Any]:
    """Analyser variables an equation computes: states, then the others by type."""
    return (
        [equation.state(k) for k in range(equation.stateCount())]
        + [
            equation.computedConstant(k)
            for k in range(equation.computedConstantCount())
        ]
        + [
            equation.algebraicVariable(k)
            for k in range(equation.algebraicVariableCount())
        ]
        + [
            equation.externalVariable(k)
            for k in range(equation.externalVariableCount())
        ]
    )


def _add_equation(
    model_sbml: libsbml.Model,
    equation: Any,
    ids: VariableIds,
    number_units: NumberUnits,
) -> None:
    """Add the rule or initial assignment of an equation."""
    equation_type = equation.type()
    type_name = libcellml.AnalyserEquation.typeAsString(equation_type)
    names = [variable.variable().name() for variable in _equation_variables(equation)]
    if equation_type == EquationType.EXTERNAL:
        raise MathConversionError(
            f"Equation of type '{type_name}' for {names} is not supported."
        )
    ast = equation.ast()
    units = number_units.units_of(ast)
    if equation_type == EquationType.NLA:
        # an implicit equation is the algebraic rule `0 = residual`; the
        # analyser gives the residual `left - right` of `left = right`
        if ast.type() == AstType.EQUALITY:
            residual = libsbml.ASTNode(libsbml.AST_MINUS)
            residual.addChild(ast_to_sbml(ast.leftChild(), ids, units))
            residual.addChild(ast_to_sbml(ast.rightChild(), ids, units))
        else:
            residual = ast_to_sbml(ast, ids, units)
        algebraic: libsbml.AlgebraicRule = model_sbml.createAlgebraicRule()
        algebraic.setMath(residual)
        logger.info("0 = %s", libsbml.formulaToL3String(residual))
        return
    if ast.type() != AstType.EQUALITY:
        raise MathConversionError(f"Equation for {names} is not an equality.")
    left, right = ast.leftChild(), ast.rightChild()
    if units is not None:
        # the units are those of the whole equation, from the left to the right
        for _ in range(count_numbers(left)):
            next(units, None)
    rhs = ast_to_sbml(right, ids, units)

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
        EquationType.CONSTANT,
        EquationType.COMPUTED_CONSTANT,
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
    model_sbml: libsbml.Model,
    model: libcellml.Model,
    ids: VariableIds,
    sbml_unit_id: Callable[[str], str],
) -> None:
    """Add an event per reset of every component."""
    index = 0
    for component in _components(model):
        for k in range(component.resetCount()):
            index += 1
            _add_reset(
                model_sbml, component, component.reset(k), index, ids, sbml_unit_id
            )


def _add_reset(
    model_sbml: libsbml.Model,
    component: Any,
    reset: Any,
    index: int,
    ids: VariableIds,
    sbml_unit_id: Callable[[str], str],
) -> None:
    """Add the event of a reset.

    The trigger is the equality of the test variable and the test value, the
    priority the negated order (CellML applies the lowest order first, SBML
    the highest priority), the assignment sets the reset variable.
    """
    test_variable = reset.testVariable()
    variable = reset.variable()
    event: libsbml.Event = model_sbml.createEvent()
    event.setId(ids.reserve(f"reset_{index}"))
    event.setUseValuesFromTriggerTime(True)

    trigger: libsbml.Trigger = event.createTrigger()
    trigger.setPersistent(True)
    trigger.setInitialValue(True)
    condition = libsbml.ASTNode(libsbml.AST_RELATIONAL_EQ)
    condition.addChild(variable_node(test_variable, ids))
    condition.addChild(
        _reset_expression(
            reset.testValue(), test_variable, component, ids, sbml_unit_id
        )
    )
    trigger.setMath(condition)

    priority: libsbml.Priority = event.createPriority()
    order = libsbml.ASTNode(libsbml.AST_REAL)
    order.setValue(-float(reset.order()))
    priority.setMath(order)

    assignment: libsbml.EventAssignment = event.createEventAssignment()
    assignment.setVariable(ids.id_for(variable))
    assignment.setMath(
        _reset_expression(reset.resetValue(), variable, component, ids, sbml_unit_id)
    )
    logger.info(
        "reset_%d: %s == %s -> %s",
        index,
        ids.id_for(test_variable),
        libsbml.formulaToL3String(condition.getChild(1)),
        ids.id_for(variable),
    )


def _reset_expression(
    mathml: str,
    variable: Any,
    component: Any,
    ids: VariableIds,
    sbml_unit_id: Callable[[str], str],
) -> libsbml.ASTNode:
    """Expression of a test or reset value.

    The MathML is either the expression itself or the equation
    `variable = expression`, in which case the right side is used.
    """
    node = mathml_to_sbml(mathml, component.name(), ids, sbml_unit_id)
    if (
        node.getType() == libsbml.AST_RELATIONAL_EQ
        and node.getNumChildren() == 2
        and node.getChild(0).getType() == libsbml.AST_NAME
        and node.getChild(0).getName() == ids.id_for(variable)
    ):
        return node.getChild(1).deepCopy()
    return node
