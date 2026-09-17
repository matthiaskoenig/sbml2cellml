"""The pipeline of the harness.

Every runnable case goes through five stages: the reference simulation of
the original SBML with roadrunner, the conversion to CellML, the libopencor
simulation of the CellML, the conversion back to SBML and the roadrunner
simulation of the roundtrip SBML. Every simulation is compared with the
expected results of the case. The simulators run in worker processes, the
conversions in this process.
"""

import logging
import re
from collections.abc import Callable
from pathlib import Path

import libsbml
import pandas as pd

from sbml2cellml import __version__, convert_cellml2sbml, convert_sbml2cellml
from sbml2cellml.testsuite.cases import SUITE_VERSION, Case, skip_reason
from sbml2cellml.testsuite.compare import (
    Comparison,
    compare,
    requested_frame,
    species_quantities,
    strip_brackets,
)
from sbml2cellml.testsuite.results import STAGES, CaseResult, StageResult, SuiteResult
from sbml2cellml.testsuite.worker import SimulatorWorker, frame

logger = logging.getLogger(__name__)

#: length of a failure message; generous, so the normalised reason key that
#: report._reason computes from it (REASON_LENGTH = 160, after quotes and
#: numbers collapse) always comes from the complete issue text rather than a
#: prefix cut short by the wrapper line
MESSAGE_LENGTH = 400
#: tight solver tolerances so the comparison measures the conversion, not the
#: integrator; passed to every roadrunner and libopencor simulation
RELATIVE_TOLERANCE = 1e-9
ABSOLUTE_TOLERANCE = 1e-12
#: an absolute path quoted in an exception message (e.g. the suite path of a
#: `CellMLValidationError`), reduced to its basename so the message does not
#: depend on the machine it ran on
_ABSOLUTE_PATH = re.compile(r"'[^']*/([^/']+)'")


def _message(err: BaseException) -> str:
    """Type and the relevant line of an exception, shortened.

    Absolute paths quoted in the exception text are reduced to their
    basename first, so the message does not depend on `$HOME` or the suite
    location. When the first line ends with `:` and a second line exists
    (e.g. a `CellMLValidationError` whose message is a wrapper line -
    `CellML model '...' converted from '...' has N errors:` - followed by
    the list of issues), the wrapper line is dropped entirely and the
    message is built from the second line instead, so it carries the
    complete first issue rather than a wrapper prefix cut short by however
    many digits the error count has. Otherwise the first line is used as
    is.
    """
    text = _ABSOLUTE_PATH.sub(r"'\1'", str(err))
    lines = text.strip().splitlines()
    first = lines[0] if lines else ""
    content = lines[1].strip() if first.endswith(":") and len(lines) > 1 else first
    return f"{type(err).__name__}: {content}"[:MESSAGE_LENGTH]


def _stage(comparison: Comparison) -> StageResult:
    """Stage result of a comparison."""
    return StageResult(
        "pass" if comparison.passed else "fail",
        comparison.message[:MESSAGE_LENGTH],
        None if not comparison.variables else comparison.max_excess,
    )


def reference_selections(case: Case, model: libsbml.Model) -> list[str]:
    """Roadrunner selections of the settings variables of the original model.

    A species expected as concentration is selected as `[id]`, everything
    else by id.
    """
    species = {s.getId() for s in model.getListOfSpecies()}
    return [
        f"[{v}]" if v in species and v in case.settings.concentration else v
        for v in case.settings.variables
    ]


