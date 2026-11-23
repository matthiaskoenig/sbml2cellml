"""Conversion of SBML models to CellML 2.0.

The conversion puts every SBML compartment, parameter and species as a variable
into a single CellML component `sbml`, together with the variable of
integration `time`. Assignment rules become equations, rate rules
differential equations. Every reaction with a kinetic law is a variable of its
rate, the rates of its reactions are the differential equation of a species.
The target of an
assignment rule has no initial value, the rule defines it at all times. A
species in concentration whose compartment changes gets a second variable
`<species>_amount`: the reactions change the amount, the concentration is the
amount per size of the compartment. The
unit definitions and the units of numbers are converted, the units of the
variables when the unit annotation of the model is complete
(`sbml2cellml.cellmlunits`), else all variables are `dimensionless`.

Every formula stays the AST libsbml reads from the model, new formulas are
built from nodes (`sbml2cellml.astnodes`): as text an id such as `avogadro`,
`pi` or `NaN` would be read back as the symbol of that name.

CellML has no functions: the calls of SBML function definitions are replaced
by the bodies of the functions (libsbml's `expandFunctionDefinitions`
conversion) before the conversion, and the initial assignments are evaluated
to initial values (`expandInitialAssignments`).

A formula with a delay has no counterpart in CellML and is not converted
(logged as a warning, see docs/conversion-issues.md).

The conversion runs in rust by default (`sbml2cellml.rust`, the crate
`crates/tocellml`), which writes the same CellML model as this module
without libsbml and without libcellml; `rust.ENGINES` are the engines of
`convert_sbml2cellml`, and the python engine writes what rust does not do.
"""

import dataclasses
import logging
import math
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import libcellml
import libsbml

from sbml2cellml import astnodes, cellml, mathml, rust, sbml
from sbml2cellml import metadata as sbml_metadata
from sbml2cellml.cellml import CellMLValidationError
from sbml2cellml.cellmlunits import CellMLUnits
from sbml2cellml.mathml import TIME_ID
from sbml2cellml.rust import Engine
from sbml2cellml.sbml import SBMLValidationError
from sbml2cellml.variables import unique_sid

logger = logging.getLogger(__name__)

#: name of the single component which holds the model
COMPONENT_ID = "sbml"
#: units of a variable without units
UNITS_ID = "dimensionless"
#: suffix of the file with the metadata, next to the CellML file
METADATA_SUFFIX = ".rdf"
#: variables without units named in the warning of an incomplete annotation
MISSING_UNITS_LOGGED = 10


class SBML2CellMLConversionError(ValueError):
    """The SBML document cannot be converted."""


def convert_sbml2cellml(
    sbml_path: Path,
    cellml_path: Path | None = None,
    validate: bool = True,
    metadata: bool = True,
    engine: Engine = "auto",
) -> libcellml.Model:
    """Convert an SBML file to a CellML model.

    Args:
        sbml_path: path of the SBML file.
        cellml_path: path the CellML is written to, not written if `None`.
        validate: validate and analyse the CellML model with libcellml and
            raise if it has errors.
        metadata: write the names, notes, SBO terms, annotations and the
            history of the SBML elements as RDF next to the CellML file
            (`<stem>.rdf`, see `sbml2cellml.metadata`); no file is written
            for a model without metadata.
        engine: which converter writes the model, `"rust"` for the crates of
            the repository (`sbml2cellml.rust`), `"python"` for libsbml,
            libcellml and this module, and `"auto"` for rust, with python
            for a model the rust converter refuses (a formula with a
            delay).

    Returns:
        The CellML model.

    Raises:
        SBML2CellMLConversionError: if the file does not exist, has no model
            or cannot be converted by the engine which is asked for.
        CellMLValidationError: if `validate` is set and the model has errors.
    """
    sbml_path = Path(sbml_path)
    if not sbml_path.is_file():
        raise SBML2CellMLConversionError(f"SBML file does not exist: '{sbml_path}'.")
    doc: libsbml.SBMLDocument = libsbml.readSBMLFromFile(str(sbml_path))
    model_sbml: libsbml.Model | None = doc.getModel()
    if model_sbml is None:
        raise SBML2CellMLConversionError(f"No model in SBML file '{sbml_path}'.")
    # CellML has no counterpart of a submodel: a hierarchical model is
    # flattened, so its components are those of the flat model
    try:
        flattened = sbml.flatten_comp(doc, base_path=Path(sbml_path).parent)
    except SBMLValidationError as err:
        raise SBML2CellMLConversionError(str(err)) from err
    if flattened is not None:
        logger.warning(
            "Flattened the submodels of the hierarchical model '%s'", sbml_path
        )
        doc = flattened
        model_sbml = doc.getModel()
    mid: str = model_sbml.getId() if model_sbml.isSetId() else Path(sbml_path).stem
    logger.info("Converting SBML model '%s' from '%s'", mid, sbml_path)

    model: libcellml.Model | None = None
    # the SBML element of every CellML element which stands for one, for the
    # metadata of the model
    elements: dict[str, libsbml.SBase] = {}
    if engine != "python":
        try:
            # the text of the file unless libsbml wrote the flattened
            # document, so that the model is not serialized again
            text = (
                libsbml.writeSBMLToString(doc)
                if flattened is not None
                else sbml_path.read_text(encoding="utf-8")
            )
            model, elements = _convert_with_rust(text, mid, model_sbml)
        except rust.RustError as err:
            if engine == "rust":
                raise SBML2CellMLConversionError(
                    f"SBML model of '{sbml_path}' cannot be converted "
                    f"by the rust engine: {err}"
                ) from err
            logger.warning(
                "The rust engine refused '%s', converting with python: %s",
                sbml_path,
                err,
            )
    if model is None:
        model, elements = _convert_with_python(doc, mid)

    if validate:
        issues = cellml.errors(cellml.validate_model(model))
        if issues:
            raise CellMLValidationError(
                f"CellML model '{mid}' converted from '{sbml_path}' has "
                f"{len(issues)} errors:\n{cellml.format_issues(issues)}"
            )

    if cellml_path is not None:
        cellml.write_model(model, cellml_path)
        logger.info("CellML written to '%s'", cellml_path)
        if metadata:
            _write_metadata(elements, Path(cellml_path))

    return model


def _convert_with_rust(
    text: str, mid: str, model_sbml: libsbml.Model
) -> tuple[libcellml.Model, dict[str, libsbml.SBase]]:
    """Convert an SBML document with the rust converter.

    The document is handed over as text, with the submodels of a hierarchical
    model flattened by the caller, since the rust crates read no file and
    know no package. The conversion gives the SBML element of every element
    of the CellML model which stands for one, which `_rust_elements` resolves
    for the metadata; the ids the metadata points at are set here, as the
    python engine sets them (`_set_ids`).

    Args:
        text: the SBML document, flattened.
        mid: the name of the CellML model.
        model_sbml: the model of the document, for the metadata.

    Returns:
        The model, parsed from the CellML text the rust converter writes,
        and the SBML element of every CellML element which stands for one.

    Raises:
        RustError: if the document cannot be read or converted.
        CellMLValidationError: if the CellML text cannot be parsed.
    """
    cellml_text, warnings, origins = rust.convert_sbml_to_cellml(text, mid)
    for warning in warnings:
        logger.warning("%s", warning)
    model = cellml.parse_model(cellml_text, f"model '{mid}' of the rust engine")
    _set_ids(model)
    logger.info("Converted the model '%s' with the rust engine", mid)
    return model, _rust_elements(model_sbml, model, origins)


def _rust_elements(
    model_sbml: libsbml.Model,
    model: libcellml.Model,
    origins: list[rust.Origin],
) -> dict[str, libsbml.SBase]:
    """The SBML element of every CellML element of a conversion in rust.

    The rust converter names the element of the CellML model which every
    SBML element became (`sbml2cellml.rust.Origin`); the id of that element
    is what the metadata points at (`_set_ids`).

    Args:
        model_sbml: the SBML model, before libsbml expanded anything.
        model: the CellML model with its ids.
        origins: the SBML element of every CellML element, from the rust
            conversion.

    Returns:
        The SBML element by the id of its CellML element, as
        `_metadata_elements` gives it for the python engine.
    """
    component: libcellml.Component = model.component(COMPONENT_ID)
    elements: dict[str, libsbml.SBase] = {}
    for name, kind, sid, pid in origins:
        element: libsbml.SBase | None
        cellml_id: str
        if kind == "model":
            element, cellml_id = model_sbml, model.id()
        elif kind == "event":
            # the trigger variable carries what a reset cannot express
            variable = component.variable(name)
            if variable is None:
                continue
            element, cellml_id = _event_of(model_sbml, sid), variable.id()
        elif kind == "units":
            units: libcellml.Units | None = model.units(name)
            if units is None:
                continue
            element, cellml_id = model_sbml.getUnitDefinition(sid), units.id()
        else:
            variable: libcellml.Variable | None = component.variable(name)
            if variable is None:
                continue
            cellml_id = variable.id()
            if kind == "local_parameter":
                reaction: libsbml.Reaction | None = model_sbml.getReaction(sid)
                law = None if reaction is None else reaction.getKineticLaw()
                element = None if law is None else law.getParameter(pid)
            else:
                element = model_sbml.getElementBySId(sid)
        if element is not None and cellml_id:
            elements[cellml_id] = element
    return elements


