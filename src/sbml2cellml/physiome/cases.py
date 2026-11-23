"""Case construction for a model of the Physiome Model Repository.

Every model runs the same generic timecourse. The repository has no expected
results, so the libopencor simulation of the CellML model is what the later
stages are compared with (`sbml2cellml.physiome.runner`).

The variables of a case are the SBML ids `cellml2sbml` gives the variables of
the model, one per equivalence set of the CellML model
(`sbml2cellml.variables.VariableIds`). `columns` maps the names libopencor
gives them, with and without the component, to those ids, so that the result
of the CellML simulation and the result of the SBML simulation hold the same
columns.
"""

import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import libcellml

from sbml2cellml.cellml2sbml import analyse_model, read_cellml_model
from sbml2cellml.physiome.models import Exposure, PhysiomeError
from sbml2cellml.testsuite.cases import Case, Settings
from sbml2cellml.variables import (
    VariableIds,
    analyser_variables,
    components,
    equivalence_set,
)

logger = logging.getLogger(__name__)

#: duration (time units of the model) of the generic timecourse
DURATION = 100.0
#: number of steps of the generic timecourse. The models of the repository
#: are stiff and many of them switch their right-hand side hard (a gate
#: `u < u_c ? 0 : 1` of a cardiac model, for instance), where the two
#: solvers step over the switch differently when the output grid is coarse:
#: the Fenton Karma 1998 model differs by 1.2 in `u` with 100 output points
#: and by 0 with 1000, so the comparison measures the output grid instead of
#: the conversion unless the grid is fine
STEPS = 1000
#: absolute tolerance of the comparison
ABSOLUTE = 1e-6
#: relative tolerance of the comparison
RELATIVE = 1e-3
#: name of the time column of a result, as the SBML simulation gives it
TIME = "time"


@dataclass(frozen=True)
class PhysiomeCase:
    """A case of the check: the CellML model and how to read its results."""

    #: the generic case, with the settings and without expected results
    case: Case
    #: path of the CellML file, the source of the pipeline
    cellml_path: Path
    #: SBML id by the name libopencor gives a variable, with the component
    #: (`membrane/V`) and without it (`V`)
    columns: dict[str, str]


def constructs(model: libcellml.Model, analyser_model: Any) -> tuple[str, ...]:
    """CellML constructs a model uses, as component tags of a `Case`.

    Args:
        model: the CellML model, with its imports flattened.
        analyser_model: its analyser model.

    Returns:
        The construct tags, e.g. `("Components", "Resets")`.
    """
    count = len(list(components(model)))
    tags = [f"{count} components"] if count else []
    if analyser_model.stateCount():
        tags.append("DifferentialEquations")
    if analyser_model.hasExternalVariables():
        tags.append("ExternalVariables")
    if any(component.resetCount() for component in components(model)):
        tags.append("Resets")
    if model.hasImports():
        tags.append("Imports")
    if model.unitsCount():
        tags.append("Units")
    return tuple(tags)


def _full_name(variable: Any) -> str:
    """`component/variable` name of a variable, as libopencor writes it."""
    component = variable.parent().name() if variable.parent() else ""
    return f"{component}/{variable.name()}"


def physiome_case(exposure: Exposure, cellml_path: Path) -> PhysiomeCase:
    """Build the generic timecourse case of a model of the repository.

    Args:
        exposure: the exposure the model belongs to.
        cellml_path: path of the CellML file in the cloned workspace.

    Returns:
        The case, with `expected=None`; `settings.variables` are the SBML
        ids of the variables of the model without the variable of
        integration.

    Raises:
        PhysiomeError: if the model cannot be read, has unresolved imports,
            cannot be analysed or has no variables.
    """
    try:
        model = read_cellml_model(cellml_path)
        analyser_model = analyse_model(model)
    except Exception as err:
        raise PhysiomeError(f"{exposure.id}: {err}") from err

    ids = VariableIds(analyser_model)
    variables: list[str] = []
    columns: dict[str, str] = {}
    voi = analyser_model.voi()
    analysed = [
        analyser_model.state(k) for k in range(analyser_model.stateCount())
    ] + analyser_variables(analyser_model)
    representatives = [
        analyser_variable.variable() for analyser_variable in analysed
    ] + ([] if voi is None else [voi.variable()])
    # libopencor names a variable of the result after the variable the
    # analyser picked for its equivalence set and keeps the component of a
    # name which more than one of them has (`simulate._result_names`)
    counts = Counter(variable.name() for variable in representatives)
    for variable in representatives:
        # the comparison reads the time points from `time`, as the SBML
        # simulation names them, whatever the variable of integration of
        # the CellML model is called
        sid = TIME if ids.is_voi(variable) else ids.id_for(variable)
        if sid != TIME and sid not in variables:
            variables.append(sid)
        if counts[variable.name()] == 1:
            columns[variable.name()] = sid
        # every variable of the equivalence set, so that the map holds the
        # name of the result whichever member the generator names it after
        for member in equivalence_set(variable):
            columns[_full_name(member)] = sid
    if not variables:
        raise PhysiomeError(f"{exposure.id}: the model has no variables")

    settings = Settings(
        start=0.0,
        duration=DURATION,
        steps=STEPS,
        variables=tuple(variables),
        absolute=ABSOLUTE,
        relative=RELATIVE,
        amount=frozenset(),
        concentration=frozenset(),
    )
    return PhysiomeCase(
        case=Case(
            id=exposure.id,
            case_dir=cellml_path.parent,
            sbml_path=None,
            settings=settings,
            expected=None,
            test_tags=(),
            component_tags=constructs(model, analyser_model),
            test_type="TimeCourse",
            name=exposure.title,
        ),
        cellml_path=cellml_path,
        columns=columns,
    )
