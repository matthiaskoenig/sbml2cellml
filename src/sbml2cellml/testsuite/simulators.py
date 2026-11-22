"""Simulator functions run inside a `SimulatorWorker`.

Every function imports its simulator lazily, so a worker process loads only
the simulator it is used for. Results are plain dictionaries (`columns`,
`rows`, `seconds`) so they can be sent between processes. `seconds` is the
wall time of the simulation, measured around the call of the simulator in
the worker process, so it holds no overhead of the harness: it is the time a
user waits for the model, the compilation of the model included.
"""

import time
from pathlib import Path
from typing import Any


def simulate_sbml(
    sbml: str,
    selections: list[str],
    start: float,
    end: float,
    steps: int,
    relative_tolerance: float | None = None,
    absolute_tolerance: float | None = None,
    maximum_number_of_steps: int | None = None,
) -> dict[str, Any]:
    """Uniform timecourse of an SBML model with sbmlsim-core.

    Args:
        sbml: SBML document as string.
        selections: selections after `time`, e.g. `S1`, `[S1]`.
        start: start time.
        end: end time.
        steps: number of intervals, the result has `steps + 1` rows.
        relative_tolerance: relative tolerance of the integrator, the
            default of `sbml2cellml.sbmlsim` when `None`.
        absolute_tolerance: absolute tolerance of the integrator, the
            default of `sbml2cellml.sbmlsim` when `None`.
        maximum_number_of_steps: internal steps of the integrator between
            two time points, the default of `sbml2cellml.sbmlsim` when
            `None`.

    Returns:
        `columns` (the selections with `time` first), `rows` and `seconds`.
    """
    from sbml2cellml.sbmlsim import run_timecourse

    started = time.perf_counter()
    df = run_timecourse(
        sbml,
        selections,
        start=start,
        end=end,
        steps=steps,
        relative_tolerance=relative_tolerance,
        absolute_tolerance=absolute_tolerance,
        maximum_number_of_steps=maximum_number_of_steps,
    )
    seconds = time.perf_counter() - started
    return {
        "columns": list(df.columns),
        "rows": df.to_numpy().tolist(),
        "seconds": seconds,
    }


def simulate_cellml(
    cellml_path: str,
    start: float,
    end: float,
    steps: int,
    relative_tolerance: float | None = None,
    absolute_tolerance: float | None = None,
    maximum_number_of_steps: int | None = None,
) -> dict[str, Any]:
    """Uniform timecourse of a CellML model with libopencor.

    Args:
        cellml_path: path of the CellML file.
        start: start time.
        end: end time.
        steps: number of intervals.
        relative_tolerance: relative tolerance of the ODE solver, the
            libopencor default when `None`.
        absolute_tolerance: absolute tolerance of the ODE solver, the
            libopencor default when `None`.
        maximum_number_of_steps: internal steps of the ODE solver between
            two time points, the default of `run_timecourse` when `None`.

    Returns:
        `columns` (`time` first, then every variable), `rows` and `seconds`.
    """
    from sbml2cellml.simulate import MAXIMUM_NUMBER_OF_STEPS, run_timecourse

    started = time.perf_counter()
    df, _ = run_timecourse(
        Path(cellml_path),
        start=start,
        end=end,
        steps=steps,
        relative_tolerance=relative_tolerance,
        absolute_tolerance=absolute_tolerance,
        maximum_number_of_steps=(
            MAXIMUM_NUMBER_OF_STEPS
            if maximum_number_of_steps is None
            else maximum_number_of_steps
        ),
    )
    seconds = time.perf_counter() - started
    return {
        "columns": list(df.columns),
        "rows": df.to_numpy().tolist(),
        "seconds": seconds,
    }


def sleep(seconds: float) -> dict[str, Any]:
    """Sleep, for the timeout tests of the worker.

    Args:
        seconds: how long.

    Returns:
        `slept` with the seconds.
    """
    time.sleep(seconds)
    return {"slept": seconds}
