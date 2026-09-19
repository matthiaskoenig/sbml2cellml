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

Not supported yet (logged as warning, see docs/conversion-issues.md): events.
"""

import logging
import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import libcellml
import libsbml

from sbml2cellml import astnodes, cellml, mathml
from sbml2cellml import metadata as sbml_metadata
from sbml2cellml.cellml import CellMLValidationError
from sbml2cellml.cellmlunits import CellMLUnits
from sbml2cellml.mathml import TIME_ID
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

    Returns:
        The CellML model.

    Raises:
        SBML2CellMLConversionError: if the file does not exist or has no model.
        CellMLValidationError: if `validate` is set and the model has errors.
    """
    sbml_path = Path(sbml_path)
    if not sbml_path.is_file():
        raise SBML2CellMLConversionError(f"SBML file does not exist: '{sbml_path}'.")
    doc: libsbml.SBMLDocument = libsbml.readSBMLFromFile(str(sbml_path))
    model_sbml: libsbml.Model | None = doc.getModel()
    if model_sbml is None:
        raise SBML2CellMLConversionError(f"No model in SBML file '{sbml_path}'.")
    mid: str = model_sbml.getId() if model_sbml.isSetId() else Path(sbml_path).stem
    logger.info("Converting SBML model '%s' from '%s'", mid, sbml_path)
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
        _add_variable(component, TIME_ID, None, units)
    compartment_sizes = _add_compartments(component, model_sbml, assigned, units)
    _add_parameters(component, model_sbml, assigned, units)
    _add_species(
        component, model_sbml, compartment_sizes, assigned, formulas.amounts, units
    )
    _add_local_parameters(component, model_sbml, formulas.local_ids, units)
    _add_species_references(component, model_sbml, assigned, units)
    for rid in reaction_ids:
        _add_variable(component, rid, None, units)

    parts: list[str] = []
    for vid, formula in assignment_rules.items():
        logger.info("%s = %s", vid, astnodes.text(formula))
        parts.append(mathml.mathml_for_assignment(vid, formula, number_units))
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
        parts.append(mathml.mathml_for_algebraic(formula, number_units))
    parts.extend(_constants_of_algebraic_rules(component, formulas))
    for vid, formula in [*rate_rules.items(), *reaction_terms.items()]:
        logger.info("d%s/dt = %s", vid, astnodes.text(formula))
        parts.append(mathml.mathml_for_diff(vid, formula, TIME_ID, number_units))
    for rid in reaction_ids:
        logger.info("%s = %s (rate of reaction)", rid, astnodes.text(rates[rid]))
        parts.append(mathml.mathml_for_assignment(rid, rates[rid], number_units))
    parts.extend(
        _non_finite_initial_values(component, set(rate_rules) | set(reaction_terms))
    )
    component.setMath(mathml.cellml_math(parts))
    model.linkUnits()
    _set_ids(model)

    event: libsbml.Event
    for event in model_sbml.getListOfEvents():
        logger.warning(
            "Event '%s' not converted, events are not supported yet.", event.getId()
        )
    assignment: libsbml.InitialAssignment
    for assignment in model_sbml.getListOfInitialAssignments():
        logger.warning(
            "InitialAssignment for '%s' not converted, it was not evaluated.",
            assignment.getSymbol(),
        )

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
            elements = _metadata_elements(model_sbml, model, cellml_units, formulas)
            _write_metadata(elements, Path(cellml_path))

    return model


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
def _without_rate_rules(doc: libsbml.SBMLDocument) -> Iterator[None]:
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
            rate = self.reaction_terms.get(amount.variable, astnodes.number(0.0))
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
    algebraic_rules = _match_algebraic_rules(
        model_sbml, algebraic, set(assignment_rules) | set(rate_rules)
    )
    model_sbml.populateAllElementIdList()
    ids: libsbml.IdList = model_sbml.getAllElementIdList()
    used = {ids.at(k) for k in range(ids.size())} | {TIME_ID}
    local_ids = _local_parameter_ids(model_sbml, used)
    determined = set(assignment_rules) | set(rate_rules) | set(algebraic_rules)
    changing = _changing(
        model_sbml, assignment_rules, set(rate_rules) | set(algebraic_rules)
    )
    amounts = _amounts(model_sbml, determined, changing, used)
    rates = _kinetic_laws(model_sbml, local_ids)
    reaction_terms = _collect_reaction_terms(model_sbml, rates, amounts)
    result = _Formulas(
        assignment_rules,
        rate_rules,
        reaction_terms,
        rates,
        local_ids,
        algebraic_rules,
        amounts,
    )
    derivatives = result.derivatives
    for formulas in (
        assignment_rules,
        rate_rules,
        reaction_terms,
        rates,
        algebraic_rules,
    ):
        for key, formula in formulas.items():
            formulas[key] = _expand_rate_of(formula, derivatives, result.computed)
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


