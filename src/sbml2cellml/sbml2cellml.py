"""Conversion of SBML models to CellML 2.0.

The conversion puts every SBML compartment, parameter and species as a variable
into a single CellML component `sbml`, together with the variable of
integration `time`. Assignment rules become equations, rate rules and the
kinetic laws of the reactions become differential equations. All variables are
`dimensionless`, the units of the SBML model are not converted yet.

Not supported yet (logged as warning, see docs/roadmap.md): unit definitions,
initial assignments, function definitions, events and algebraic rules. The
stoichiometry of a reaction is not applied to its kinetic law either.
"""

import logging
import math
from pathlib import Path

import libcellml
import libsbml

from sbml2cellml import cellml, mathml
from sbml2cellml.cellml import CellMLValidationError

logger = logging.getLogger(__name__)

#: name of the single component which holds the model
COMPONENT_ID = "sbml"
#: name of the variable of integration
TIME_ID = "time"
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
        SBML2CellMLConversionError: if the file has no model.
        CellMLValidationError: if `validate` is set and the model has errors.
    """
    doc: libsbml.SBMLDocument = libsbml.readSBMLFromFile(str(sbml_path))
    model_sbml: libsbml.Model | None = doc.getModel()
    if model_sbml is None:
        raise SBML2CellMLConversionError(f"No model in SBML file '{sbml_path}'.")
    mid: str = model_sbml.getId() if model_sbml.isSetId() else Path(sbml_path).stem
    logger.info("Converting SBML model '%s' from '%s'", mid, sbml_path)

    model = libcellml.Model(mid)
    component = libcellml.Component(COMPONENT_ID)
    model.addComponent(component)

    per_second = libcellml.Units("per_second")
    per_second.addUnit("second", -1)
    model.addUnits(per_second)

    time = libcellml.Variable(TIME_ID)
    time.setUnits(UNITS_ID)
    component.addVariable(time)

    compartment_sizes = _add_compartments(component, model_sbml)
    _add_parameters(component, model_sbml)
    in_amount = _add_species(component, model_sbml, compartment_sizes)

    assignment_rules, rate_rules = _collect_rules(model_sbml)
    reaction_terms = _collect_reaction_terms(model_sbml, in_amount)

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


def _add_variable(component: libcellml.Component, sid: str, value: float) -> None:
    """Add a dimensionless variable with an initial value to the component."""
    variable = libcellml.Variable(sid)
    variable.setUnits(UNITS_ID)
    variable.setInitialValue(value)
    component.addVariable(variable)


def _add_compartments(
    component: libcellml.Component, model_sbml: libsbml.Model
) -> dict[str, float]:
    """Add the compartments as variables.

    Returns:
        The initial size of every compartment by id.
    """
    sizes: dict[str, float] = {}
    compartment: libsbml.Compartment
    for compartment in model_sbml.getListOfCompartments():
        cid: str = compartment.getId()
        sizes[cid] = _initial_value(cid, compartment.getSize())
        _add_variable(component, cid, sizes[cid])
        logger.info("'%s' variable for compartment", cid)
    return sizes


def _add_parameters(component: libcellml.Component, model_sbml: libsbml.Model) -> None:
    """Add the parameters as variables."""
    parameter: libsbml.Parameter
    for parameter in model_sbml.getListOfParameters():
        pid: str = parameter.getId()
        _add_variable(component, pid, _initial_value(pid, parameter.getValue()))
        logger.info("'%s' variable for parameter", pid)


def _add_species(
    component: libcellml.Component,
    model_sbml: libsbml.Model,
    compartment_sizes: dict[str, float],
) -> dict[str, bool]:
    """Add the species as variables.

    A species with `hasOnlySubstanceUnits` is a variable in amount, every other
    species a variable in concentration; the initial value is converted with
    the size of the compartment when it is given in the other quantity.

    Returns:
        Whether the variable of a species is in amount, by species id.
    """
    in_amount: dict[str, bool] = {}
    species: libsbml.Species
    for species in model_sbml.getListOfSpecies():
        sid: str = species.getId()
        size = compartment_sizes[species.getCompartment()]
        amount = species.getHasOnlySubstanceUnits()
        in_amount[sid] = amount

        if species.isSetInitialAmount():
            value = _initial_value(sid, species.getInitialAmount())
            initial = value if amount else value / size
        elif species.isSetInitialConcentration():
            value = _initial_value(sid, species.getInitialConcentration())
            initial = value * size if amount else value
        else:
            initial = _initial_value(sid, math.nan)
        _add_variable(component, sid, initial)
        logger.info("'%s' variable for species", sid)
    return in_amount


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


def _collect_reaction_terms(
    model_sbml: libsbml.Model, in_amount: dict[str, bool]
) -> dict[str, str]:
    """Collect the rate of change of every species from the kinetic laws.

    The kinetic law of a reaction is in amount per time. It is subtracted for
    every reactant and added for every product; for a species in concentration
    the sum is divided by the size of its compartment.

    Returns:
        The right hand side of `d species / d time`, by species id.
    """
    terms: dict[str, str] = {}
    reaction: libsbml.Reaction
    for reaction in model_sbml.getListOfReactions():
        klaw: libsbml.KineticLaw | None = reaction.getKineticLaw()
        if klaw is None:
            logger.warning(
                "Reaction '%s' has no kinetic law and is not converted.",
                reaction.getId(),
            )
            continue
        formula: str = libsbml.formulaToL3String(klaw.getMath())
        reference: libsbml.SpeciesReference
        for reference in reaction.getListOfReactants():
            _append_term(terms, reference.getSpecies(), f"- ({formula})")
        for reference in reaction.getListOfProducts():
            _append_term(terms, reference.getSpecies(), f"+ ({formula})")

    for sid, formula in terms.items():
        if not in_amount[sid]:
            cid: str = model_sbml.getSpecies(sid).getCompartment()
            terms[sid] = f"1.0 dimensionless/{cid} * ({formula})"
    return terms


def _append_term(terms: dict[str, str], sid: str, term: str) -> None:
    """Append a term to the rate of change of a species."""
    terms[sid] = f"{terms[sid]} {term}" if sid in terms else term
