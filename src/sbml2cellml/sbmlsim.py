"""Simulation of SBML models with sbmlsim-core.

sbmlsim-core compiles an SBML model to WebAssembly and simulates it with its
engine (CVODE of SUNDIALS). It is part of the `simulate` extra and imported
when a simulation runs, so the rest of the package works without it. See
`SBMLSIM_INSTALL`.

The compiler reads flat SBML level 3 (version 1 or 2) without a required
package, while the converters read every level: `compilable_sbml` converts a
level 1 or 2 model and flattens the `comp` package of a model before it is
compiled.
"""

import logging
from pathlib import Path
from typing import Any

import libsbml
import pandas as pd

from sbml2cellml.simulate import MAXIMUM_NUMBER_OF_STEPS, SimulationError

logger = logging.getLogger(__name__)

#: contract of a simulation request of sbmlsim-core
SIMULATION_CONTRACT = "simulation/1"
#: relative tolerance of CVODE when none is given
RELATIVE_TOLERANCE = 1e-8
#: absolute tolerance of CVODE when none is given
ABSOLUTE_TOLERANCE = 1e-10
#: how to install sbmlsim-core, the message of the ImportError
SBMLSIM_INSTALL = (
    "sbmlsim-core is not installed. Install it with the simulate extra, "
    '`pip install "sbml2cellml[simulate]"`, see '
    "https://matthiaskoenig.github.io/sbml2cellml/installation/"
)
#: runtime of this process, created on first use: the engine of sbmlsim-core
#: is compiled once and every model is loaded into it
_RUNTIME: Any = None


def _sbmlsim_core() -> Any:
    """Import sbmlsim-core with an installation hint on failure.

    Returns:
        The `sbmlsim_core` module.

    Raises:
        ImportError: if sbmlsim-core is not installed.
    """
    try:
        import sbmlsim_core
    except ImportError as err:
        raise ImportError(SBMLSIM_INSTALL) from err
    return sbmlsim_core


def runtime() -> Any:
    """The runtime of this process, created on first use.

    The engine is compiled once and shared by every model of the process.

    Returns:
        The `sbmlsim_core.Runtime`.
    """
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = _sbmlsim_core().Runtime()
    return _RUNTIME


def _errors(document: libsbml.SBMLDocument) -> str:
    """The messages of the errors of a document, for an exception."""
    return "; ".join(
        document.getError(index).getMessage()
        for index in range(document.getNumErrors())
    )


def compilable_sbml(sbml: str) -> str:
    """The model as flat SBML level 3, converted when it is not.

    Args:
        sbml: SBML document as string.

    Returns:
        The document, converted to level 3 version 2 when its level is lower
        and flattened when it requires the `comp` package; the string itself
        when neither applies.

    Raises:
        SimulationError: if the document has no model or cannot be converted.
    """
    document = libsbml.readSBMLFromString(sbml)
    if document.getModel() is None:
        raise SimulationError(f"no model in the SBML document: {_errors(document)}")
    converted = False
    if document.getLevel() < 3:
        logger.info(
            "converting the model from level %d version %d to level 3 version 2",
            document.getLevel(),
            document.getVersion(),
        )
        # the strict conversion refuses a model which it cannot convert
        # without a change of its meaning, which includes constructs without
        # mathematics (the `outside` attribute of a compartment of level 2)
        # and inconsistent units; the conversion is then repeated without the
        # check, which drops what level 3 has no place for
        if not document.setLevelAndVersion(3, 2, True):
            problems = _errors(document)
            if not document.setLevelAndVersion(3, 2, False):
                raise SimulationError(
                    "the model cannot be converted to SBML level 3 version 2: "
                    f"{problems}"
                )
            logger.warning(
                "the model was converted to SBML level 3 version 2 without the "
                "strict check: %s",
                problems,
            )
        converted = True
    if document.getPackageRequired("comp"):
        logger.info("flattening the comp package of the model")
        properties = libsbml.ConversionProperties()
        properties.addOption("flatten comp", True)
        properties.addOption("leave ports", False)
        if document.convert(properties) != libsbml.LIBSBML_OPERATION_SUCCESS:
            raise SimulationError(
                f"the comp package of the model cannot be flattened: {_errors(document)}"
            )
        converted = True
    return str(libsbml.writeSBMLToString(document)) if converted else sbml


def state_scale(model: libsbml.Model) -> float:
    """Smallest nonzero magnitude of the initial value of a state.

    The states of the solver are the species, in amounts, and the
    compartments and parameters a rate rule determines. An absolute
    tolerance above the magnitude of a state makes its trajectory
    meaningless, and the amounts of a model with a small compartment are
    small: a species with a concentration of 1 in a compartment of
    1e-13 litre has the amount 1e-13. `run_timecourse` therefore scales the
    absolute tolerance with this magnitude, as roadrunner does.

    Args:
        model: the model, after the conversion to level 3.

    Returns:
        The smallest nonzero magnitude of an initial value of a state, `1.0`
        when the model has no state with a value.
    """
    assignments = set()
    rates = set()
    for index in range(model.getNumRules()):
        rule = model.getRule(index)
        if rule.isAssignment():
            assignments.add(rule.getVariable())
        elif rule.isRate():
            rates.add(rule.getVariable())
    sizes = {}
    values = []
    for index in range(model.getNumCompartments()):
        compartment = model.getCompartment(index)
        if compartment.isSetSize():
            sizes[compartment.getId()] = compartment.getSize()
            if compartment.getId() in rates:
                values.append(abs(compartment.getSize()))
    for index in range(model.getNumParameters()):
        parameter = model.getParameter(index)
        if parameter.getId() in rates and parameter.isSetValue():
            values.append(abs(parameter.getValue()))
    for index in range(model.getNumSpecies()):
        species = model.getSpecies(index)
        if species.getConstant() or species.getId() in assignments:
            continue
        if species.isSetInitialAmount():
            values.append(abs(species.getInitialAmount()))
        elif species.isSetInitialConcentration():
            size = (
                1.0
                if species.getHasOnlySubstanceUnits()
                else sizes.get(species.getCompartment(), 1.0)
            )
            values.append(abs(species.getInitialConcentration() * size))
    nonzero = [value for value in values if value > 0.0]
    return min(nonzero) if nonzero else 1.0