def _convert_with_python(
    doc: libsbml.SBMLDocument, mid: str
) -> tuple[libcellml.Model, dict[str, libsbml.SBase]]:
    """Convert an SBML document with libsbml, libcellml and this module.

    Args:
        doc: the SBML document, flattened.
        mid: the name of the CellML model.

    Returns:
        The model and the SBML element of every CellML element which stands
        for one, for the metadata of the model.
    """
    model_sbml: libsbml.Model = doc.getModel()
    # CellML has neither functions nor initial assignments: libsbml inlines the
    # function calls, the formulas are collected (they do not depend on the
    # initial values), the rateOf symbols of the initial assignments replaced,
    # and libsbml evaluates the initial assignments to initial values
    recursive = _recursive_functions(model_sbml)
    _expand(doc, mid, recursive, FUNCTION_DEFINITIONS)
    formulas = _collect_formulas(doc.getModel())
    _rate_of_in_initial_assignments(doc.getModel(), formulas)
    _drop_initial_assignments_without_math(doc.getModel())
    _expand(doc, mid, recursive, INITIAL_ASSIGNMENTS)
    # the conversions rewrite the document, its model is read again
    model_sbml = doc.getModel()
    assert model_sbml is not None
    _solve_algebraic_rules(model_sbml, formulas)

    model, cellml_units = _build_model(mid, model_sbml, formulas)
    if formulas.events and cellml.errors(cellml.validate_model(model)):
        # the math of an event may use what a CellML model cannot express,
        # e.g. a factorial: the model is built again without the events
        without_events = dataclasses.replace(formulas, events=[])
        other, other_units = _build_model(mid, model_sbml, without_events)
        if not cellml.errors(cellml.validate_model(other)):
            for event in formulas.events:
                logger.warning(
                    "Event '%s' is not converted, its math is not valid CellML.",
                    event.sid,
                )
            model, cellml_units = other, other_units

    assignment: libsbml.InitialAssignment
    for assignment in model_sbml.getListOfInitialAssignments():
        logger.warning(
            "InitialAssignment for '%s' not converted, it was not evaluated.",
            assignment.getSymbol(),
        )
    return model, _metadata_elements(model_sbml, model, cellml_units, formulas)


def _set_ids(model: libcellml.Model) -> None:
    """Give the model, its variables and its units an id.

    CellML has no metadata, an `id` is what external metadata points at
    (`sbml2cellml.metadata`). A variable has its name as id, which is unique
    in the single component; units are `units_<name>` and the model has its
    name, both with a numeric suffix when the id is taken.
    """
    component: libcellml.Component = model.component(COMPONENT_ID)
    used: set[str] = set()
    for k in range(component.variableCount()):
        variable: libcellml.Variable = component.variable(k)
        variable.setId(variable.name())
        used.add(variable.name())
    for k in range(model.unitsCount()):
        units: libcellml.Units = model.units(k)
        units.setId(unique_sid(f"units_{units.name()}", used))
    model.setId(unique_sid(model.name(), used))


#: an expansion of libsbml: the option of the conversion, what it expands, what
#: happens to what is not expanded, and the count of what is left to expand
FUNCTION_DEFINITIONS = (
    "expandFunctionDefinitions",
    "Function definitions",
    "their calls remain",
    libsbml.Model.getNumFunctionDefinitions,
)
INITIAL_ASSIGNMENTS = (
    "expandInitialAssignments",
    "Initial assignments",
    "they are not converted",
    libsbml.Model.getNumInitialAssignments,
)


def _expand(
    doc: libsbml.SBMLDocument,
    mid: str,
    recursive: list[str],
    expansion: tuple[str, str, str, Callable[[libsbml.Model], int]],
) -> None:
    """Expand the function definitions or the initial assignments with libsbml.

    The calls of function definitions are replaced by the function bodies
    (`FUNCTION_DEFINITIONS`), the initial assignments evaluated to initial
    values (`INITIAL_ASSIGNMENTS`). libsbml refuses an invalid document (e.g.
    a call of an undefined function) and crashes on a recursive function
    definition read from a file, which is therefore checked first. The initial
    assignments are evaluated `_without_rate_rules`; libsbml leaves the ones
    which are NaN, see `_assign_nan`. What is
    not expanded stays, with a warning: the calls, which the validation of
    the CellML reports as unknown names, and the initial assignments, which
    are not converted.

    Args:
        doc: the SBML document, converted in place.
        mid: id of the model, for the log.
        recursive: ids of the recursive function definitions of the model.
        expansion: `FUNCTION_DEFINITIONS` or `INITIAL_ASSIGNMENTS`.
    """
    option, what, consequence, count_of = expansion
    count = count_of(doc.getModel())
    if count == 0:
        return
    if recursive:
        logger.warning(
            "%s of '%s' could not be expanded, %s: recursive function definitions %s",
            what,
            mid,
            consequence,
            ", ".join(recursive),
        )
        return
    properties = libsbml.ConversionProperties()
    properties.addOption(option, True)
    if expansion is INITIAL_ASSIGNMENTS:
        with _without_rate_rules(doc):
            status = doc.convert(properties)
            _assign_nan(doc.getModel())
    else:
        # the calls in the rate rules are expanded too
        status = doc.convert(properties)
    # libsbml may expand a part and report a failure, e.g. an initial
    # assignment to NaN, which it cannot evaluate
    left = count_of(doc.getModel())
    if left:
        logger.warning(
            "%s of '%s' could not be expanded (%d of %d), %s: %s",
            what,
            mid,
            left,
            count,
            consequence,
            libsbml.OperationReturnValue_toString(status),
        )
    if left < count:
        logger.info("Expanded %d %s of '%s'", count - left, what.lower(), mid)


def _drop_initial_assignments_without_math(model_sbml: libsbml.Model) -> None:
    """Remove the initial assignments without math, which have no effect.

    SBML allows them since L3V2; libsbml reports a failure for them when it
    expands the initial assignments.
    """
    for k in reversed(range(model_sbml.getNumInitialAssignments())):
        assignment: libsbml.InitialAssignment = model_sbml.getInitialAssignment(k)
        if not assignment.isSetMath():
            logger.info(
                "InitialAssignment for '%s' has no math and is ignored",
                assignment.getSymbol(),
            )
            model_sbml.removeInitialAssignment(k)


def _assign_nan(model_sbml: libsbml.Model) -> None:
    """Set the variables of the initial assignments which are NaN, in place.

    libsbml leaves an initial assignment which it evaluates to NaN, the value
    of the formula (`NaN`, `0 / 0`, a formula with a variable which is NaN)
    as well as the sign of a formula it cannot evaluate. The value is NaN
    when libsbml knows all of the formula: no call of a function definition,
    no rateOf or delay symbol and only ids of compartments, parameters,
    species and species references, none of which has an initial assignment
    libsbml cannot evaluate. Such an assignment is removed and its variable
    set to NaN (see `_non_finite_initial_values`), the others stay.

    Args:
        model_sbml: the SBML model after the expansion of the initial
            assignments, without its rate rules (`_without_rate_rules`).
    """
    left: dict[str, libsbml.ASTNode] = {
        assignment.getSymbol(): assignment.getMath()
        for assignment in model_sbml.getListOfInitialAssignments()
    }
    names_of: dict[str, set[str]] = {}
    for sid, formula in left.items():
        names_of[sid] = set()
        _collect_names(formula, libsbml.AST_NAME, names_of[sid])
    known = {
        sid
        for sid, formula in left.items()
        if _is_known(model_sbml, formula, names_of[sid])
    }
    shrinks = True
    while shrinks:
        unknown = set(left) - known
        through_unknown = {sid for sid in known if names_of[sid] & unknown}
        known -= through_unknown
        shrinks = bool(through_unknown)

    libsbml.SBMLTransforms.mapComponentValues(model_sbml)
    values = {
        sid: libsbml.SBMLTransforms.evaluateASTNode(left[sid], model_sbml)
        for sid in known
    }
    libsbml.SBMLTransforms.clearComponentValues(model_sbml)
    for sid, value in values.items():
        if not math.isnan(value):
            continue
        _set_quantity(model_sbml.getElementBySId(sid), math.nan)
        model_sbml.removeInitialAssignment(sid)
        logger.info("%s = NaN (initial assignment)", sid)


#: nodes of a formula whose value libsbml does not know
_UNKNOWN_NODES = (
    libsbml.AST_FUNCTION,
    libsbml.AST_FUNCTION_RATE_OF,
    libsbml.AST_FUNCTION_DELAY,
)


def _is_known(
    model_sbml: libsbml.Model, formula: libsbml.ASTNode, ids: set[str]
) -> bool:
    """Whether libsbml knows the value of every part of a formula.

    Args:
        model_sbml: the SBML model.
        formula: the formula.
        ids: the ids the formula uses.
    """
    names: set[str] = set()
    for node_type in _UNKNOWN_NODES:
        _collect_names(formula, node_type, names)
    return not names and all(
        isinstance(
            model_sbml.getElementBySId(sid),
            libsbml.Compartment
            | libsbml.Parameter
            | libsbml.Species
            | libsbml.SpeciesReference,
        )
        for sid in ids
    )


@contextmanager
def _without_rate_rules(doc: libsbml.SBMLDocument) -> Generator[None]:
    """Take the rate rules out of the model while libsbml evaluates formulas.

    libsbml evaluates a variable without a value yet (it has an initial
    assignment, or its value is NaN) by the math of its rule, also of a rate
    rule: the rate becomes the value, and libsbml crashes when the rate depends
    on the variable. The rate rules go back to the end of the rules, in their
    order; the converter reads the formulas of the rules before
    (`_collect_formulas`).

    Args:
        doc: the SBML document; its model may be replaced meanwhile.

    Raises:
        SBML2CellMLConversionError: if libsbml does not take a rule back.
    """
    model_sbml: libsbml.Model = doc.getModel()
    rules: list[libsbml.Rule] = [
        model_sbml.removeRule(k)
        for k in reversed(range(model_sbml.getNumRules()))
        if model_sbml.getRule(k).isRate()
    ]
    try:
        yield
    finally:
        model_sbml = doc.getModel()
        for rule in reversed(rules):
            status: int = model_sbml.addRule(rule)
            if status != libsbml.LIBSBML_OPERATION_SUCCESS:
                raise SBML2CellMLConversionError(
                    f"Rate rule for '{rule.getVariable()}' could not be added: "
                    f"{libsbml.OperationReturnValue_toString(status)}"
                )


@dataclass(frozen=True)
class _Amount:
    """The variable of the amount of a species in concentration."""

    #: id of the variable of the amount
    variable: str
    #: id of the compartment of the species
    compartment: str


@dataclass
class _Event:
    """An SBML event as the resets of a CellML model.

    CellML applies a reset when its test variable reaches its test value:
    the variable `trigger` is 1 while the condition of the event holds and
    0 otherwise, and every assignment of the event is a reset which fires
    when it becomes 1.
    """

    #: id of the event, for the log
    sid: str
    #: id of the variable which is 1 while the condition holds
    trigger: str
    #: condition of the trigger
    condition: libsbml.ASTNode
    #: right-hand side by the id of the variable an assignment sets
    assignments: dict[str, libsbml.ASTNode]
    #: priority of the event when it is a number, 0 without one; CellML
    #: applies the lowest order first and SBML the highest priority
    priority: float = 0.0


