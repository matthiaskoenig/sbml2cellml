"""Conversion of CellML 2.0 models to SBML level 3 version 2.

The libcellml analyser classifies the variables and equations of the model
and resolves the connections between components; the converter renders its
model as SBML: every variable is a parameter, states get rate rules,
algebraic variables assignment rules, computed constants initial assignments,
and the resets of the components become events. CellML units become unit
definitions. There are no compartments, species or reactions.

The metadata of an SBML model which `sbml2cellml` wrote next to the CellML
file (`sbml2cellml.metadata`) comes back on the parameters, the unit
definitions and the model.
"""

import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import libcellml
import libsbml

from sbml2cellml import cellml, sbml
from sbml2cellml.metadata import Record, apply_metadata, read_metadata
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
from sbml2cellml.variables import (
    ComponentIds,
    VariableIds,
    analyser_variables,
    components,
    equivalence_set,
    sanitize_id,
    unique_sid,
    variable_key,
)

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


#: suffix of the file with the metadata, next to the CellML file
METADATA_SUFFIX = ".rdf"

#: name of the SBML package for the hierarchical model composition
COMP_PACKAGE = "comp"


def convert_cellml2sbml(
    cellml_path: Path,
    sbml_path: Path | None = None,
    validate: bool = True,
    metadata: bool = True,
    hierarchical: bool = False,
) -> libsbml.SBMLDocument:
    """Convert a CellML file to an SBML document.

    Args:
        cellml_path: path of the CellML file; imports are resolved relative to it.
        sbml_path: path the SBML is written to, not written if `None`.
        validate: check the consistency of the document with libsbml and raise
            if it has errors.
        metadata: read the metadata from the RDF file next to the CellML file
            (`<stem>.rdf`, see `sbml2cellml.metadata`) when it exists.
        hierarchical: write every component as a submodel of the
            hierarchical model composition package (`comp`,
            `build_hierarchical_document`) instead of one flat model.

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
    model = read_cellml_model(cellml_path)
    logger.info("Converting CellML model '%s' from '%s'", model.name(), cellml_path)
    analyser_model = analyse_model(model)
    metadata_path = cellml_path.with_suffix(METADATA_SUFFIX)
    records: dict[str, Record] = {}
    if metadata and metadata_path.is_file():
        try:
            records = read_metadata(metadata_path, cellml_path.name)
        except ValueError as err:
            raise CellML2SBMLConversionError(str(err)) from err
        logger.info("Metadata of %d elements in '%s'", len(records), metadata_path)
    build = build_hierarchical_document if hierarchical else build_document
    try:
        doc = build(model, analyser_model, records)
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


def read_cellml_model(cellml_path: Path) -> libcellml.Model:
    """Read a CellML file of any version and flatten its imports.

    A CellML 1.0 or 1.1 document, which the models of the Physiome Model
    Repository are, is read in the permissive mode of libcellml, as are the
    files it imports.

    Args:
        cellml_path: path of the CellML file; imports are resolved relative
            to it.

    Returns:
        The model with its imports flattened.

    Raises:
        CellMLValidationError: if the file cannot be parsed.
        CellML2SBMLConversionError: if the imports cannot be resolved.
    """
    cellml_path = Path(cellml_path)
    version = cellml.cellml_version(cellml_path.read_text(encoding="utf-8"))
    if version is not None:
        logger.warning(
            "CellML %s model '%s', read in permissive mode", version, cellml_path
        )
    model = cellml.read_model(cellml_path, strict=version is None)
    return _flatten(model, cellml_path.parent, permissive=version is not None)


def _flatten(
    model: libcellml.Model, base_path: Path, permissive: bool = False
) -> libcellml.Model:
    """Resolve the imports of a model and flatten it, if it has any.

    Args:
        model: the parsed model.
        base_path: directory the imports are resolved from.
        permissive: read the imported files as CellML 1.0 and 1.1 documents
            as well, as the parser of a model of that version does.

    Returns:
        The model with its imports flattened, the model itself when it has
        no imports.
    """
    if not model.hasImports():
        return model
    importer = libcellml.Importer(permissive)
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


def analyse_model(model: libcellml.Model) -> Any:
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


def build_document(
    model: libcellml.Model,
    analyser_model: Any,
    records: dict[str, Record] | None = None,
) -> libsbml.SBMLDocument:
    """Build the SBML document of an analysed CellML model.

    Args:
        model: the (flattened) CellML model.
        analyser_model: its analyser model without errors.
        records: metadata by the id of a CellML element
            (`sbml2cellml.metadata.read_metadata`), none when `None`.

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
    _add_metadata(model_sbml, model, ids, unit_ids, records or {})
    return doc