def _initial_value(sid: str, value: float | None) -> float:
    """Replace an unset initial value by 1.0 with a warning.

    `value` is `None` when the SBML attribute is unset (libsbml returns NaN
    for an unset value, like for a value set to NaN, so the caller decides
    with `isSet...`); a value which is set is returned as it is, NaN and
    infinity included.
    """
    if value is None:
        logger.warning("Initial value of '%s' is not set, using 1.0.", sid)
        return 1.0
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
        units[TIME_ID] = cellml_units.time()
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
        variable.setInitialValue(value)
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
            initial = _initial_value(sid, None)
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
    change, the rates of the reactions, the targets of assignment rules which
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
    determined: set[str],
    changing: set[str],
    used: set[str],
) -> dict[str, _Amount]:
    """The species in concentration which need a variable of their amount.

    Reactions change the amount of a species, and a species nothing changes
    keeps its amount, also a constant one or a boundary species. The
    concentration follows when the size of the compartment changes, so a
    species in a compartment which changes becomes the equation
    `species = amount / compartment` with the amount as the variable the
    reactions change. A species which a rule determines itself stays as it
    is: the rule gives its concentration or the rate of it.

    Args:
        model_sbml: the SBML model.
        determined: ids which assignment, rate and algebraic rules determine.
        changing: ids of the variables which change in time (`_changing`).
        used: ids taken so far, the new ids are added.

    Returns:
        The variable `<species>_amount` (with a numeric suffix when that id
        is taken) by species id.
    """
    amounts: dict[str, _Amount] = {}
    species: libsbml.Species
    for species in model_sbml.getListOfSpecies():
        sid: str = species.getId()
        cid: str = species.getCompartment()
        if (
            species.getHasOnlySubstanceUnits()
            or sid in determined
            or cid not in changing
        ):
            continue
        amounts[sid] = _Amount(unique_sid(f"{sid}_amount", used), cid)
    return amounts


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
) -> None:
    """Add the species references with an id as variables.

    The id of a species reference stands for its stoichiometry in formulas,
    and rules may set it; the variable has the stoichiometry as initial
    value, none when an assignment rule sets it.
    """
    reaction: libsbml.Reaction
    for reaction in model_sbml.getListOfReactions():
        references = [*reaction.getListOfReactants(), *reaction.getListOfProducts()]
        for reference in references:
            if not reference.isSetId():
                continue
            vid: str = reference.getId()
            value = (
                None
                if vid in assigned
                else _initial_value(
                    vid,
                    _set_value(
                        reference.isSetStoichiometry(), reference.getStoichiometry()
                    ),
                )
            )
            _add_variable(component, vid, value, units)
            logger.info(
                "'%s' variable for a stoichiometry of '%s'", vid, reaction.getId()
            )


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


def _uses_time(model_sbml: libsbml.Model) -> bool:
    """Whether a rule or a kinetic law uses the time symbol."""
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


def _stoichiometry_factor(
    reaction_id: str, reference: libsbml.SpeciesReference
) -> libsbml.ASTNode | None:
    """Factor of the kinetic law for a species reference, `None` for 1.

    A stoichiometry which is not set is 1 in SBML level 1 and 2 and unknown
    in level 3, where 1.0 is used with a warning.
    """
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
) -> dict[str, libsbml.ASTNode]:
    """Collect the rate of change of every species from the rates of its reactions.

    The rate of a reaction (the variable of a reaction with a kinetic law,
    `rates`) is in amount per time. Multiplied with
    the stoichiometry (the variable of a species reference with an id), it
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
        for sign, references in (
            (libsbml.AST_MINUS, reaction.getListOfReactants()),
            (libsbml.AST_PLUS, reaction.getListOfProducts()),
        ):
            for reference in references:
                sid: str = reference.getSpecies()
                if model_sbml.getSpecies(sid).getBoundaryCondition():
                    continue
                factor = _stoichiometry_factor(rid, reference)
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
        for reference in [
            *reaction.getListOfReactants(),
            *reaction.getListOfProducts(),
        ]:
            if reference.isSetId():
                elements[reference.getId()] = reference
    definition: libsbml.UnitDefinition
    for definition in model_sbml.getListOfUnitDefinitions():
        units: libcellml.Units | None = model.units(
            cellml_units.name(definition.getId()) or ""
        )
        if units is not None and units.id():
            elements[units.id()] = definition
    return elements


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
