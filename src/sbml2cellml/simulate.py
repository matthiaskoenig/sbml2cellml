"""Simulation of CellML models with libopencor.

libopencor is not on PyPI; it is imported when a simulation runs, so the rest
of the package works without it. See `LIBOPENCOR_INSTALL`.
"""

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt
from matplotlib.figure import Figure

logger = logging.getLogger(__name__)

#: first column of the timecourse of a model without variable of integration
STEADY_STATE_TIME = "time"
#: how to install libopencor, the message of the ImportError
LIBOPENCOR_INSTALL = (
    "libopencor is not installed. It is not on PyPI; install the wheel for "
    "your platform and python version from "
    "https://github.com/opencor/libopencor/releases, see "
    "https://matthiaskoenig.github.io/sbml2cellml/installation/"
)


class SimulationError(RuntimeError):
    """libopencor reported issues for the file, the document or the run."""


def _libopencor() -> Any:
    """Import libopencor with an installation hint on failure."""
    try:
        import libopencor
    except ImportError as err:
        raise ImportError(LIBOPENCOR_INSTALL) from err
    return libopencor


def _raise_on_issues(what: str, issues: Any) -> None:
    """Raise a SimulationError with the descriptions of the issues, if any."""
    descriptions = [issue.description for issue in issues]
    if descriptions:
        raise SimulationError(f"{what}: " + "; ".join(descriptions))


def _variable_name(name: str) -> str:
    """Variable name without the `component/` prefix of libopencor."""
    return name.rsplit("/", 1)[-1]


def _scalar(value: Any) -> float:
    """A constant of libopencor as a plain float.

    `task.constant(k)` and `task.computed_constant(k)` return the value
    repeated for every row as a numpy array rather than a single number;
    take the first element in that case.
    """
    if hasattr(value, "__len__"):
        value = value[0]
    return float(value)


def run_timecourse(
    cellml_path: Path,
    start: float = 0.0,
    end: float = 100.0,
    steps: int = 100,
    relative_tolerance: float | None = None,
    absolute_tolerance: float | None = None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Run a uniform timecourse of a CellML model.

    Args:
        cellml_path: path of the CellML file.
        start: start time of the output.
        end: end time of the output.
        steps: number of steps, the output has `steps + 1` rows.
        relative_tolerance: relative tolerance of the ODE solver, the
            libopencor default when `None`.
        absolute_tolerance: absolute tolerance of the ODE solver, the
            libopencor default when `None`.

    Returns:
        The timecourse with the variable of integration in the first column
        followed by the states, the algebraic variables, the constants and
        the computed constants, and the units of every column. A model
        without a variable of integration (an algebraic model, which
        libopencor solves as a steady state) has the same values at every
        time point, in a first column `time` of the requested time points.

    Raises:
        ImportError: if libopencor is not installed.
        SimulationError: if libopencor reports issues, e.g., for a model which
            is not valid or not fully constrained, or two result columns get
            the same name.
    """
    libopencor = _libopencor()
    path = Path(cellml_path).resolve()
    if not path.is_file():
        raise SimulationError(f"file: '{path}' does not exist")

    file = libopencor.File(str(path))
    _raise_on_issues("file", file.issues)
    document = libopencor.SedDocument(file)
    _raise_on_issues("document", document.issues)

    # the timecourse settings of the simulation libopencor created for the
    # file; an algebraic model gets a steady state simulation instead
    simulation = document.simulations[0]
    steady_state = isinstance(simulation, libopencor.SedSteadyState)
    if not steady_state:
        simulation.initial_time = start
        simulation.output_start_time = start
        simulation.output_end_time = end
        simulation.number_of_steps = steps
        if relative_tolerance is not None:
            simulation.ode_solver.relative_tolerance = relative_tolerance
        if absolute_tolerance is not None:
            simulation.ode_solver.absolute_tolerance = absolute_tolerance

    instance = document.instantiate()
    _raise_on_issues("instance", instance.issues)
    instance.run()
    _raise_on_issues("run", instance.issues)

    task = instance.tasks[0]
    data: dict[str, Any] = {}
    units: dict[str, str] = {}

    def add(name: str, values: Any, unit: str) -> None:
        # the component prefix is dropped, so two variables, or a variable
        # and the time points of a steady state, may get the same name
        if name in data:
            raise SimulationError(f"result: the name '{name}' occurs twice")
        data[name] = values
        units[name] = unit

    if steady_state:
        # one value per variable, repeated at the requested time points
        rows = steps + 1
        add(STEADY_STATE_TIME, np.linspace(start, end, rows), "")
    else:
        rows = len(task.voi)
        add(_variable_name(task.voi_name), task.voi, task.voi_unit)
    for k in range(task.state_count):
        add(_variable_name(task.state_name(k)), task.state(k), task.state_unit(k))
    for k in range(task.algebraic_variable_count):
        values = task.algebraic_variable(k)
        add(
            _variable_name(task.algebraic_variable_name(k)),
            [_scalar(values)] * rows if steady_state else values,
            task.algebraic_variable_unit(k),
        )
    for k in range(task.constant_count):
        add(
            _variable_name(task.constant_name(k)),
            [_scalar(task.constant(k))] * rows,
            task.constant_unit(k),
        )
    for k in range(task.computed_constant_count):
        add(
            _variable_name(task.computed_constant_name(k)),
            [_scalar(task.computed_constant(k))] * rows,
            task.computed_constant_unit(k),
        )

    logger.info("Simulated '%s': %d rows, %d columns", path, steps + 1, len(data))
    return pd.DataFrame(data), units


def plot_timecourse(
    df: pd.DataFrame, units: dict[str, str], show: bool = True
) -> Figure:
    """Plot every column of a timecourse against the first column.

    Args:
        df: timecourse from `run_timecourse`.
        units: units of the columns from `run_timecourse`.
        show: call `matplotlib.pyplot.show`.

    Returns:
        The figure.
    """
    fig, ax = plt.subplots(nrows=1, ncols=1)
    voi = df.columns[0]
    for name in df.columns[1:]:
        ax.plot(df[voi], df[name], label=f"{name} [{units[name]}]")
    ax.set_xlabel(f"{voi} [{units[voi]}]")
    ax.set_ylabel("value")
    ax.legend()
    if show:
        plt.show()
    return fig