def _first_variable(node: Any) -> Any | None:
    """First variable of an analyser AST, depth first from the left."""
    if node is None:
        return None
    if node.type() == AstType.CI:
        return node.variable()
    for child in (node.leftChild(), node.rightChild()):
        found = _first_variable(child)
        if found is not None:
            return found
    return None


def _equation_component(equation: Any) -> str | None:
    """Name of the component the math of an equation is written in.

    The analyser keeps the variables of the component an equation comes
    from, so the first variable of its left side (the state of an ODE, the
    variable of an assignment, any variable of an implicit equation) names
    the component.

    Args:
        equation: analyser equation.

    Returns:
        The name of the component, `None` for an equation without variables.
    """
    ast = equation.ast()
    if ast is None:
        return None
    side = ast.leftChild() if ast.type() == AstType.EQUALITY else ast
    if side is not None and side.type() == AstType.DIFF:
        side = side.rightChild()
    variable = _first_variable(side)
    if variable is None:
        variable = _first_variable(ast)
    if variable is None or variable.parent() is None:
        return None
    return variable.parent().name()


def _equations_by_component(analyser_model: Any) -> dict[str, list[Any]]:
    """The analyser equations of a model by the component they come from.

    Args:
        analyser_model: model of a libcellml analyser without errors.

    Returns:
        The equations per component name, in the order of the analyser.

    Raises:
        MathConversionError: if an equation belongs to no component.
    """
    by_component: dict[str, list[Any]] = {}
    for k in range(analyser_model.analyserEquationCount()):
        equation = analyser_model.analyserEquation(k)
        name = _equation_component(equation)
        if name is None:
            raise MathConversionError(
                "An equation of the model is not written in a component."
            )
        by_component.setdefault(name, []).append(equation)
    return by_component


def _member_of(component_name: str, variable: Any) -> Any | None:
    """The variable of an equivalence set which lives in a component."""
    for member in equivalence_set(variable):
        if member.parent() is not None and member.parent().name() == component_name:
            return member
    return None


def _computed_names(component: Any, equations: list[Any]) -> set[str]:
    """Names of the variables an equation or a reset of the component writes.

    They become the parameters which are not constant: a state with its rate
    rule, an algebraic variable with its assignment rule, the unknowns of an
    implicit equation and the variable of a reset. A computed constant keeps
    its initial assignment and stays constant, as in the flat conversion.

    Args:
        component: CellML component.
        equations: the analyser equations of that component.

    Returns:
        The names of the variables of the component.
    """
    names: set[str] = set()
    for equation in equations:
        equation_type = equation.type()
        ast = equation.ast()
        if equation_type == EquationType.ODE:
            left = ast.leftChild() if ast is not None else None
            state = left.rightChild() if left is not None else None
            variable = state.variable() if state is not None else None
            if variable is not None:
                names.add(variable.name())
        elif equation_type == EquationType.ALGEBRAIC:
            variable = _first_variable(ast.leftChild() if ast is not None else None)
            if variable is not None:
                names.add(variable.name())
        elif equation_type == EquationType.NLA:
            for analyser_variable in _equation_variables(equation):
                member = _member_of(component.name(), analyser_variable.variable())
                if member is not None:
                    names.add(member.name())
    for k in range(component.resetCount()):
        variable = component.reset(k).variable()
        if variable is not None:
            names.add(variable.name())
    return names