def solver_settings(
    relative_tolerance: float | None = None,
    absolute_tolerance: float | None = None,
    maximum_number_of_steps: int | None = None,
) -> dict[str, Any]:
    """Solver settings of a request of `simulation/1`.

    Every field of the settings of a request is explicit, so the defaults are
    spelled out here: CVODE with the time steps it chooses itself
    (`maximum_time_step` and `initial_time_step` `0.0`) and the linear solver
    and the jacobian the compiler chose (`auto`).

    Args:
        relative_tolerance: relative tolerance of CVODE,
            `RELATIVE_TOLERANCE` when `None`.
        absolute_tolerance: absolute tolerance of CVODE,
            `ABSOLUTE_TOLERANCE` when `None`.
        maximum_number_of_steps: internal steps of CVODE between two time
            points, `MAXIMUM_NUMBER_OF_STEPS` when `None`.

    Returns:
        The settings of the request.
    """
    return {
        "relative_tolerance": (
            RELATIVE_TOLERANCE if relative_tolerance is None else relative_tolerance
        ),
        "absolute_tolerance": {
            "scalar": (
                ABSOLUTE_TOLERANCE if absolute_tolerance is None else absolute_tolerance
            )
        },
        "maximum_num_steps": (
            MAXIMUM_NUMBER_OF_STEPS
            if maximum_number_of_steps is None
            else maximum_number_of_steps
        ),
        "maximum_time_step": 0.0,
        "initial_time_step": 0.0,
        "stiff": True,
        "linear_solver": "auto",
        "jacobian": "auto",
    }


def _scaled_tolerance(sbml: str, absolute_tolerance: float | None) -> float:
    """Absolute tolerance scaled with the smallest initial value of a state.

    Args:
        sbml: the compilable SBML document as string.
        absolute_tolerance: the absolute tolerance to scale,
            `ABSOLUTE_TOLERANCE` when `None`.

    Returns:
        The scaled tolerance, the given one when the model has no state
        below one or the scaled tolerance underflows to zero.
    """
    tolerance = ABSOLUTE_TOLERANCE if absolute_tolerance is None else absolute_tolerance
    model = libsbml.readSBMLFromString(sbml).getModel()
    scale = 1.0 if model is None else min(1.0, state_scale(model))
    if scale >= 1.0 or tolerance * scale == 0.0:
        return tolerance
    logger.info(
        "scaling the absolute tolerance %g with the smallest initial value of a "
        "state, %g",
        tolerance,
        scale,
    )
    return tolerance * scale


def run_timecourse(
    sbml: str | Path,
    selections: list[str],
    start: float = 0.0,
    end: float = 1.0,
    steps: int = 100,
    relative_tolerance: float | None = None,
    absolute_tolerance: float | None = None,
    maximum_number_of_steps: int | None = None,
    scale_tolerance: bool = True,
) -> pd.DataFrame:
    """Uniform timecourse of an SBML model.

    Args:
        sbml: SBML document as string, or the path of an SBML file.
        selections: the variables of the result after `time`, by id; a
            species in brackets (`[S1]`) is its concentration.
        start: start time.
        end: end time.
        steps: number of intervals, the result has `steps + 1` rows.
        relative_tolerance: relative tolerance of CVODE, see
            `solver_settings`.
        absolute_tolerance: absolute tolerance of CVODE, see
            `solver_settings`.
        maximum_number_of_steps: internal steps of CVODE between two time
            points, see `solver_settings`.
        scale_tolerance: multiply the absolute tolerance with the smallest
            initial value of a state when it is below one (`state_scale`),
            the tolerance of a model with small amounts would be above its
            states otherwise.

    Returns:
        The timecourse with `time` as first column and the selections after
        it, one row per time point.

    Raises:
        ImportError: if sbmlsim-core is not installed.
        SimulationError: if the model cannot be made compilable.
        sbmlsim_core.SbmlsimCoreError: if sbmlsim-core cannot compile, load
            or simulate the model.
    """
    text = Path(sbml).read_text(encoding="utf-8") if isinstance(sbml, Path) else sbml
    compilable = compilable_sbml(text)
    if scale_tolerance:
        absolute_tolerance = _scaled_tolerance(compilable, absolute_tolerance)
    compiled = _sbmlsim_core().compile_sbml(compilable)
    model = runtime().load(compiled.wasm, compiled.description)
    output = model.instance().simulate(
        {
            "contract": SIMULATION_CONTRACT,
            "start": start,
            "end": end,
            "output": {"uniform": {"steps": steps}},
            "preinit": [],
            "changes": [],
            "selections": list(selections),
            "settings": solver_settings(
                relative_tolerance, absolute_tolerance, maximum_number_of_steps
            ),
        }
    )
    return pd.DataFrame(output.values, columns=output.columns)