def run_case(
    case: Case, work_dir: Path, roadrunner: SimulatorWorker, libopencor: SimulatorWorker
) -> CaseResult:
    """Run the five stages of a case.

    Args:
        case: a runnable case.
        work_dir: directory for the converted files.
        roadrunner: worker for the SBML simulations.
        libopencor: worker for the CellML simulation.

    Returns:
        The stage results; a stage whose input stage failed is `skip`. Every
        stage is `fail` when the case itself cannot be set up (e.g. an
        unparsable SBML file). When `case.expected` is `None`, the reference
        simulation becomes the expected results for `libopencor` and
        `roundtrip` when it succeeds; when it fails, those two stages are
        `skip` (`reference failed`) instead of running, and `reference`
        itself has no `max_excess` (there is nothing to compare it with).
    """
    assert case.sbml_path is not None
    settings = case.settings

    def _result(stages: dict[str, StageResult]) -> CaseResult:
        return CaseResult(
            case.id,
            list(case.test_tags),
            list(case.component_tags),
            stages,
            name=case.name,
        )

    try:
        model = libsbml.readSBMLFromFile(str(case.sbml_path)).getModel()
        if model is None:
            raise ValueError("no model in the SBML file")
        quantities = species_quantities(model)
        compartments = [c.getId() for c in model.getListOfCompartments()]
    except Exception as err:
        message = f"setup: {_message(err)}"[:MESSAGE_LENGTH]
        stages = {stage: StageResult("fail", message) for stage in STAGES}
        return _result(stages)

    stages: dict[str, StageResult] = {}

    # reference
    expected: pd.DataFrame | None = case.expected
    try:
        result = roadrunner.call(
            "simulate_sbml",
            sbml=case.sbml_path.read_text(encoding="utf-8"),
            selections=reference_selections(case, model),
            start=settings.start,
            end=settings.end,
            steps=settings.steps,
            relative_tolerance=RELATIVE_TOLERANCE,
            absolute_tolerance=ABSOLUTE_TOLERANCE,
        )
        reference = strip_brackets(frame(result))
        if expected is None:
            expected = reference
            stages["reference"] = StageResult("pass")
        else:
            stages["reference"] = _stage(compare(reference, expected, settings))
    except Exception as err:
        stages["reference"] = StageResult("fail", _message(err))

    # sbml2cellml
    cellml_path = work_dir / f"{case.id}.cellml"
    try:
        convert_sbml2cellml(case.sbml_path, cellml_path=cellml_path, validate=True)
        stages["sbml2cellml"] = StageResult("pass")
    except Exception as err:
        stages["sbml2cellml"] = StageResult("fail", _message(err))
        for stage in ("libopencor", "cellml2sbml", "roundtrip"):
            stages[stage] = StageResult("skip", "sbml2cellml failed")
        return _result(stages)

    # libopencor
    if expected is None:
        stages["libopencor"] = StageResult("skip", "reference failed")
    else:
        try:
            result = libopencor.call(
                "simulate_cellml",
                cellml_path=str(cellml_path),
                start=settings.start,
                end=settings.end,
                steps=settings.steps,
                relative_tolerance=RELATIVE_TOLERANCE,
                absolute_tolerance=ABSOLUTE_TOLERANCE,
            )
            df = requested_frame(frame(result), quantities, settings)
            stages["libopencor"] = _stage(compare(df, expected, settings))
        except Exception as err:
            stages["libopencor"] = StageResult("fail", _message(err))

    # cellml2sbml
    roundtrip_path = work_dir / f"{case.id}-roundtrip.xml"
    try:
        convert_cellml2sbml(cellml_path, sbml_path=roundtrip_path, validate=True)
        stages["cellml2sbml"] = StageResult("pass")
    except Exception as err:
        stages["cellml2sbml"] = StageResult("fail", _message(err))
        stages["roundtrip"] = StageResult("skip", "cellml2sbml failed")
        return _result(stages)

    # roundtrip
    if expected is None:
        stages["roundtrip"] = StageResult("skip", "reference failed")
    else:
        try:
            selections = list(dict.fromkeys([*settings.variables, *compartments]))
            result = roadrunner.call(
                "simulate_sbml",
                sbml=roundtrip_path.read_text(encoding="utf-8"),
                selections=selections,
                start=settings.start,
                end=settings.end,
                steps=settings.steps,
                relative_tolerance=RELATIVE_TOLERANCE,
                absolute_tolerance=ABSOLUTE_TOLERANCE,
            )
            df = requested_frame(frame(result), quantities, settings)
            stages["roundtrip"] = _stage(compare(df, expected, settings))
        except Exception as err:
            stages["roundtrip"] = StageResult("fail", _message(err))

    return _result(stages)


def run_suite(
    cases: list[Case],
    work_dir: Path,
    timeout: float = 60.0,
    progress: Callable[[str], None] | None = None,
) -> SuiteResult:
    """Run the pipeline for every runnable case.

    Args:
        cases: the cases; unrunnable ones are recorded as skipped.
        work_dir: directory for the converted files, created if needed.
        timeout: seconds per simulator call.
        progress: called with the finished status line of the case after
            every runnable case, e.g. `00001 reference=pass sbml2cellml=pass
            libopencor=fail cellml2sbml=pass roundtrip=fail`.

    Returns:
        The suite result.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    result = SuiteResult(suite=SUITE_VERSION, version=__version__)
    runnable = []
    for case in cases:
        reason = skip_reason(case)
        if reason is None:
            runnable.append(case)
        else:
            result.skipped[case.id] = reason
    if not runnable:
        return result
    with (
        SimulatorWorker("roadrunner", timeout) as roadrunner,
        SimulatorWorker("libopencor", timeout) as libopencor,
    ):
        for case in runnable:
            logger.info("case %s", case.id)
            case_result = run_case(case, work_dir, roadrunner, libopencor)
            result.cases[case.id] = case_result
            if progress is not None:
                statuses = " ".join(
                    f"{stage}={case_result.stages[stage].status}" for stage in STAGES
                )
                progress(f"{case.id} {statuses}")
    return result
