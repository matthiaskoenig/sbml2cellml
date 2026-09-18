"""Conversion of SBML models to CellML 2.0.

The conversion puts every SBML compartment, parameter and species as a variable
into a single CellML component `sbml`, together with the variable of
integration `time`. Assignment rules become equations, rate rules and the
kinetic laws of the reactions become differential equations. The target of an
assignment rule has no initial value, the rule defines it at all times. All
variables are `dimensionless`, the units of the SBML model are not converted
yet.

CellML has no functions: the calls of SBML function definitions are replaced
by the bodies of the functions (libsbml's `expandFunctionDefinitions`
conversion) before the conversion.

Not supported yet (logged as warning, see docs/roadmap.md): unit definitions,
initial assignments, events and algebraic rules. The stoichiometry of a
reaction is not applied to its kinetic law either.
"""

import logging
import math
from pathlib import Path

import libcellml
import libsbml

from sbml2cellml import cellml, mathml
from sbml2cellml.cellml import CellMLValidationError
from sbml2cellml.mathml import TIME_ID
from sbml2cellml.variables import unique_sid

logger = logging.getLogger(__name__)

#: name of the single component which holds the model
COMPONENT_ID = "sbml"
#: units of every variable until units are converted
UNITS_ID = "dimensionless"


class SBML2CellMLConversionError(ValueError):
    """The SBML document cannot be converted."""