@dataclass
class _Formulas:
    """The formulas of a model as libsbml ASTs, without rateOf symbols."""

    #: right-hand side by the id of the variable an assignment rule sets
    assignment_rules: dict[str, libsbml.ASTNode]
    #: right-hand side of `d x / d time` by the id of a rate rule target
    rate_rules: dict[str, libsbml.ASTNode]
    #: right-hand side of `d species / d time` from the reactions
    reaction_terms: dict[str, libsbml.ASTNode]
    #: rate by reaction id
    rates: dict[str, libsbml.ASTNode]
    #: variable id of every local parameter, by reaction and parameter id
    local_ids: dict[str, dict[str, str]]
    #: formula of `0 = formula` by the id of the variable the rule determines
    algebraic_rules: dict[str, libsbml.ASTNode]
    #: variable of the amount by the id of a species in concentration whose
    #: compartment changes
    amounts: dict[str, _Amount]
    #: name of the variable of integration, `TIME_ID` unless the model has
    #: an element of that id
    time_id: str = TIME_ID
    #: name of the state of a model whose formulas use time without a
    #: differential equation, `None` for every other model
    time_state: str | None = None
    #: the events of the model, which become resets
    events: list["_Event"] = field(default_factory=list)
    #: the variable of a stoichiometry which a `<stoichiometryMath>`
    #: computes, by the reaction, the role and the index of its reference
    stoichiometries: dict[tuple[str, str, int], str] = field(default_factory=dict)

    @property
    def computed(self) -> set[str]:
        """Ids which an assignment or algebraic rule computes."""
        return set(self.assignment_rules) | set(self.algebraic_rules)

    @property
    def derivatives(self) -> dict[str, libsbml.ASTNode]:
        """Right-hand side of `d x / d time` by id, what `rateOf(x)` stands for.

        The concentration `S = A / C` of a species with a variable of its
        amount has the rate `(dA/dt - S * dC/dt) / C`.
        """
        derivatives = {**self.rate_rules, **self.reaction_terms}
        for sid, amount in self.amounts.items():
            compartment = astnodes.name(amount.compartment)
            dilution = astnodes.apply(
                libsbml.AST_TIMES,
                astnodes.name(sid),
                astnodes.apply(libsbml.AST_FUNCTION_RATE_OF, compartment),
            )
            # the reaction terms of the amount, or the rate rule of the
            # concentration which became the rate of the amount
            rate = self.reaction_terms.get(amount.variable)
            if rate is None:
                rate = self.rate_rules.get(amount.variable, astnodes.number(0.0))
            derivatives[sid] = astnodes.apply(
                libsbml.AST_DIVIDE,
                astnodes.apply(libsbml.AST_MINUS, rate, dilution),
                compartment,
            )
        return derivatives


def _collect_formulas(model_sbml: libsbml.Model) -> _Formulas:
    """Collect the formulas of the rules and reactions of a model.

    They do not depend on the initial values, so they can be collected before
    the initial assignments are evaluated. CellML has no rateOf: it is
    replaced by the right-hand side it stands for.
    """
    assignment_rules, rate_rules, algebraic = _collect_rules(model_sbml)
    model_sbml.populateAllElementIdList()
    ids: libsbml.IdList = model_sbml.getAllElementIdList()
    element_ids = {ids.at(k) for k in range(ids.size())}
    # a compartment, species, parameter, reaction or species reference may
    # be called `time`, the variable of integration takes another name then
    # (the ids of the unit definitions are no variables)
    time_id = unique_sid(TIME_ID, _variable_ids(model_sbml))
    used = element_ids | {time_id}
    # a stoichiometry which a formula of level 1 or 2 computes is the
    # equation of a variable, as the assignment rule of a species reference
    # of level 3 is
    stoichiometries, stoichiometry_names = _stoichiometries(model_sbml, used)
    assignment_rules.update(stoichiometries)
    algebraic_rules = _match_algebraic_rules(
        model_sbml, algebraic, set(assignment_rules) | set(rate_rules)
    )
    local_ids = _local_parameter_ids(model_sbml, used)
    changing = _changing(
        model_sbml, assignment_rules, set(rate_rules) | set(algebraic_rules)
    )
    amounts = _amounts(
        model_sbml,
        set(assignment_rules) | set(algebraic_rules),
        set(rate_rules),
        changing,
        used,
    )
    _rate_rules_of_amounts(rate_rules, amounts)
    rates = _kinetic_laws(model_sbml, local_ids)
    reaction_terms = _collect_reaction_terms(
        model_sbml, rates, amounts, stoichiometry_names
    )
    # CellML knows the variable of integration only from a differential
    # equation: a model whose formulas use time without one gets a state
    # which integrates it, `d time_state / d time = 1`
    time_state = (
        unique_sid(f"{time_id}_state", used)
        if not rate_rules and not reaction_terms and _uses_time(model_sbml)
        else None
    )
    result = _Formulas(
        assignment_rules,
        rate_rules,
        reaction_terms,
        rates,
        local_ids,
        algebraic_rules,
        amounts,
        time_id,
        time_state,
        _collect_events(model_sbml, used),
        stoichiometry_names,
    )
    derivatives = result.derivatives
    for formulas in (
        assignment_rules,
        rate_rules,
        reaction_terms,
        rates,
        algebraic_rules,
        *(event.assignments for event in result.events),
    ):
        for key, formula in formulas.items():
            formulas[key] = _expand_rate_of(formula, derivatives, result.computed)
    for event in result.events:
        event.condition = _expand_rate_of(event.condition, derivatives, result.computed)
    return result


def _rate_of_in_initial_assignments(
    model_sbml: libsbml.Model, formulas: _Formulas
) -> None:
    """Replace the rateOf symbols of the initial assignments, in place.

    libsbml cannot evaluate a rateOf; replaced by the right-hand side it
    stands for, the initial assignment is evaluated like any other. A rate
    with a local parameter stays unevaluated, the variable of the local
    parameter is not part of the SBML model.
    """
    derivatives = formulas.derivatives
    assignment: libsbml.InitialAssignment
    for assignment in model_sbml.getListOfInitialAssignments():
        if not assignment.isSetMath():
            continue
        math: libsbml.ASTNode = assignment.getMath()
        if _uses_rate_of(math):
            assignment.setMath(_expand_rate_of(math, derivatives, formulas.computed))


def _collect_names(
    node: libsbml.ASTNode | None, node_type: int, names: set[str]
) -> None:
    """Collect the names of the nodes of a type in a formula.

    E.g. the functions it calls (`AST_FUNCTION`) or the ids it uses
    (`AST_NAME`).
    """
    if node is None:
        return
    if node.getType() == node_type:
        names.add(node.getName())
    for k in range(node.getNumChildren()):
        _collect_names(node.getChild(k), node_type, names)


def _recursive_functions(model_sbml: libsbml.Model) -> list[str]:
    """Ids of the function definitions which call themselves.

    A function is recursive when it reaches itself through its calls,
    directly or through other function definitions.

    Returns:
        The sorted ids of the recursive function definitions.
    """
    calls: dict[str, set[str]] = {}
    definition: libsbml.FunctionDefinition
    for definition in model_sbml.getListOfFunctionDefinitions():
        names: set[str] = set()
        _collect_names(definition.getMath(), libsbml.AST_FUNCTION, names)
        calls[definition.getId()] = names
    recursive = []
    for fid in sorted(calls):
        seen: set[str] = set()
        stack = list(calls[fid])
        while stack:
            name = stack.pop()
            if name == fid:
                recursive.append(fid)
                break
            if name not in seen:
                seen.add(name)
                stack.extend(calls.get(name, ()))
    return recursive


def _initial_value(sid: str, value: float | None, default: float = 1.0) -> float:
    """Replace an unset initial value by `default` with a warning.

    `value` is `None` when the SBML attribute is unset (libsbml returns NaN
    for an unset value, like for a value set to NaN, so the caller decides
    with `isSet...`); a value which is set is returned as it is, NaN and
    infinity included. The default is the value a simulator of the SBML
    model takes: the size of a compartment and a stoichiometry are 1, the
    initial amount of a species is 0.
    """
    if value is None:
        logger.warning("Initial value of '%s' is not set, using %s.", sid, default)
        return default
    return value


def _set_value(is_set: bool, value: float) -> float | None:
    """The value of an SBML attribute, `None` when it is unset."""
    return value if is_set else None


def _variable_units(
    model_sbml: libsbml.Model,
    cellml_units: CellMLUnits,
    formulas: _Formulas,
    reaction_ids: list[str],
    has_time: bool,
) -> dict[str, str]:
    """The units of the variables of a model with a complete unit annotation.

    Units which are not set are unknown in SBML, not dimensionless, so the
    units are converted for all variables or for none: a model in which
    some variables had units and the others were dimensionless would state
    units which the SBML model does not have.

    Args:
        model_sbml: the SBML model.
        cellml_units: the CellML units of the model.
        formulas: the formulas of the model, with the variables of the local
            parameters and of the amounts.
        reaction_ids: ids of the reactions which are variables of their rate.
        has_time: whether the model has the variable of integration.

    Returns:
        The name of the CellML units by variable id; empty when the units of
        a variable are unknown, which is logged.
    """
    units: dict[str, str | None] = {}
    if has_time:
        units[formulas.time_id] = cellml_units.time()
        if formulas.time_state is not None:
            units[formulas.time_state] = cellml_units.time()
    compartment: libsbml.Compartment
    for compartment in model_sbml.getListOfCompartments():
        units[compartment.getId()] = cellml_units.of_compartment(compartment)
    parameter: libsbml.Parameter
    for parameter in model_sbml.getListOfParameters():
        units[parameter.getId()] = cellml_units.of_parameter(parameter)
    species: libsbml.Species
    for species in model_sbml.getListOfSpecies():
        units[species.getId()] = cellml_units.of_species(species)
        if species.getId() in formulas.amounts:
            amount = formulas.amounts[species.getId()]
            units[amount.variable] = cellml_units.of_amount(species)
    for rid, ids in formulas.local_ids.items():
        klaw: libsbml.KineticLaw = model_sbml.getReaction(rid).getKineticLaw()
        for pid, vid in ids.items():
            units[vid] = cellml_units.of_parameter(klaw.getParameter(pid))
    reaction: libsbml.Reaction
    for reaction in model_sbml.getListOfReactions():
        for reference in [
            *reaction.getListOfReactants(),
            *reaction.getListOfProducts(),
        ]:
            if reference.isSetId():
                # a stoichiometry has no units
                units[reference.getId()] = UNITS_ID
    for name in formulas.stoichiometries.values():
        units[name] = UNITS_ID
    for rid in reaction_ids:
        units[rid] = cellml_units.of_reaction()

    missing = sorted(vid for vid, name in units.items() if name is None)
    if not missing:
        logger.info("Unit annotation of '%s' is complete", model_sbml.getId())
        return {vid: name for vid, name in units.items() if name is not None}
    if cellml_units.is_annotated:
        logger.warning(
            "Units of the variables not converted, the unit annotation is "
            "incomplete: %s%s have no units.",
            ", ".join(missing[:MISSING_UNITS_LOGGED]),
            ", ..." if len(missing) > MISSING_UNITS_LOGGED else "",
        )
    return {}