def _add_component_parameters(
    definition: libsbml.Model,
    component: Any,
    equations: list[Any],
    ids: ComponentIds,
    unit_ids: dict[str, str],
) -> None:
    """Add a parameter for every variable of a component to its definition.

    A variable the component computes is not constant, the others are: their
    value comes from the model the submodel is used in, through the
    replacement of the variable (`_add_replacements`).

    Args:
        definition: the SBML model definition of the component.
        component: CellML component.
        equations: the analyser equations of that component.
        ids: the local ids of the variables.
        unit_ids: the SBML unit ids by CellML units name.

    Raises:
        MathConversionError: if an initial value names a variable which is
            not part of the component.
    """
    computed = _computed_names(component, equations)
    for k in range(component.variableCount()):
        variable = component.variable(k)
        if ids.is_voi(variable):
            continue
        sid = ids.id_for(variable)
        parameter: libsbml.Parameter = definition.createParameter()
        parameter.setId(sid)
        parameter.setConstant(variable.name() not in computed)
        parameter.setUnits(unit_id(variable.units().name(), unit_ids))
        if sid != variable.name():
            parameter.setName(variable.name())
        initial = variable.initialValue()
        if not initial:
            continue
        try:
            parameter.setValue(float(initial))
        except ValueError:
            try:
                reference = ids.lookup(component.name(), initial)
            except KeyError as err:
                raise MathConversionError(
                    f"Initial value '{initial}' of variable '{variable.name()}' "
                    f"in component '{component.name()}' is not a variable of "
                    f"that component."
                ) from err
            assignment: libsbml.InitialAssignment = definition.createInitialAssignment()
            assignment.setSymbol(sid)
            node = libsbml.ASTNode(libsbml.AST_NAME)
            node.setName(reference)
            assignment.setMath(node)


def _add_component_resets(
    definition: libsbml.Model,
    component: Any,
    ids: ComponentIds,
    sbml_unit_id: Callable[[str], str],
) -> None:
    """Add an event per reset of a component to its model definition."""
    for k in range(component.resetCount()):
        _add_reset(definition, component, component.reset(k), k + 1, ids, sbml_unit_id)


def _replacement_path(variable: Any) -> list[str]:
    """Names of the components from the top of the model down to a variable."""
    path: list[str] = []
    parent = variable.parent()
    while isinstance(parent, libcellml.Component):
        path.append(parent.name())
        parent = parent.parent()
    path.reverse()
    return path


def _add_replacements(
    parameter: libsbml.Parameter,
    analyser_variable: Any,
    submodels: dict[str, str],
    ids: ComponentIds,
) -> None:
    """Replace the variable of every component by a parameter of the model.

    The parameter of the top level model replaces the parameter of every
    component of the equivalence set, which is what the connections of the
    CellML model say: they are one variable. A variable of a component which
    is encapsulated by another one is addressed through the submodels down
    to it (`comp:sBaseRef`).

    Args:
        parameter: the parameter of the top level model.
        analyser_variable: the analyser variable of the equivalence set.
        submodels: the id of the submodel of a component by component name.
        ids: the local ids of the variables.
    """
    plugin = parameter.getPlugin(COMP_PACKAGE)
    for member in equivalence_set(analyser_variable.variable()):
        path = _replacement_path(member)
        if not path or path[0] not in submodels:
            continue
        replaced: libsbml.ReplacedElement = plugin.createReplacedElement()
        replaced.setSubmodelRef(submodels[path[0]])
        reference: Any = replaced
        for name in path[1:]:
            reference.setIdRef(submodels[name])
            reference = reference.createSBaseRef()
        reference.setIdRef(ids.id_for(member))


def _connected_variables(analyser_model: Any, model: libcellml.Model) -> list[Any]:
    """Analyser variables whose equivalence set spans more than one component.

    They become the parameters of the top level model, which replace the
    parameters of the components. A variable of a single component stays
    inside the model definition of that component, as does the initial value
    which names a variable of the same component.

    Args:
        analyser_model: model of a libcellml analyser without errors.
        model: the CellML model.

    Returns:
        The analyser variables, states first.
    """
    variables = [
        analyser_model.state(k) for k in range(analyser_model.stateCount())
    ] + analyser_variables(analyser_model)
    voi = analyser_model.voi()
    voi_variable = voi.variable() if voi is not None else None
    connected = []
    for analyser_variable in variables:
        variable = analyser_variable.variable()
        if voi_variable is not None and ids_of_set(variable) == ids_of_set(
            voi_variable
        ):
            continue
        components_of_set = {
            member.parent().name()
            for member in equivalence_set(variable)
            if member.parent() is not None
        }
        if len(components_of_set) > 1:
            connected.append(analyser_variable)
    return connected


def ids_of_set(variable: Any) -> frozenset[tuple[str, str]]:
    """Keys of the variables of an equivalence set."""
    return frozenset(variable_key(member) for member in equivalence_set(variable))


