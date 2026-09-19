"""Simulator functions run inside a `SimulatorWorker`.

Every function imports its simulator lazily, so a worker process loads only
the simulator it is used for: roadrunner and libopencor bundle different LLVM
versions and crash once both have compiled in the same process. Results are
plain dictionaries (`columns`, `rows`) so they can be sent between processes.
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
    """Uniform timecourse of an SBML model with roadrunner.

    Args:
        sbml: SBML document as string.
        selections: roadrunner selections after `time`, e.g. `S1`, `[S1]`.
        start: start time.
        end: end time.
        steps: number of intervals, the result has `steps + 1` rows.
        relative_tolerance: relative tolerance of the integrator, the
            roadrunner default when `None`.
        absolute_tolerance: absolute tolerance of the integrator, the
            roadrunner default when `None`.
        maximum_number_of_steps: internal steps of the integrator between
            two time points, the roadrunner default (20000) when `None`.

    Returns:
        `columns` (the selections with `time` first) and `rows`.
    """
    import roadrunner

    roadrunner.Logger.setLevel(roadrunner.Logger.LOG_ERROR)
    rr = roadrunner.RoadRunner(sbml)
    if relative_tolerance is not None:
        rr.integrator.setValue("relative_tolerance", relative_tolerance)
    if absolute_tolerance is not None:
        rr.integrator.setValue("absolute_tolerance", absolute_tolerance)
    if maximum_number_of_steps is not None:
        rr.integrator.setValue("maximum_num_steps", maximum_number_of_steps)
    rr.timeCourseSelections = ["time", *selections]
    result = rr.simulate(start, end, steps + 1)
    return {
        "columns": list(result.colnames),
        "rows": [[float(value) for value in row] for row in result],
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
        `columns` (`time` first, then every variable) and `rows`.
    """
    from sbml2cellml.simulate import MAXIMUM_NUMBER_OF_STEPS, run_timecourse

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
    return {"columns": list(df.columns), "rows": df.to_numpy().tolist()}


def sleep(seconds: float) -> dict[str, Any]:
    """Sleep, for the timeout tests of the worker.

    Args:
        seconds: how long.

    Returns:
        `slept` with the seconds.
    """
    time.sleep(seconds)
    return {"slept": seconds}