def _add_variable(
    component: libcellml.Component,
    sid: str,
    value: float | None,
    units: dict[str, str],
) -> None:
    """Add a variable to the component.

    `value` is its initial value, `None` for a variable an equation computes
    (the target of an assignment rule), which must not have one. `units` has
    the units of the variables (`_variable_units`), a variable without is
    dimensionless.
    """
    variable = libcellml.Variable(sid)
    variable.setUnits(units.get(sid, UNITS_ID))
    if value is not None:
        # a value of -0.0, which an evaluation of libsbml gives, is the zero
        # of the model
        variable.setInitialValue(value + 0.0)
    component.addVariable(variable)


def _add_compartments(
    component: libcellml.Component,
    model_sbml: libsbml.Model,
    assigned: set[str],
    units: dict[str, str],
) -> dict[str, float]:
    """Add the compartments as variables.

    Returns:
        The initial size of every compartment by id, which converts the
        initial values of its species. An assignment rule gives the size of
        its compartment at the start (the size attribute does not count);
        NaN when it cannot be evaluated.
    """
    sizes: dict[str, float] = {}
    compartment: libsbml.Compartment
    for compartment in model_sbml.getListOfCompartments():
        cid: str = compartment.getId()
        if cid in assigned:
            sizes[cid] = _value_at_start(model_sbml, cid)
            _add_variable(component, cid, None, units)
        else:
            sizes[cid] = _initial_value(
                cid, _set_value(compartment.isSetSize(), compartment.getSize())
            )
            _add_variable(component, cid, sizes[cid], units)
        logger.info("'%s' variable for compartment", cid)
    return sizes


def _value_at_start(model_sbml: libsbml.Model, sid: str) -> float:
    """The value of a variable at the start, evaluated by libsbml.

    libsbml takes the value of the target of an assignment rule from the
    rule. The formulas are evaluated `_without_rate_rules`.

    Returns:
        The value, NaN when libsbml cannot evaluate it (e.g. a rule which
        uses a variable without a value).
    """
    with _without_rate_rules(model_sbml.getSBMLDocument()):
        libsbml.SBMLTransforms.mapComponentValues(model_sbml)
        value: float = libsbml.SBMLTransforms.evaluateASTNode(
            astnodes.name(sid), model_sbml
        )
        libsbml.SBMLTransforms.clearComponentValues(model_sbml)
    return value


def _add_parameters(
    component: libcellml.Component,
    model_sbml: libsbml.Model,
    assigned: set[str],
    units: dict[str, str],
) -> None:
    """Add the parameters as variables."""
    parameter: libsbml.Parameter
    for parameter in model_sbml.getListOfParameters():
        pid: str = parameter.getId()
        value = (
            None
            if pid in assigned
            else _initial_value(
                pid, _set_value(parameter.isSetValue(), parameter.getValue())
            )
        )
        _add_variable(component, pid, value, units)
        logger.info("'%s' variable for parameter", pid)


def _add_species(
    component: libcellml.Component,
    model_sbml: libsbml.Model,
    compartment_sizes: dict[str, float],
    assigned: set[str],
    amounts: dict[str, _Amount],
    units: dict[str, str],
) -> None:
    """Add the species as variables.

    A species with `hasOnlySubstanceUnits` is a variable in amount, every other
    species a variable in concentration; the initial value is converted with
    the size of the compartment when it is given in the other quantity. A
    species an assignment rule sets has no initial value. A species in
    concentration with a variable of its amount (`amounts`) has none either,
    the initial value in amount goes to that variable.

    """
    species: libsbml.Species
    for species in model_sbml.getListOfSpecies():
        sid: str = species.getId()
        cid: str = species.getCompartment()
        amount = species.getHasOnlySubstanceUnits() or sid in amounts

        initial: float | None
        if sid in assigned:
            initial = None
        elif species.isSetInitialAmount():
            value = _initial_value(sid, species.getInitialAmount())
            initial = value if amount else value / _size(cid, sid, compartment_sizes)
        elif species.isSetInitialConcentration():
            value = _initial_value(sid, species.getInitialConcentration())
            initial = value * _size(cid, sid, compartment_sizes) if amount else value
        else:
            # a species without an initial amount or concentration has none
            # in SBML; a simulator of the model starts it at zero
            initial = _initial_value(sid, None, default=0.0)
        if sid in amounts:
            _add_variable(component, sid, None, units)
            _add_variable(component, amounts[sid].variable, initial, units)
            logger.info(
                "'%s' variable for the amount of species '%s'",
                amounts[sid].variable,
                sid,
            )
        else:
            _add_variable(component, sid, initial, units)
        logger.info("'%s' variable for species", sid)


def _size(cid: str, sid: str, compartment_sizes: dict[str, float]) -> float:
    """Size of a compartment for the conversion of a species' initial value.

    Only the size of a compartment which an assignment rule sets can be unset
    (NaN); 1.0 is used then, with a warning.
    """
    size = compartment_sizes[cid]
    if math.isnan(size):
        logger.warning(
            "Size of compartment '%s' is not set, using 1.0 to convert the "
            "initial value of '%s'.",
            cid,
            sid,
        )
        return 1.0
    return size


def _collect_rules(
    model_sbml: libsbml.Model,
) -> tuple[
    dict[str, libsbml.ASTNode], dict[str, libsbml.ASTNode], list[libsbml.ASTNode]
]:
    """Collect the rules as formulas.

    Returns:
        The assignment rules and the rate rules, formula by variable id, and
        the formulas of the algebraic rules.
    """
    assignment_rules: dict[str, libsbml.ASTNode] = {}
    rate_rules: dict[str, libsbml.ASTNode] = {}
    algebraic_rules: list[libsbml.ASTNode] = []
    rule: libsbml.Rule
    for rule in model_sbml.getListOfRules():
        if not rule.isSetMath():
            # allowed since SBML L3V2, the rule has no effect
            logger.info("Rule for '%s' has no math and is ignored", rule.getVariable())
            continue
        formula: libsbml.ASTNode = rule.getMath().deepCopy()
        if rule.getTypeCode() == libsbml.SBML_ASSIGNMENT_RULE:
            assignment_rules[rule.getVariable()] = formula
        elif rule.getTypeCode() == libsbml.SBML_RATE_RULE:
            rate_rules[rule.getVariable()] = formula
        else:
            algebraic_rules.append(formula)
    return assignment_rules, rate_rules, algebraic_rules


def _match_algebraic_rules(
    model_sbml: libsbml.Model, rules: list[libsbml.ASTNode], determined: set[str]
) -> dict[str, libsbml.ASTNode]:
    """Match every algebraic rule with the variable it determines.

    An algebraic rule `0 = formula` determines a variable of its formula
    which nothing else determines: a compartment, parameter, species or
    species reference which is not constant, not the target of another rule
    and not a species changed by reactions. CellML does not name the variable
    an implicit equation determines, the converter has to know it (see
    `_constants_of_algebraic_rules`); a maximum matching of rules and
    variables finds it when several rules share candidates.

    Args:
        model_sbml: the SBML model.
        rules: formulas of the algebraic rules.
        determined: ids which assignment and rate rules determine.

    Returns:
        The formula of the algebraic rule by the id of the variable it
        determines. A rule without such a variable is left out, with a
        warning.
    """
    reacting: set[str] = set()
    reaction: libsbml.Reaction
    for reaction in model_sbml.getListOfReactions():
        for reference in [
            *reaction.getListOfReactants(),
            *reaction.getListOfProducts(),
        ]:
            if not model_sbml.getSpecies(reference.getSpecies()).getBoundaryCondition():
                reacting.add(reference.getSpecies())

    def free(sid: str) -> bool:
        element = model_sbml.getElementBySId(sid)
        return (
            isinstance(
                element,
                libsbml.Compartment
                | libsbml.Parameter
                | libsbml.Species
                | libsbml.SpeciesReference,
            )
            and not element.getConstant()
            and sid not in determined
            and sid not in reacting
        )

    candidates: list[list[str]] = []
    for formula in rules:
        names: set[str] = set()
        _collect_names(formula, libsbml.AST_NAME, names)
        candidates.append(sorted(sid for sid in names if free(sid)))

    rule_of: dict[str, int] = {}

    def assign(rule: int, seen: set[str]) -> bool:
        """Give the rule a variable, moving other rules to free one (Kuhn)."""
        for sid in candidates[rule]:
            if sid in seen:
                continue
            seen.add(sid)
            if sid not in rule_of or assign(rule_of[sid], seen):
                rule_of[sid] = rule
                return True
        return False

    for k, formula in enumerate(rules):
        if not assign(k, set()):
            logger.warning(
                "AlgebraicRule '%s' not converted, it determines no variable.",
                astnodes.text(formula),
            )
    # a rule follows the rules which determine the other unknowns it uses:
    # the libcellml analyser finds a model with guesses overconstrained
    # otherwise
    variable_of = {k: sid for sid, k in rule_of.items()}
    ordered: list[int] = []

    def visit(rule: int, path: tuple[int, ...]) -> None:
        if rule in ordered or rule in path:
            return
        for sid in candidates[rule]:
            if sid != variable_of[rule] and sid in rule_of:
                visit(rule_of[sid], (*path, rule))
        ordered.append(rule)

    for k in sorted(variable_of):
        visit(k, ())
    return {variable_of[k]: rules[k] for k in ordered}