def build_hierarchical_document(
    model: libcellml.Model,
    analyser_model: Any,
    records: dict[str, Record] | None = None,
) -> libsbml.SBMLDocument:
    """Build the SBML document of a model, one submodel per component.

    Every component of the CellML model becomes a model definition of the
    hierarchical model composition package (`comp`) with the parameters of
    its variables, the rules of its equations and the events of its resets;
    a component encapsulated by another one is a submodel of the definition
    of that component, the other components are submodels of the model. A
    variable which is connected to a variable of another component is a
    parameter of the model which replaces the parameter of every component
    of the equivalence set, so that the flattened model is the model of
    `build_document`.

    Args:
        model: the (flattened) CellML model.
        analyser_model: its analyser model without errors.
        records: metadata by the id of a CellML element
            (`sbml2cellml.metadata.read_metadata`), none when `None`.

    Returns:
        The SBML document with the comp package, not validated.

    Raises:
        MathConversionError: for a construct which cannot be converted;
            `convert_cellml2sbml` wraps it.
        UnitsConversionError: for units which cannot be converted;
            `convert_cellml2sbml` wraps it.
    """
    namespaces = libsbml.SBMLNamespaces(3, 2, COMP_PACKAGE, 1)
    doc = libsbml.SBMLDocument(namespaces)
    doc.setPackageRequired(COMP_PACKAGE, True)
    document_plugin = doc.getPlugin(COMP_PACKAGE)
    model_sbml: libsbml.Model = doc.createModel()
    name = model.name() or "model"

    unit_ids = add_units(model, model_sbml)
    ids = VariableIds(analyser_model)
    local = ComponentIds(model, analyser_model)
    model_sbml.setId(ids.reserve(name))
    model_sbml.setName(name)
    voi = analyser_model.voi()
    if voi is not None:
        model_sbml.setTimeUnits(unit_id(voi.variable().units().name(), unit_ids))

    def sbml_unit_id(units_name: str) -> str:
        return unit_id(units_name, unit_ids)

    number_units = NumberUnits(model, local, sbml_unit_id)
    equations = _equations_by_component(analyser_model)
    definitions: dict[str, str] = {}
    used: set[str] = set()
    for component in components(model):
        definitions[component.name()] = unique_sid(
            sanitize_id(f"{component.name()}_component"), used
        )

    submodels: dict[str, str] = {}
    for component in components(model):
        definition = document_plugin.createModelDefinition()
        definition.setId(definitions[component.name()])
        definition.setName(component.name())
        add_units(model, definition)
        component_equations = equations.get(component.name(), [])
        _add_component_parameters(
            definition, component, component_equations, local, unit_ids
        )
        for equation in component_equations:
            _add_equation(definition, equation, local, number_units)
        _add_component_resets(definition, component, local, sbml_unit_id)
        logger.info(
            "'%s' model definition of component '%s' with %d parameters",
            definition.getId(),
            component.name(),
            definition.getNumParameters(),
        )
        for k in range(component.componentCount()):
            child = component.component(k)
            submodel: libsbml.Submodel = definition.getPlugin(
                COMP_PACKAGE
            ).createSubmodel()
            submodel.setId(local.reserve(child.name()))
            submodel.setModelRef(definitions[child.name()])
            submodels[child.name()] = submodel.getId()

    model_plugin = model_sbml.getPlugin(COMP_PACKAGE)
    for k in range(model.componentCount()):
        component = model.component(k)
        submodel = model_plugin.createSubmodel()
        submodel.setId(ids.reserve(component.name()))
        submodel.setModelRef(definitions[component.name()])
        submodels[component.name()] = submodel.getId()

    reset_targets = {
        ids.id_for(component.reset(k).variable())
        for component in components(model)
        for k in range(component.resetCount())
    }
    for analyser_variable in _connected_variables(analyser_model, model):
        sid = ids.id_for(analyser_variable.variable())
        variable_type = analyser_variable.type()
        constant = (
            variable_type in (VariableType.CONSTANT, VariableType.COMPUTED_CONSTANT)
            and sid not in reset_targets
        )
        _add_parameter(model_sbml, analyser_variable, ids, unit_ids, constant=constant)
        _add_replacements(
            model_sbml.getParameter(sid), analyser_variable, submodels, local
        )
    logger.info(
        "Hierarchical model '%s' with %d submodels and %d replaced variables",
        model_sbml.getId(),
        model_plugin.getNumSubmodels(),
        model_sbml.getNumParameters(),
    )
    _add_metadata(model_sbml, model, ids, unit_ids, records or {})
    return doc


