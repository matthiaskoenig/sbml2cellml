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

import hashlib
import logging
import math
import time
from collections import OrderedDict
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
#: how many compiled models `load_model` keeps, by the hash of their text
MODEL_CACHE_SIZE = 16
#: the compiled models of this process, oldest first
_MODELS: OrderedDict[bytes, Any] = OrderedDict()


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


def state_scale(model: Any) -> float:
    """Smallest nonzero magnitude of the initial value of a state.

    The states of the solver of an SBML model are the amounts of its
    species and the compartments and parameters a rate rule determines; the
    compiler lists them in the description of the model and the loaded model
    evaluates their initial values. An absolute tolerance above the
    magnitude of a state makes its trajectory meaningless, and the amounts
    of a model with a small compartment are small: a species with a
    concentration of 1 in a compartment of 1e-13 litre has the amount
    1e-13. `run_timecourse` therefore scales the absolute tolerance with
    this magnitude, as roadrunner does.

    Args:
        model: a `LoadedModel` of sbmlsim-core.

    Returns:
        The smallest nonzero magnitude of an initial value of a state, `1.0`
        when the model has no state with a finite value other than zero.
    """
    values = model.initial_values()
    magnitudes = [
        abs(values[state["id"]])
        for state in model.description["states"]
        if state["id"] in values
    ]
    nonzero = [value for value in magnitudes if value > 0.0 and math.isfinite(value)]
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


def load_model(sbml: str) -> Any:
    """Compile and load an SBML model, from the cache when it is there.

    The model is compiled to WebAssembly and loaded into the runtime of the
    process; the result is kept by the hash of the SBML text, so a model
    simulated again is neither converted with libsbml nor compiled a second
    time (libopencor caches a CellML file the same way). An instance of the
    loaded model is cheap and simulates on a store of its own, so the
    cached model is shared without a simulation seeing another one.

    Args:
        sbml: SBML document as string, every level.

    Returns:
        The `LoadedModel` of sbmlsim-core.

    Raises:
        ImportError: if sbmlsim-core is not installed.
        SimulationError: if the model cannot be made compilable.
        sbmlsim_core.SbmlsimCoreError: if sbmlsim-core cannot compile or
            load the model.
    """
    key = hashlib.sha256(sbml.encode("utf-8")).digest()
    model = _MODELS.get(key)
    if model is not None:
        _MODELS.move_to_end(key)
        return model
    compiled = _sbmlsim_core().compile_sbml(compilable_sbml(sbml), optimize=True)
    model = runtime().load(compiled.wasm, compiled.description)
    _MODELS[key] = model
    if len(_MODELS) > MODEL_CACHE_SIZE:
        _MODELS.popitem(last=False)
    return model


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
    warmup: bool = False,
    timings: dict[str, float] | None = None,
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
        warmup: simulate the model once on an instance of its own before
            the simulation of the result and keep the discarded simulation
            out of the integration time, as on the CellML side, where
            libopencor generates the code of a model when it runs it the
            first time.
        timings: filled with the wall time of the phases when given:
            `setup` is the conversion, the compilation and the loading of
            the model (nothing of it when the model is in the cache of
            `load_model`) and `simulate` the integration.

    Returns:
        The timecourse with `time` as first column and the selections after
        it, one row per time point.

    Raises:
        ImportError: if sbmlsim-core is not installed.
        SimulationError: if the model cannot be made compilable.
        sbmlsim_core.SbmlsimCoreError: if sbmlsim-core cannot compile, load
            or simulate the model.
    """
    started = time.perf_counter()
    text = Path(sbml).read_text(encoding="utf-8") if isinstance(sbml, Path) else sbml
    model = load_model(text)
    if scale_tolerance:
        scale = min(1.0, state_scale(model))
        tolerance = (
            ABSOLUTE_TOLERANCE if absolute_tolerance is None else absolute_tolerance
        )
        if scale < 1.0 and tolerance * scale > 0.0:
            logger.info(
                "scaling the absolute tolerance %g with the smallest initial value "
                "of a state, %g",
                tolerance,
                scale,
            )
            absolute_tolerance = tolerance * scale
    request = {
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
    if warmup:
        model.instance().simulate(request)
    instance = model.instance()
    prepared = time.perf_counter()
    output = instance.simulate(request)
    simulated = time.perf_counter()
    if timings is not None:
        timings["setup"] = prepared - started
        timings["simulate"] = simulated - prepared
    return pd.DataFrame(output.values, columns=output.columns)