def _local_parameter_ids(
    model_sbml: libsbml.Model, used: set[str]
) -> dict[str, dict[str, str]]:
    """Variable ids of the local parameters of the kinetic laws.

    A local parameter is only visible in its kinetic law, and several
    reactions may have one of the same id. Each becomes a variable of its
    own, `<reaction>_<parameter>`, with a numeric suffix when that id is
    taken by another element of the model.

    Args:
        model_sbml: the SBML model.
        used: ids taken so far, the new ids are added.

    Returns:
        The variable id of every local parameter, by reaction id and local
        parameter id.
    """
    local_ids: dict[str, dict[str, str]] = {}
    reaction: libsbml.Reaction
    for reaction in model_sbml.getListOfReactions():
        klaw: libsbml.KineticLaw | None = reaction.getKineticLaw()
        if klaw is None:
            continue
        # the local parameters in level 3, the parameters of the kinetic law
        # in level 2
        for k in range(klaw.getNumParameters()):
            pid: str = klaw.getParameter(k).getId()
            vid = unique_sid(f"{reaction.getId()}_{pid}", used)
            local_ids.setdefault(reaction.getId(), {})[pid] = vid
    return local_ids


def _changing(
    model_sbml: libsbml.Model,
    assignment_rules: dict[str, libsbml.ASTNode],
    solved: set[str],
) -> set[str]:
    """Ids of the variables which change in time.

    The targets of rate and algebraic rules, the species which reactions
    change, the rates of the reactions, the targets of the assignments of
    the events, the targets of assignment rules which
    use time or a variable which changes, and the concentration of a species
    in a compartment which changes. An assignment rule of constants (e.g. a
    volume from a body weight) does not change its target.

    Args:
        model_sbml: the SBML model.
        assignment_rules: formula by the id of the target.
        solved: ids which rate and algebraic rules determine.
    """
    changing = set(solved)
    reaction: libsbml.Reaction
    for reaction in model_sbml.getListOfReactions():
        changing.add(reaction.getId())
        for reference in [
            *reaction.getListOfReactants(),
            *reaction.getListOfProducts(),
        ]:
            if not model_sbml.getSpecies(reference.getSpecies()).getBoundaryCondition():
                changing.add(reference.getSpecies())

    # an event assignment changes its target when it fires, which is what
    # makes the concentration of a species in such a compartment change
    event: libsbml.Event
    for event in model_sbml.getListOfEvents():
        assignment: libsbml.EventAssignment
        for assignment in event.getListOfEventAssignments():
            changing.add(assignment.getVariable())

    names_of: dict[str, set[str]] = {}
    for vid, formula in assignment_rules.items():
        names: set[str] = set()
        _collect_names(formula, libsbml.AST_NAME, names)
        times: set[str] = set()
        _collect_names(formula, libsbml.AST_NAME_TIME, times)
        if times:
            changing.add(vid)
        names_of[vid] = names

    grows = True
    while grows:
        size = len(changing)
        changing |= {vid for vid, names in names_of.items() if names & changing}
        species: libsbml.Species
        for species in model_sbml.getListOfSpecies():
            if (
                species.getCompartment() in changing
                and not species.getHasOnlySubstanceUnits()
            ):
                changing.add(species.getId())
        grows = len(changing) > size
    return changing


def _amounts(
    model_sbml: libsbml.Model,
    computed: set[str],
    rate_rules: set[str],
    changing: set[str],
    used: set[str],
) -> dict[str, _Amount]:
    """The species in concentration which need a variable of their amount.

    Reactions change the amount of a species, and a species nothing changes
    keeps its amount, also a constant one or a boundary species. The
    concentration follows when the size of the compartment changes, so a
    species in a compartment which changes becomes the equation
    `species = amount / compartment` with the amount as the variable the
    reactions change. A species which a rule determines itself keeps its
    concentration as its quantity, which the rule gives (its value or the
    rate of it), unless an event sets the size of its compartment: the
    amount of the species does not change then, where its concentration
    follows the size, so such a species gets the amount as well and a rate
    rule becomes the rate of the amount
    (`d amount / d time = rate * compartment + species * rateOf(compartment)`,
    `_rate_rules_of_amounts`). The size a rule gives changes
    continuously, where both forms are the same equations.

    Args:
        model_sbml: the SBML model.
        computed: ids which assignment and algebraic rules determine.
        rate_rules: ids which rate rules determine.
        changing: ids of the variables which change in time (`_changing`).
        used: ids taken so far, the new ids are added.

    Returns:
        The variable `<species>_amount` (with a numeric suffix when that id
        is taken) by species id.
    """
    # the targets of the event assignments: the size of such a compartment
    # jumps, where the amount of a species in it stays
    assigned_by_events = {
        assignment.getVariable()
        for event in model_sbml.getListOfEvents()
        for assignment in event.getListOfEventAssignments()
    }
    amounts: dict[str, _Amount] = {}
    species: libsbml.Species
    for species in model_sbml.getListOfSpecies():
        sid: str = species.getId()
        cid: str = species.getCompartment()
        if species.getHasOnlySubstanceUnits() or sid in computed or cid not in changing:
            continue
        if sid in rate_rules and cid not in assigned_by_events:
            continue
        amounts[sid] = _Amount(unique_sid(f"{sid}_amount", used), cid)
    return amounts


def _rate_rules_of_amounts(
    rate_rules: dict[str, libsbml.ASTNode], amounts: dict[str, _Amount]
) -> None:
    """Move the rate rule of a species with an amount to its amount.

    The rule gives the rate of the concentration `S = A / C`, which the
    amount integrates as `dA/dt = rate * C + S * rateOf(C)`
    (`rateOf(C)` is replaced by the rate of the compartment and is 0 for a
    compartment only an event sets).

    Args:
        rate_rules: the rate rules by the id of their target, changed in
            place.
        amounts: the variable of the amount by species id.
    """
    for sid, amount in amounts.items():
        rate = rate_rules.pop(sid, None)
        if rate is None:
            continue
        compartment = astnodes.name(amount.compartment)
        rate_rules[amount.variable] = astnodes.apply(
            libsbml.AST_PLUS,
            astnodes.apply(libsbml.AST_TIMES, rate, compartment),
            astnodes.apply(
                libsbml.AST_TIMES,
                astnodes.name(sid),
                astnodes.apply(libsbml.AST_FUNCTION_RATE_OF, compartment),
            ),
        )


def _add_local_parameters(
    component: libcellml.Component,
    model_sbml: libsbml.Model,
    local_ids: dict[str, dict[str, str]],
    units: dict[str, str],
) -> None:
    """Add the local parameters of the kinetic laws as variables (`local_ids`)."""
    for rid, ids in local_ids.items():
        klaw: libsbml.KineticLaw = model_sbml.getReaction(rid).getKineticLaw()
        for pid, vid in ids.items():
            local = klaw.getParameter(pid)
            value = _initial_value(
                vid, _set_value(local.isSetValue(), local.getValue())
            )
            _add_variable(component, vid, value, units)
            logger.info("'%s' variable for local parameter '%s' of '%s'", vid, pid, rid)


def _add_species_references(
    component: libcellml.Component,
    model_sbml: libsbml.Model,
    assigned: set[str],
    units: dict[str, str],
    stoichiometries: dict[tuple[str, str, int], str],
) -> None:
    """Add the species references with an id as variables.

    The id of a species reference stands for its stoichiometry in formulas,
    and rules may set it; the variable has the stoichiometry as initial
    value, none when an assignment rule sets it. A reference of level 1 or 2
    whose `<stoichiometryMath>` computes the stoichiometry gets the variable
    of that formula (`stoichiometries`), which an equation computes.
    """
    reaction: libsbml.Reaction
    for reaction in model_sbml.getListOfReactions():
        rid: str = reaction.getId()
        for role, references in (
            ("reactant", reaction.getListOfReactants()),
            ("product", reaction.getListOfProducts()),
        ):
            reference: libsbml.SpeciesReference
            for index, reference in enumerate(references):
                if not reference.isSetId():
                    name = stoichiometries.get((rid, role, index))
                    if name is not None:
                        _add_variable(component, name, None, units)
                        logger.info(
                            "'%s' variable for a stoichiometry of '%s'", name, rid
                        )
                    continue
                vid: str = reference.getId()
                value = (
                    None
                    if vid in assigned
                    else _initial_value(
                        vid,
                        _set_value(
                            reference.isSetStoichiometry(),
                            reference.getStoichiometry(),
                        ),
                    )
                )
                _add_variable(component, vid, value, units)
                logger.info("'%s' variable for a stoichiometry of '%s'", vid, rid)


def _kinetic_laws(
    model_sbml: libsbml.Model, local_ids: dict[str, dict[str, str]]
) -> dict[str, libsbml.ASTNode]:
    """The rate of every reaction with a kinetic law, amount per time.

    Returns:
        The formula of the kinetic law, its local parameters renamed to their
        variables (`local_ids`), by reaction id.
    """
    rates: dict[str, libsbml.ASTNode] = {}
    reaction: libsbml.Reaction
    for reaction in model_sbml.getListOfReactions():
        klaw: libsbml.KineticLaw | None = reaction.getKineticLaw()
        if klaw is None or not klaw.isSetMath():
            logger.warning(
                "Reaction '%s' has no kinetic law with math and is not converted.",
                reaction.getId(),
            )
            continue
        math: libsbml.ASTNode = klaw.getMath().deepCopy()
        for pid, vid in local_ids.get(reaction.getId(), {}).items():
            math.renameSIdRefs(pid, vid)
        rates[reaction.getId()] = math
    return rates