def _add_metadata(
    model_sbml: libsbml.Model,
    model: libcellml.Model,
    ids: VariableIds,
    unit_ids: dict[str, str],
    records: dict[str, Record],
) -> None:
    """Set the metadata on the elements of the SBML model.

    A record belongs to the CellML element with its id: to the parameter of
    a variable (of the equivalence set of the variable, the first record
    wins), to the unit definition of units, or to the model. The id is the
    metaid of the SBML element, it is unique in the CellML model.
    """
    elements: dict[str, libsbml.SBase] = {}
    if model.id():
        elements[model.id()] = model_sbml
    for k in range(model.unitsCount()):
        units = model.units(k)
        definition = model_sbml.getUnitDefinition(unit_ids.get(units.name(), ""))
        if units.id() and definition is not None:
            elements[units.id()] = definition
    for component in _components(model):
        for k in range(component.variableCount()):
            variable = component.variable(k)
            if not variable.id():
                continue
            try:
                parameter = model_sbml.getParameter(ids.id_for(variable))
            except KeyError:
                continue  # not part of the analysed model
            if parameter is not None:
                elements[variable.id()] = parameter

    applied: set[str] = set()
    for cid, record in records.items():
        element = elements.get(cid)
        if element is None:
            logger.info("Metadata of '%s' has no element in the SBML model", cid)
            continue
        key = f"{element.getTypeCode()}:{element.getId()}"
        if key in applied:
            logger.info("Metadata of '%s' ignored, its parameter has some", cid)
            continue
        applied.add(key)
        apply_metadata(element, record, cid)


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

    The trigger is the equality of the test variable and the test value, or
    the condition of a test variable which is `piecewise(1, condition, 0)`
    (`_condition_of_a_trigger`), the priority the negated order (CellML
    applies the lowest order first, SBML the highest priority), the
    assignment sets the reset variable.
    """
    test_variable = reset.testVariable()
    variable = reset.variable()
    event: libsbml.Event = model_sbml.createEvent()
    event.setId(ids.reserve(f"reset_{index}"))
    event.setUseValuesFromTriggerTime(True)

    trigger: libsbml.Trigger = event.createTrigger()
    trigger.setPersistent(True)
    trigger.setInitialValue(True)
    value = _reset_expression(
        reset.testValue(), test_variable, component, ids, sbml_unit_id
    )
    test_sid = ids.id_for(test_variable)
    condition = _condition_of_a_trigger(model_sbml, test_sid, value)
    if condition is None:
        condition = libsbml.ASTNode(libsbml.AST_RELATIONAL_EQ)
        condition.addChild(variable_node(test_variable, ids))
        condition.addChild(value)
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


def _condition_of_a_trigger(
    model_sbml: libsbml.Model, test_sid: str, value: libsbml.ASTNode
) -> libsbml.ASTNode | None:
    """Condition of a test variable which stands for a trigger.

    `sbml2cellml` writes the trigger of an SBML event as the variable
    `piecewise(1, condition, 0)` and resets when it reaches 1. The
    condition itself is the trigger of the event again, which a simulator
    evaluates as a boolean instead of looking for the root of a step.

    Args:
        model_sbml: the SBML model with the rules of the variables.
        test_sid: id of the test variable of the reset.
        value: the test value of the reset.

    Returns:
        The condition, or `None` when the test variable is no such trigger.
    """
    if not (value.isNumber() and value.getValue() == 1.0):
        return None
    rule: libsbml.Rule = model_sbml.getRule(test_sid)
    if rule is None or not rule.isAssignment() or not rule.isSetMath():
        return None
    math_node: libsbml.ASTNode = rule.getMath()
    if (
        math_node.getType() != libsbml.AST_FUNCTION_PIECEWISE
        or math_node.getNumChildren() != 3
        or not math_node.getChild(0).isNumber()
        or math_node.getChild(0).getValue() != 1.0
        or not math_node.getChild(2).isNumber()
        or math_node.getChild(2).getValue() != 0.0
    ):
        return None
    return math_node.getChild(1).deepCopy()


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