def convert_sbml2cellml(
    sbml_path: Path, cellml_path: Path | None = None, validate: bool = True
) -> libcellml.Model:
    """Convert an SBML file to a CellML model.

    Args:
        sbml_path: path of the SBML file.
        cellml_path: path the CellML is written to, not written if `None`.
        validate: validate and analyse the CellML model with libcellml and
            raise if it has errors.

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
    _expand_function_definitions(doc, mid)
    # the conversion rewrites the document, its model is read again
    model_sbml = doc.getModel()
    assert model_sbml is not None

    model = libcellml.Model(mid)
    component = libcellml.Component(COMPONENT_ID)
    model.addComponent(component)

    per_second = libcellml.Units("per_second")
    per_second.addUnit("second", -1)
    model.addUnits(per_second)

    time = libcellml.Variable(TIME_ID)
    time.setUnits(UNITS_ID)
    component.addVariable(time)

    assignment_rules, rate_rules = _collect_rules(model_sbml)
    assigned = set(assignment_rules)
    compartment_sizes = _add_compartments(component, model_sbml, assigned)
    _add_parameters(component, model_sbml, assigned)
    in_amount = _add_species(component, model_sbml, compartment_sizes, assigned)
    local_ids = _add_local_parameters(component, model_sbml)
    _add_species_references(component, model_sbml, assigned)
    rates = _kinetic_laws(model_sbml, local_ids)
    reaction_ids = _referenced_reactions(model_sbml, rates)
    for rid in reaction_ids:
        _add_variable(component, rid, None)

    reaction_terms = _collect_reaction_terms(model_sbml, in_amount, rates)

    parts: list[str] = []
    for vid, formula in assignment_rules.items():
        logger.info("%s = %s", vid, formula)
        parts.append(mathml.mathml_for_assignment(vid=vid, formula=formula))
    for vid, formula in rate_rules.items():
        logger.info("d%s/dt = %s", vid, formula)
        parts.append(mathml.mathml_for_diff(vid=vid, formula=formula, ivid=TIME_ID))
    for vid, formula in reaction_terms.items():
        logger.info("d%s/dt = %s", vid, formula)
        parts.append(mathml.mathml_for_diff(vid=vid, formula=formula, ivid=TIME_ID))
    for rid in reaction_ids:
        logger.info("%s = %s (rate of reaction)", rid, rates[rid])
        parts.append(mathml.mathml_for_assignment(vid=rid, formula=rates[rid]))
    component.setMath(mathml.cellml_math(parts))

    event: libsbml.Event
    for event in model_sbml.getListOfEvents():
        logger.warning(
            "Event '%s' not converted, events are not supported yet.", event.getId()
        )
    assignment: libsbml.InitialAssignment
    for assignment in model_sbml.getListOfInitialAssignments():
        logger.warning(
            "InitialAssignment for '%s' not converted, initial assignments are "
            "not supported yet.",
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

    return model


def _expand_function_definitions(doc: libsbml.SBMLDocument, mid: str) -> None:
    """Replace the calls of function definitions by the function bodies.

    libsbml inlines every call with its arguments and removes the function
    definitions. It refuses an invalid document (e.g. a call of an undefined
    function) and crashes on a recursive function definition read from a
    file, which is therefore checked first. The calls then stay, with a
    warning, and the validation of the CellML reports them as unknown names.

    Args:
        doc: the SBML document, converted in place.
        mid: id of the model, for the log.
    """
    model_sbml: libsbml.Model = doc.getModel()
    count = model_sbml.getNumFunctionDefinitions()
    if count == 0:
        return
    recursive = _recursive_functions(model_sbml)
    if recursive:
        logger.warning(
            "Function definitions of '%s' could not be expanded, their calls "
            "remain: recursive function definitions %s",
            mid,
            ", ".join(recursive),
        )
        return
    properties = libsbml.ConversionProperties()
    properties.addOption("expandFunctionDefinitions", True)
    status = doc.convert(properties)
    if status != libsbml.LIBSBML_OPERATION_SUCCESS:
        logger.warning(
            "Function definitions of '%s' could not be expanded, their calls "
            "remain: %s",
            mid,
            libsbml.OperationReturnValue_toString(status),
        )
        return
    logger.info("Expanded %d function definitions of '%s'", count, mid)


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


def _initial_value(sid: str, value: float) -> float:
    """Replace a NaN initial value by 1.0 with a warning.

    A NaN is what libsbml returns for an unset value; the value would have to
    be calculated from the rules and initial assignments, which is not
    supported yet.
    """
    if math.isnan(value):
        logger.warning("Initial value of '%s' is not set, using 1.0.", sid)
        return 1.0
    return value


def _add_variable(
    component: libcellml.Component, sid: str, value: float | None
) -> None:
    """Add a dimensionless variable to the component.

    `value` is its initial value, `None` for a variable an equation computes
    (the target of an assignment rule), which must not have one.
    """
    variable = libcellml.Variable(sid)
    variable.setUnits(UNITS_ID)
    if value is not None:
        variable.setInitialValue(value)
    component.addVariable(variable)


def _add_compartments(
    component: libcellml.Component, model_sbml: libsbml.Model, assigned: set[str]
) -> dict[str, float]:
    """Add the compartments as variables.

    Returns:
        The initial size of every compartment by id, which converts the
        initial values of its species; NaN for a compartment an assignment
        rule sets whose size attribute is unset.
    """
    sizes: dict[str, float] = {}
    compartment: libsbml.Compartment
    for compartment in model_sbml.getListOfCompartments():
        cid: str = compartment.getId()
        if cid in assigned:
            sizes[cid] = compartment.getSize()
            _add_variable(component, cid, None)
        else:
            sizes[cid] = _initial_value(cid, compartment.getSize())
            _add_variable(component, cid, sizes[cid])
        logger.info("'%s' variable for compartment", cid)
    return sizes


def _add_parameters(
    component: libcellml.Component, model_sbml: libsbml.Model, assigned: set[str]
) -> None:
    """Add the parameters as variables."""
    parameter: libsbml.Parameter
    for parameter in model_sbml.getListOfParameters():
        pid: str = parameter.getId()
        value = None if pid in assigned else _initial_value(pid, parameter.getValue())
        _add_variable(component, pid, value)
        logger.info("'%s' variable for parameter", pid)


def _add_species(
    component: libcellml.Component,
    model_sbml: libsbml.Model,
    compartment_sizes: dict[str, float],
    assigned: set[str],
) -> dict[str, bool]:
    """Add the species as variables.

    A species with `hasOnlySubstanceUnits` is a variable in amount, every other
    species a variable in concentration; the initial value is converted with
    the size of the compartment when it is given in the other quantity. A
    species an assignment rule sets has no initial value.

    Returns:
        Whether the variable of a species is in amount, by species id.
    """
    in_amount: dict[str, bool] = {}
    species: libsbml.Species
    for species in model_sbml.getListOfSpecies():
        sid: str = species.getId()
        cid: str = species.getCompartment()
        amount = species.getHasOnlySubstanceUnits()
        in_amount[sid] = amount

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
            initial = _initial_value(sid, math.nan)
        _add_variable(component, sid, initial)
        logger.info("'%s' variable for species", sid)
    return in_amount


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
) -> tuple[dict[str, str], dict[str, str]]:
    """Collect the assignment and rate rules as formulas.

    Returns:
        The assignment rules and the rate rules, formula by variable id.
    """
    assignment_rules: dict[str, str] = {}
    rate_rules: dict[str, str] = {}
    rule: libsbml.Rule
    for rule in model_sbml.getListOfRules():
        formula: str = libsbml.formulaToL3String(rule.getMath())
        if rule.getTypeCode() == libsbml.SBML_ASSIGNMENT_RULE:
            assignment_rules[rule.getVariable()] = formula
        elif rule.getTypeCode() == libsbml.SBML_RATE_RULE:
            rate_rules[rule.getVariable()] = formula
        else:
            logger.warning(
                "AlgebraicRule '%s' not converted, algebraic rules are not "
                "supported yet.",
                formula,
            )
    return assignment_rules, rate_rules


def _add_local_parameters(
    component: libcellml.Component, model_sbml: libsbml.Model
) -> dict[str, dict[str, str]]:
    """Add the local parameters of the kinetic laws as variables.

    A local parameter is only visible in its kinetic law, and several
    reactions may have one of the same id. Each becomes a variable of its
    own, `<reaction>_<parameter>`, with a numeric suffix when that id is
    taken by another element of the model.

    Returns:
        The variable id of every local parameter, by reaction id and local
        parameter id.
    """
    model_sbml.populateAllElementIdList()
    ids: libsbml.IdList = model_sbml.getAllElementIdList()
    used = {ids.at(k) for k in range(ids.size())} | {TIME_ID}
    local_ids: dict[str, dict[str, str]] = {}
    reaction: libsbml.Reaction
    for reaction in model_sbml.getListOfReactions():
        klaw: libsbml.KineticLaw | None = reaction.getKineticLaw()
        if klaw is None:
            continue
        rid: str = reaction.getId()
        # the local parameters in level 3, the parameters of the kinetic law
        # in level 2
        for k in range(klaw.getNumParameters()):
            local = klaw.getParameter(k)
            pid: str = local.getId()
            vid = unique_sid(f"{rid}_{pid}", used)
            local_ids.setdefault(rid, {})[pid] = vid
            _add_variable(component, vid, _initial_value(vid, local.getValue()))
            logger.info("'%s' variable for local parameter '%s' of '%s'", vid, pid, rid)
    return local_ids


def _add_species_references(
    component: libcellml.Component, model_sbml: libsbml.Model, assigned: set[str]
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
                else _initial_value(vid, reference.getStoichiometry())
            )
            _add_variable(component, vid, value)
            logger.info(
                "'%s' variable for a stoichiometry of '%s'", vid, reaction.getId()
            )


def _kinetic_laws(
    model_sbml: libsbml.Model, local_ids: dict[str, dict[str, str]]
) -> dict[str, str]:
    """The rate of every reaction with a kinetic law, amount per time.

    Returns:
        The formula of the kinetic law, its local parameters renamed to their
        variables (`local_ids`), by reaction id.
    """
    rates: dict[str, str] = {}
    reaction: libsbml.Reaction
    for reaction in model_sbml.getListOfReactions():
        klaw: libsbml.KineticLaw | None = reaction.getKineticLaw()
        if klaw is None:
            logger.warning(
                "Reaction '%s' has no kinetic law and is not converted.",
                reaction.getId(),
            )
            continue
        math: libsbml.ASTNode = klaw.getMath().deepCopy()
        for pid, vid in local_ids.get(reaction.getId(), {}).items():
            math.renameSIdRefs(pid, vid)
        rates[reaction.getId()] = libsbml.formulaToL3String(math)
    return rates


def _referenced_reactions(
    model_sbml: libsbml.Model, rates: dict[str, str]
) -> list[str]:
    """Ids of the reactions a rule or a kinetic law uses as a name.

    The id of a reaction stands for its rate in formulas; such a reaction
    gets a variable of its rate.
    """
    names: set[str] = set()
    rule: libsbml.Rule
    for rule in model_sbml.getListOfRules():
        _collect_names(rule.getMath(), libsbml.AST_NAME, names)
    reaction: libsbml.Reaction
    for reaction in model_sbml.getListOfReactions():
        if reaction.getKineticLaw() is not None:
            _collect_names(reaction.getKineticLaw().getMath(), libsbml.AST_NAME, names)
    return [rid for rid in rates if rid in names]


def _stoichiometry_factor(reaction_id: str, reference: libsbml.SpeciesReference) -> str:
    """Factor of the kinetic law for a species reference, empty for 1."""
    if reference.isSetId():
        return f"{reference.getId()} * "
    if not reference.isSetStoichiometry():
        logger.warning(
            "Stoichiometry of '%s' in reaction '%s' is not set, using 1.0.",
            reference.getSpecies(),
            reaction_id,
        )
        return ""
    value: float = reference.getStoichiometry()
    return "" if value == 1.0 else f"{value!r} * "


def _collect_reaction_terms(
    model_sbml: libsbml.Model,
    in_amount: dict[str, bool],
    rates: dict[str, str],
) -> dict[str, str]:
    """Collect the rate of change of every species from the kinetic laws.

    The rate of a reaction (`rates`) is in amount per time. Multiplied with
    the stoichiometry (the variable of a species reference with an id), it
    is subtracted for every reactant and added for every product; for a
    species in concentration the sum is divided by the size of its
    compartment.

    Returns:
        The right hand side of `d species / d time`, by species id.
    """
    terms: dict[str, str] = {}
    reaction: libsbml.Reaction
    for reaction in model_sbml.getListOfReactions():
        rid: str = reaction.getId()
        if rid not in rates:
            continue
        formula = rates[rid]
        reference: libsbml.SpeciesReference
        for reference in reaction.getListOfReactants():
            factor = _stoichiometry_factor(rid, reference)
            _append_term(terms, reference.getSpecies(), f"- {factor}({formula})")
        for reference in reaction.getListOfProducts():
            factor = _stoichiometry_factor(rid, reference)
            _append_term(terms, reference.getSpecies(), f"+ {factor}({formula})")

    for sid, formula in terms.items():
        if not in_amount[sid]:
            cid: str = model_sbml.getSpecies(sid).getCompartment()
            terms[sid] = f"1.0 dimensionless/{cid} * ({formula})"
    return terms


def _append_term(terms: dict[str, str], sid: str, term: str) -> None:
    """Append a term to the rate of change of a species."""
    terms[sid] = f"{terms[sid]} {term}" if sid in terms else term