def _build_model(
    mid: str,
    model_sbml: libsbml.Model,
    formulas: _Formulas,
) -> tuple[libcellml.Model, CellMLUnits]:
    """Build the CellML model of the collected formulas.

    Args:
        mid: id of the model.
        model_sbml: the SBML model, after the conversions.
        formulas: the formulas of the model.

    Returns:
        The model and the CellML units of the SBML model, which the
        metadata of the units needs.
    """
    model = libcellml.Model(mid)
    component = libcellml.Component(COMPONENT_ID)
    model.addComponent(component)

    assignment_rules = formulas.assignment_rules
    rate_rules = formulas.rate_rules
    reaction_terms = formulas.reaction_terms
    rates = formulas.rates
    assigned = set(assignment_rules)
    # every reaction with a kinetic law is a variable of its rate
    reaction_ids = list(rates)
    # CellML knows the variable of integration only from a differential
    # equation, an unused one has an unknown type: the model is algebraic
    has_time = bool(rate_rules or reaction_terms or _uses_time(model_sbml))
    if not has_time:
        logger.info("No differential equation, '%s' is algebraic", mid)

    cellml_units = CellMLUnits(model_sbml, model)
    units = _variable_units(model_sbml, cellml_units, formulas, reaction_ids, has_time)
    number_units = cellml_units.number_units

    if has_time:
        _add_variable(component, formulas.time_id, None, units)
    if formulas.time_state is not None:
        logger.info(
            "d%s/dt = 1: no differential equation makes '%s' the variable of "
            "integration",
            formulas.time_state,
            formulas.time_id,
        )
        _add_variable(component, formulas.time_state, 0.0, units)
    compartment_sizes = _add_compartments(component, model_sbml, assigned, units)
    _add_parameters(component, model_sbml, assigned, units)
    _add_species(
        component, model_sbml, compartment_sizes, assigned, formulas.amounts, units
    )
    _add_local_parameters(component, model_sbml, formulas.local_ids, units)
    _add_species_references(
        component, model_sbml, assigned, units, formulas.stoichiometries
    )
    for rid in reaction_ids:
        _add_variable(component, rid, None, units)
    for event in formulas.events:
        _add_variable(component, event.trigger, None, units)

    parts: list[str] = []
    for vid, formula in assignment_rules.items():
        logger.info("%s = %s", vid, astnodes.text(formula))
        parts.append(
            mathml.mathml_for_assignment(
                vid, formula, number_units, time_id=formulas.time_id
            )
        )
    for sid, amount in formulas.amounts.items():
        formula = astnodes.apply(
            libsbml.AST_DIVIDE,
            astnodes.name(amount.variable),
            astnodes.name(amount.compartment),
        )
        logger.info("%s = %s (concentration of an amount)", sid, astnodes.text(formula))
        parts.append(mathml.mathml_for_assignment(sid, formula, number_units))
    for vid, formula in formulas.algebraic_rules.items():
        logger.info("0 = %s (determines %s)", astnodes.text(formula), vid)
        parts.append(
            mathml.mathml_for_algebraic(formula, number_units, time_id=formulas.time_id)
        )
    parts.extend(_constants_of_algebraic_rules(component, formulas))
    if formulas.time_state is not None:
        parts.append(
            mathml.mathml_for_diff(
                formulas.time_state,
                astnodes.number(1.0),
                formulas.time_id,
                number_units,
            )
        )
    for vid, formula in [*rate_rules.items(), *reaction_terms.items()]:
        logger.info("d%s/dt = %s", vid, astnodes.text(formula))
        parts.append(
            mathml.mathml_for_diff(vid, formula, formulas.time_id, number_units)
        )
    for rid in reaction_ids:
        logger.info("%s = %s (rate of reaction)", rid, astnodes.text(rates[rid]))
        parts.append(
            mathml.mathml_for_assignment(
                rid, rates[rid], number_units, time_id=formulas.time_id
            )
        )
    for event in formulas.events:
        condition = astnodes.apply(
            libsbml.AST_FUNCTION_PIECEWISE,
            astnodes.number(1.0),
            event.condition,
            astnodes.number(0.0),
        )
        logger.info(
            "%s = 1 while '%s' holds (event '%s')",
            event.trigger,
            astnodes.text(event.condition),
            event.sid,
        )
        parts.append(
            mathml.mathml_for_assignment(
                event.trigger, condition, number_units, time_id=formulas.time_id
            )
        )
    parts.extend(
        _non_finite_initial_values(component, set(rate_rules) | set(reaction_terms))
    )
    component.setMath(mathml.cellml_math(parts))
    _add_resets(component, formulas, number_units)
    model.linkUnits()
    _set_ids(model)

    return model, cellml_units


def _add_resets(
    component: libcellml.Component,
    formulas: _Formulas,
    number_units: mathml.UnitsNames,
) -> None:
    """Add the resets of the events of the model.

    Every assignment of an event is a reset which fires when the variable
    of its trigger reaches 1 (`_Event`). The assignment of a species in
    concentration whose compartment changes in time sets its amount, which
    is the state of the CellML model.

    Args:
        component: the component of the model.
        formulas: the formulas of the model, with its events.
        number_units: CellML units of the SBML units of a number.
    """
    order = 0
    # SBML applies the event of the highest priority first, CellML the reset
    # of the lowest order
    events = sorted(formulas.events, key=lambda event: -event.priority)
    for event in events:
        trigger = component.variable(event.trigger)
        for sid, formula in event.assignments.items():
            vid, value = sid, formula
            amount = formulas.amounts.get(sid)
            if amount is not None:
                vid = amount.variable
                value = astnodes.apply(
                    libsbml.AST_TIMES, formula, astnodes.name(amount.compartment)
                )
            variable = component.variable(vid)
            if variable is None:
                logger.warning(
                    "Event '%s' assigns '%s', which is no variable of the model: "
                    "the assignment is not converted.",
                    event.sid,
                    sid,
                )
                continue
            reset = libcellml.Reset()
            reset.setOrder(order)
            reset.setVariable(variable)
            reset.setTestVariable(trigger)
            reset.setTestValue(
                mathml.cellml_math(
                    [
                        mathml.mathml_for_assignment(
                            event.trigger,
                            astnodes.number(1.0),
                            number_units,
                            time_id=formulas.time_id,
                        )
                    ]
                )
            )
            reset.setResetValue(
                mathml.cellml_math(
                    [
                        mathml.mathml_for_assignment(
                            vid, value, number_units, time_id=formulas.time_id
                        )
                    ]
                )
            )
            component.addReset(reset)
            logger.info(
                "reset %d: %s = %s when %s is 1 (event '%s')",
                order,
                vid,
                astnodes.text(value),
                event.trigger,
                event.sid,
            )
            order += 1


def _collect_events(model_sbml: libsbml.Model, used: set[str]) -> list[_Event]:
    """The events of the model which become resets.

    An event with a delay becomes resets which fire when the trigger holds:
    CellML applies a reset when the test variable reaches the test value and
    has no counterpart for the delay, which the metadata of the conversion
    keeps (`sbml2cellml.metadata`), as it keeps the priority and the flags
    of the event.

    Args:
        model_sbml: the SBML model.
        used: ids taken so far, the variable of a trigger is added to it.

    Returns:
        One `_Event` per event which becomes resets.
    """
    events = []
    event: libsbml.Event
    for index, event in enumerate(model_sbml.getListOfEvents(), start=1):
        sid = event.getId() or f"event_{index}"
        trigger: libsbml.Trigger = event.getTrigger()
        if trigger is None or not trigger.isSetMath():
            logger.warning("Event '%s' has no trigger, it is not converted.", sid)
            continue
        delay: libsbml.Delay = event.getDelay()
        if delay is not None and delay.isSetMath():
            logger.warning(
                "Event '%s' has a delay, which a reset of CellML cannot express: "
                "the reset fires when the trigger holds, the delay is kept in the "
                "metadata of the conversion.",
                sid,
            )
            if _unsupported_math(delay.getMath()):
                logger.warning(
                    "Event '%s' has a delay CellML has no counterpart for: it is "
                    "not converted.",
                    sid,
                )
                continue
        assignments = {}
        assignment: libsbml.EventAssignment
        for assignment in event.getListOfEventAssignments():
            if assignment.isSetMath():
                assignments[assignment.getVariable()] = assignment.getMath().deepCopy()
        if _unsupported_math(trigger.getMath()) or any(
            _unsupported_math(formula) for formula in assignments.values()
        ):
            logger.warning(
                "Event '%s' uses math CellML has no counterpart for, a "
                "delay or a factorial: it is not converted.",
                sid,
            )
            continue
        if not assignments:
            logger.warning(
                "Event '%s' assigns nothing, it is not converted.",
                sid,
            )
            continue
        if not event.getUseValuesFromTriggerTime():
            logger.info(
                "Event '%s' uses the values of the time of the assignment, which "
                "a reset does as well.",
                sid,
            )
        if not trigger.getInitialValue():
            logger.warning(
                "Trigger of event '%s' has initialValue 'false', which a reset "
                "cannot express: it does not fire at the start time, the value is "
                "kept in the metadata of the conversion.",
                sid,
            )
        if not trigger.getPersistent():
            logger.warning(
                "Trigger of event '%s' is not persistent, which a reset cannot "
                "express: it fires whenever the trigger becomes true, the flag is "
                "kept in the metadata of the conversion.",
                sid,
            )
        events.append(
            _Event(
                sid,
                unique_sid(f"{sid}_trigger", used),
                trigger.getMath().deepCopy(),
                assignments,
                _priority(event),
            )
        )
    return events


#: operators of an SBML formula which no CellML model can express; a
#: `rateOf` is not among them, `_expand_rate_of` replaces it by the rate it
#: stands for, also in the formulas of an event
_UNSUPPORTED_MATH = frozenset(
    {
        libsbml.AST_FUNCTION_FACTORIAL,
        libsbml.AST_FUNCTION_DELAY,
    }
)


def _unsupported_math(node: libsbml.ASTNode | None) -> bool:
    """Whether a formula uses an operator CellML has no counterpart for.

    Args:
        node: root of the formula, `None` for a formula which is not set.

    Returns:
        Whether the formula or one of its children is such an operator.
    """
    if node is None:
        return False
    if node.getType() in _UNSUPPORTED_MATH:
        return True
    return any(
        _unsupported_math(node.getChild(k)) for k in range(node.getNumChildren())
    )


def _priority(event: libsbml.Event) -> float:
    """Priority of an event, 0 when it has none or none which is a number.

    Args:
        event: the SBML event.

    Returns:
        The value of the priority, which orders the resets of the events.
    """
    priority: libsbml.Priority = event.getPriority()
    if priority is None or not priority.isSetMath():
        return 0.0
    math_node: libsbml.ASTNode = priority.getMath()
    if math_node.isNumber():
        return float(math_node.getValue())
    logger.warning(
        "Priority of event '%s' is no number, the resets keep the order of the events.",
        event.getId(),
    )
    return 0.0


def _variable_ids(model_sbml: libsbml.Model) -> set[str]:
    """Ids of the SBML elements which become variables of the component.

    Args:
        model_sbml: the SBML model.

    Returns:
        The ids of the compartments, species, parameters, reactions and
        species references.
    """
    ids = {element.getId() for element in model_sbml.getListOfCompartments()}
    ids |= {element.getId() for element in model_sbml.getListOfSpecies()}
    ids |= {element.getId() for element in model_sbml.getListOfParameters()}
    reaction: libsbml.Reaction
    for reaction in model_sbml.getListOfReactions():
        ids.add(reaction.getId())
        reference: libsbml.SpeciesReference
        for reference in [
            *reaction.getListOfReactants(),
            *reaction.getListOfProducts(),
        ]:
            if reference.isSetId():
                ids.add(reference.getId())
    return ids


