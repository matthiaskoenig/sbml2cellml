"""Case construction for a BioModels model.

Every curated model runs the same generic timecourse: there are no expected
results (`Case.expected` is `None`, the roadrunner simulation of the
original SBML becomes the expected results the later stages are compared
with, see `sbml2cellml.testsuite.runner`).
"""

from pathlib import Path

import libsbml

from sbml2cellml.biomodels.models import BioModelsError, ModelInfo
from sbml2cellml.testsuite.cases import Case, Settings

#: duration (time units of the model) of the generic timecourse
DURATION = 100.0
#: number of steps of the generic timecourse
STEPS = 100
#: absolute tolerance of the comparison
ABSOLUTE = 1e-6
#: relative tolerance of the comparison
RELATIVE = 1e-3


def constructs(model: libsbml.Model, text: str) -> tuple[str, ...]:
    """SBML constructs a model uses, as component tags of a `Case`.

    Args:
        model: the model to inspect.
        text: the file content the model was read from, used to detect a
            `csymbol` delay (not exposed on the `libsbml.Model` API).

    Returns:
        The construct tags present in the model, e.g. `("Reactions",
        "AssignmentRules")`.
    """
    tags: list[str] = []
    if model.getNumReactions():
        tags.append("Reactions")
    if model.getNumEvents():
        tags.append("Events")
    if model.getNumFunctionDefinitions():
        tags.append("FunctionDefinitions")
    if model.getNumInitialAssignments():
        tags.append("InitialAssignments")
    if model.getNumConstraints():
        tags.append("Constraints")
    rules = [model.getRule(k) for k in range(model.getNumRules())]
    if any(rule.isAlgebraic() for rule in rules):
        tags.append("AlgebraicRules")
    if any(rule.isAssignment() for rule in rules):
        tags.append("AssignmentRules")
    if any(rule.isRate() for rule in rules):
        tags.append("RateRules")
    if "symbols/delay" in text:
        tags.append("Delay")
    return tuple(tags)


def biomodel_case(info: ModelInfo, sbml_path: Path, packages: tuple[str, ...]) -> Case:
    """Build the generic timecourse case of a BioModels model.

    Args:
        info: metadata of the model.
        sbml_path: path of the downloaded SBML file.
        packages: SBML packages the model uses (`models.packages`); each
            becomes a `<package>:package` component tag so `skip_reason`
            skips the case the same way it skips a test suite case using an
            unsupported package.

    Returns:
        The case, with `expected=None` and `test_type="TimeCourse"`.
        `settings.variables` is the species ids, followed by the ids of the
        rate-rule and assignment-rule targets which are not species
        (parameters and compartments), in document order and without
        duplicates; `amount` and `concentration` stay species only.

    Raises:
        BioModelsError: if the SBML file has no model.
    """
    doc = libsbml.readSBMLFromFile(str(sbml_path))
    model = doc.getModel()
    if model is None:
        raise BioModelsError(f"{info.id}: no model in {sbml_path.name}")
    species = list(model.getListOfSpecies())
    species_ids = tuple(s.getId() for s in species)
    variables = list(species_ids)
    seen = set(species_ids)
    for rule in model.getListOfRules():
        if not (rule.isRate() or rule.isAssignment()):
            continue
        target = rule.getVariable()
        if target and target not in seen:
            variables.append(target)
            seen.add(target)
    settings = Settings(
        start=0.0,
        duration=DURATION,
        steps=STEPS,
        variables=tuple(variables),
        absolute=ABSOLUTE,
        relative=RELATIVE,
        amount=frozenset(s.getId() for s in species if s.getHasOnlySubstanceUnits()),
        concentration=frozenset(
            s.getId() for s in species if not s.getHasOnlySubstanceUnits()
        ),
    )
    tags = constructs(model, sbml_path.read_text(encoding="utf-8")) + tuple(
        f"{package}:package" for package in packages
    )
    return Case(
        id=info.id,
        case_dir=sbml_path.parent,
        sbml_path=sbml_path,
        settings=settings,
        expected=None,
        test_tags=(),
        component_tags=tags,
        test_type="TimeCourse",
        name=info.name,
    )