def _uses_time(model_sbml: libsbml.Model) -> bool:
    """Whether a rule, a kinetic law or an event uses the time symbol."""
    names: set[str] = set()
    rule: libsbml.Rule
    for rule in model_sbml.getListOfRules():
        _collect_names(rule.getMath(), libsbml.AST_NAME_TIME, names)
    reaction: libsbml.Reaction
    for reaction in model_sbml.getListOfReactions():
        if reaction.getKineticLaw() is not None:
            _collect_names(
                reaction.getKineticLaw().getMath(), libsbml.AST_NAME_TIME, names
            )
    event: libsbml.Event
    for event in model_sbml.getListOfEvents():
        trigger: libsbml.Trigger = event.getTrigger()
        if trigger is not None:
            _collect_names(trigger.getMath(), libsbml.AST_NAME_TIME, names)
        assignment: libsbml.EventAssignment
        for assignment in event.getListOfEventAssignments():
            _collect_names(assignment.getMath(), libsbml.AST_NAME_TIME, names)
    return bool(names)


def _quantity(element: libsbml.SBase) -> float | None:
    """The value of a compartment, parameter, species or species reference.

    A species has its concentration, its amount with `hasOnlySubstanceUnits`
    (what its id stands for in a formula); `None` when the value is unset.
    """
    if isinstance(element, libsbml.Compartment):
        return _set_value(element.isSetSize(), element.getSize())
    if isinstance(element, libsbml.Parameter):
        return _set_value(element.isSetValue(), element.getValue())
    if isinstance(element, libsbml.SpeciesReference):
        return _set_value(element.isSetStoichiometry(), element.getStoichiometry())
    if isinstance(element, libsbml.Species):
        if element.getHasOnlySubstanceUnits():
            return _set_value(element.isSetInitialAmount(), element.getInitialAmount())
        return _set_value(
            element.isSetInitialConcentration(), element.getInitialConcentration()
        )
    return None


def _set_quantity(element: libsbml.SBase, value: float) -> None:
    """Set the value `_quantity` reads."""
    if isinstance(element, libsbml.Compartment):
        element.setSize(value)
    elif isinstance(element, libsbml.Parameter):
        element.setValue(value)
    elif isinstance(element, libsbml.SpeciesReference):
        element.setStoichiometry(value)
    elif isinstance(element, libsbml.Species):
        if element.getHasOnlySubstanceUnits():
            element.setInitialAmount(value)
        else:
            element.unsetInitialAmount()
            element.setInitialConcentration(value)


def _solve_algebraic_rules(model_sbml: libsbml.Model, formulas: _Formulas) -> None:
    """Solve the algebraic rules at the start and set the values in the model.

    The solution is the best guess for the solver of the simulation, and the
    initial size of a compartment which an algebraic rule determines converts
    the initial values of its species. The rules are solved in their order
    (a rule follows the rules it depends on) with the secant method, the
    formulas evaluated by libsbml. A rule which cannot be solved keeps the
    SBML value of its variable.

    Args:
        model_sbml: the SBML model, the values are set in place.
        formulas: the formulas of the model.
    """
    for sid, node in formulas.algebraic_rules.items():
        element: libsbml.SBase = model_sbml.getElementBySId(sid)
        original = _quantity(element)

        def residual(
            value: float,
            element: libsbml.SBase = element,
            node: libsbml.ASTNode = node,
        ) -> float:
            _set_quantity(element, value)
            libsbml.SBMLTransforms.clearComponentValues(model_sbml)
            libsbml.SBMLTransforms.mapComponentValues(model_sbml)
            return libsbml.SBMLTransforms.evaluateASTNode(node, model_sbml)

        x0 = 1.0 if original is None else original
        with _without_rate_rules(model_sbml.getSBMLDocument()):
            solution = _secant(residual, x0)
        libsbml.SBMLTransforms.clearComponentValues(model_sbml)
        if solution is None:
            logger.info("Algebraic rule for '%s' not solved at the start", sid)
            if original is not None:
                _set_quantity(element, original)
            continue
        _set_quantity(element, solution)
        logger.info("%s = %s at the start (algebraic rule)", sid, solution)


def _secant(function: Callable[[float], float], x0: float) -> float | None:
    """A root of a function with the secant method, `None` without convergence."""
    x1 = x0 + max(abs(x0), 1.0) * 1e-3
    f0, f1 = function(x0), function(x1)
    for _ in range(50):
        if not (math.isfinite(f0) and math.isfinite(f1)):
            return None
        if f1 == 0.0 or abs(x1 - x0) <= 1e-14 * max(abs(x1), 1.0):
            return x1
        if f1 == f0:
            return None
        x0, x1, f0 = x1, x1 - f1 * (x1 - x0) / (f1 - f0), f1
        f1 = function(x1)
    return None


def _constants_of_algebraic_rules(
    component: libcellml.Component, formulas: _Formulas
) -> list[str]:
    """State the constants of the algebraic rules as equations.

    libcellml takes the variable of an implicit equation which has an
    initial value for its unknown, the value being the guess of the solver
    (without a guess the solver of libopencor starts at 0 and may give up).
    With a second such variable in the equation the model is
    underconstrained, so every other variable of an algebraic rule which is
    not a state loses its initial value to the equation `y = value`, and the
    unknown of one algebraic rule which another one uses loses its guess.
    A variable a reset writes loses it as well: libcellml reports the model
    as underconstrained otherwise (the resets of a model whose implicit
    equation uses such a variable do not reach the SBML of a roundtrip,
    which the test suite reports for the cases 01589 and 01592).

    Args:
        component: the component with the variables.
        formulas: the formulas of the model.

    Returns:
        The `apply` elements of the equations.
    """
    keep = (
        set(formulas.algebraic_rules)
        | set(formulas.rate_rules)
        | set(formulas.reaction_terms)
    )
    names: set[str] = set()
    for vid, formula in formulas.algebraic_rules.items():
        rule_names: set[str] = set()
        _collect_names(formula, libsbml.AST_NAME, rule_names)
        names |= rule_names
        # the unknown of another algebraic rule cannot be stated as a
        # constant, it loses its guess instead
        for other in (rule_names & set(formulas.algebraic_rules)) - {vid}:
            unknown: libcellml.Variable = component.variable(other)
            if unknown.initialValue():
                unknown.removeInitialValue()
                logger.info("%s has no guess, another algebraic rule uses it", other)
    parts: list[str] = []
    for name in sorted(names - keep):
        variable: libcellml.Variable | None = component.variable(name)
        if variable is None or not variable.initialValue():
            continue
        value: str = variable.initialValue()
        variable.removeInitialValue()
        logger.info("%s = %s (constant of an algebraic rule)", name, value)
        parts.append(
            mathml.mathml_for_assignment(
                name,
                astnodes.number(float(value)),
                number_units=variable.units().name(),
            )
        )
    return parts


#: the non-finite initial values as libcellml writes them
NON_FINITE = {"inf", "-inf", "nan"}


def _non_finite_initial_values(
    component: libcellml.Component, states: set[str]
) -> list[str]:
    """Replace infinite and NaN initial values by equations.

    CellML initial values are real numbers or variable references; a
    variable which is not a state and has an infinite or NaN initial value
    (from an SBML value or an initial assignment) gets the equation
    `v = INF` (or `-INF`, `NaN`) instead. A state keeps it, CellML cannot
    express it.

    Args:
        component: the component with the variables.
        states: ids of the variables which a differential equation defines.

    Returns:
        The `apply` elements of the equations.
    """
    parts: list[str] = []
    for k in range(component.variableCount()):
        variable: libcellml.Variable = component.variable(k)
        value: str = variable.initialValue()
        if value not in NON_FINITE or variable.name() in states:
            continue
        variable.removeInitialValue()
        logger.info("%s = %s (non-finite initial value)", variable.name(), value)
        parts.append(
            mathml.mathml_for_assignment(variable.name(), astnodes.number(float(value)))
        )
    return parts


def _uses_rate_of(node: libsbml.ASTNode) -> bool:
    """Whether a formula has a rateOf symbol."""
    return node.getType() == libsbml.AST_FUNCTION_RATE_OF or any(
        _uses_rate_of(node.getChild(k)) for k in range(node.getNumChildren())
    )


def _expand_rate_of(
    formula: libsbml.ASTNode,
    derivatives: dict[str, libsbml.ASTNode],
    assigned: set[str],
) -> libsbml.ASTNode:
    """Replace the rateOf symbols of a formula by the rates they stand for.

    `rateOf(x)` becomes the right-hand side of the differential equation of
    `x` (its rate rule or reaction terms, whose own rateOf symbols are
    replaced in turn) and 0 when `x` has none. It stays, with a warning, when
    the rate of `x` depends on itself or an assignment rule sets `x` (which
    SBML does not allow); the validation of the CellML reports it then.

    Args:
        formula: the formula, which is not changed.
        derivatives: right-hand side of `d x / d time` by id.
        assigned: ids which an assignment rule sets.

    Returns:
        The formula without the rateOf symbols which could be replaced.
    """
    if not _uses_rate_of(formula):
        return formula
    return _replace_rate_of(formula.deepCopy(), derivatives, assigned, ())


def _replace_rate_of(
    node: libsbml.ASTNode,
    derivatives: dict[str, libsbml.ASTNode],
    assigned: set[str],
    path: tuple[str, ...],
) -> libsbml.ASTNode:
    """The node with its rateOf symbols replaced, see `_expand_rate_of`.

    `path` holds the ids whose rates are being inserted, to detect a rate
    which depends on itself.
    """
    if node.getType() == libsbml.AST_FUNCTION_RATE_OF and node.getNumChildren() == 1:
        target: str = node.getChild(0).getName()
        if target in path:
            logger.warning(
                "rateOf(%s) not converted, the rate of '%s' depends on itself.",
                target,
                target,
            )
            return node
        if target in assigned:
            logger.warning(
                "rateOf(%s) not converted, '%s' is computed by a rule.",
                target,
                target,
            )
            return node
        rate: libsbml.ASTNode = (
            derivatives[target].deepCopy()
            if target in derivatives
            else astnodes.number(0.0)
        )
        return _replace_rate_of(rate, derivatives, assigned, (*path, target))
    for k in range(node.getNumChildren()):
        child: libsbml.ASTNode = node.getChild(k)
        replaced = _replace_rate_of(child, derivatives, assigned, path)
        if replaced is not child:
            node.replaceChild(k, replaced.deepCopy(), True)
    return node


def _stoichiometry_math(
    reference: libsbml.SpeciesReference,
) -> libsbml.ASTNode | None:
    """The formula of the `<stoichiometryMath>` of a species reference.

    Returns:
        The formula, `None` for a reference of level 3 and for one whose
        element has no mathematics.
    """
    if not reference.isSetStoichiometryMath():
        return None
    math: libsbml.ASTNode | None = reference.getStoichiometryMath().getMath()
    return math


def _stoichiometries(
    model_sbml: libsbml.Model, used: set[str]
) -> tuple[dict[str, libsbml.ASTNode], dict[tuple[str, str, int], str]]:
    """The stoichiometries which a `<stoichiometryMath>` computes.

    Level 1 and 2 state a stoichiometry which changes in time as the
    `<stoichiometryMath>` of the species reference, where level 3 has an
    assignment rule of the id of the reference. Such a reference becomes a
    variable with the formula as its equation, named after the reference
    when it has an id and `__stoichiometry_<reaction>_<role>_<index>`
    otherwise, as the reader of SBML of sbmlsim-core names it. A formula
    which is a number is the stoichiometry itself and needs no variable.

    Args:
        model_sbml: the SBML model.
        used: ids which are taken, extended by the names of the variables.

    Returns:
        The formula by the name of its variable, and the name by the
        reaction, the role and the index of the species reference.
    """
    formulas: dict[str, libsbml.ASTNode] = {}
    names: dict[tuple[str, str, int], str] = {}
    reaction: libsbml.Reaction
    for reaction in model_sbml.getListOfReactions():
        rid: str = reaction.getId()
        for role, references in (
            ("reactant", reaction.getListOfReactants()),
            ("product", reaction.getListOfProducts()),
        ):
            reference: libsbml.SpeciesReference
            for index, reference in enumerate(references):
                math = _stoichiometry_math(reference)
                if math is None or math.isNumber():
                    continue
                name = (
                    reference.getId()
                    if reference.isSetId()
                    else unique_sid(f"__stoichiometry_{rid}_{role}_{index}", used)
                )
                used.add(name)
                formulas[name] = math.deepCopy()
                names[rid, role, index] = name
                logger.info(
                    "'%s' variable for the stoichiometryMath of '%s' in '%s'",
                    name,
                    reference.getSpecies(),
                    rid,
                )
    return formulas, names


def _stoichiometry_factor(
    reaction_id: str, reference: libsbml.SpeciesReference, name: str | None
) -> libsbml.ASTNode | None:
    """Factor of the kinetic law for a species reference, `None` for 1.

    A stoichiometry which is not set is 1 in SBML level 1 and 2 and unknown
    in level 3, where 1.0 is used with a warning. `name` is the variable of
    a stoichiometry which a `<stoichiometryMath>` computes (`_stoichiometries`).
    """
    if name is not None:
        return astnodes.name(name)
    math = _stoichiometry_math(reference)
    if math is not None and math.isNumber():
        # the number of the formula is the stoichiometry itself
        value: float = math.getValue()
        return None if value == 1.0 else astnodes.number(value)
    if reference.isSetId():
        return astnodes.name(reference.getId())
    if not reference.isSetStoichiometry() and reference.getLevel() >= 3:
        logger.warning(
            "Stoichiometry of '%s' in reaction '%s' is not set, using 1.0.",
            reference.getSpecies(),
            reaction_id,
        )
        return None
    value: float = reference.getStoichiometry()
    return None if value == 1.0 else astnodes.number(value)


def _collect_reaction_terms(
    model_sbml: libsbml.Model,
    rates: dict[str, libsbml.ASTNode],
    amounts: dict[str, _Amount],
    stoichiometries: dict[tuple[str, str, int], str],
) -> dict[str, libsbml.ASTNode]:
    """Collect the rate of change of every species from the rates of its reactions.

    The rate of a reaction (the variable of a reaction with a kinetic law,
    `rates`) is in amount per time. Multiplied with
    the stoichiometry (the variable of a species reference with an id or
    with a `<stoichiometryMath>`), it
    is subtracted for every reactant and added for every product which is not
    a boundary species (reactions do not change those). The sum is multiplied
    with the conversion factor of the species or else of the model, and for a
    species in concentration divided by the size of its compartment. A
    species in concentration with a variable of its amount (`amounts`, its
    compartment changes) gets the rate of change of that variable.

    Returns:
        The right hand side of `d variable / d time`, by the id of the
        species or of the variable of its amount.
    """
    terms: dict[str, list[tuple[int, libsbml.ASTNode]]] = {}
    reaction: libsbml.Reaction
    for reaction in model_sbml.getListOfReactions():
        rid: str = reaction.getId()
        if rid not in rates:
            continue
        reference: libsbml.SpeciesReference
        for sign, role, references in (
            (libsbml.AST_MINUS, "reactant", reaction.getListOfReactants()),
            (libsbml.AST_PLUS, "product", reaction.getListOfProducts()),
        ):
            for index, reference in enumerate(references):
                sid: str = reference.getSpecies()
                if model_sbml.getSpecies(sid).getBoundaryCondition():
                    continue
                factor = _stoichiometry_factor(
                    rid, reference, stoichiometries.get((rid, role, index))
                )
                rate = astnodes.name(rid)
                term = (
                    rate
                    if factor is None
                    else astnodes.apply(libsbml.AST_TIMES, factor, rate)
                )
                terms.setdefault(sid, []).append((sign, term))

    result: dict[str, libsbml.ASTNode] = {}
    for sid, signed_terms in terms.items():
        formula = astnodes.signed_sum(signed_terms)
        species: libsbml.Species = model_sbml.getSpecies(sid)
        # the conversion factor of the species, else of the model, converts
        # the extent of the reactions into the amount of the species
        factor_id: str = (
            species.getConversionFactor()
            if species.isSetConversionFactor()
            else model_sbml.getConversionFactor()
        )
        if factor_id:
            formula = astnodes.apply(
                libsbml.AST_TIMES, astnodes.name(factor_id), formula
            )
        if sid in amounts:
            result[amounts[sid].variable] = formula
            continue
        if not species.getHasOnlySubstanceUnits():
            per_size = astnodes.apply(
                libsbml.AST_DIVIDE,
                astnodes.number(1.0, mathml.NUMBER_UNITS),
                astnodes.name(species.getCompartment()),
            )
            formula = astnodes.apply(libsbml.AST_TIMES, per_size, formula)
        result[sid] = formula
    return result


def _metadata_elements(
    model_sbml: libsbml.Model,
    model: libcellml.Model,
    cellml_units: CellMLUnits,
    formulas: _Formulas,
) -> dict[str, libsbml.SBase]:
    """The SBML element of every CellML element which stands for one.

    Returns:
        The model, the compartments, species, parameters, local parameters,
        species references with an id, reactions with a rate variable and
        unit definitions, by the id of their CellML element (`_set_ids`).
    """
    elements: dict[str, libsbml.SBase] = {model.id(): model_sbml}
    element: libsbml.SBase
    for element in [
        *model_sbml.getListOfCompartments(),
        *model_sbml.getListOfSpecies(),
        *model_sbml.getListOfParameters(),
    ]:
        elements[element.getId()] = element
    reaction: libsbml.Reaction
    for reaction in model_sbml.getListOfReactions():
        rid: str = reaction.getId()
        if rid in formulas.rates:
            elements[rid] = reaction
        for pid, vid in formulas.local_ids.get(rid, {}).items():
            elements[vid] = reaction.getKineticLaw().getParameter(pid)
        for role, references in (
            ("reactant", reaction.getListOfReactants()),
            ("product", reaction.getListOfProducts()),
        ):
            for index, reference in enumerate(references):
                name = formulas.stoichiometries.get((rid, role, index))
                if reference.isSetId():
                    elements[reference.getId()] = reference
                elif name is not None:
                    elements[name] = reference
    definition: libsbml.UnitDefinition
    for definition in model_sbml.getListOfUnitDefinitions():
        units: libcellml.Units | None = model.units(
            cellml_units.name(definition.getId()) or ""
        )
        if units is not None and units.id():
            elements[units.id()] = definition
    # the trigger variable of an event carries what a reset cannot express,
    # the delay, the priority and the flags of the event
    component: libcellml.Component = model.component(COMPONENT_ID)
    for event in formulas.events:
        event_element: libsbml.Event | None = _event_of(model_sbml, event.sid)
        variable = None if component is None else component.variable(event.trigger)
        if event_element is not None and variable is not None and variable.id():
            elements[variable.id()] = event_element
    return elements


def _event_of(model_sbml: libsbml.Model, sid: str) -> libsbml.Event | None:
    """The event of an id, also for an event which has none of its own.

    `_collect_events` names an event without an id `event_<index>`, which
    `getEvent` does not find.

    Args:
        model_sbml: the SBML model.
        sid: the id `_collect_events` gave the event.

    Returns:
        The event, `None` when the model has no such event.
    """
    event: libsbml.Event = model_sbml.getEvent(sid)
    if event is not None:
        return event
    prefix, _, index = sid.rpartition("_")
    if prefix == "event" and index.isdigit():
        return model_sbml.getEvent(int(index) - 1)
    return None


def _write_metadata(elements: dict[str, libsbml.SBase], cellml_path: Path) -> None:
    """Write the metadata of the elements next to the CellML file.

    A model without metadata has no file; the file of an earlier conversion
    is removed then, `cellml2sbml` would take it for the metadata of this
    model. A file which has no metadata of the CellML file is left alone.
    """
    path = cellml_path.with_suffix(METADATA_SUFFIX)
    records = sbml_metadata.collect_metadata(elements)
    if records:
        sbml_metadata.write_metadata(records, cellml_path.name, path)
        return
    try:
        stale = path.is_file() and sbml_metadata.read_metadata(path, cellml_path.name)
    except ValueError:
        stale = False
    if stale:
        path.unlink()
        logger.info("Metadata of an earlier conversion removed: '%s'", path)
